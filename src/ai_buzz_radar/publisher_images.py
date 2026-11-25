"""Select, verify and retain figures from the original publisher."""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from pydantic import Field
from resvg_py import svg_to_bytes

from ai_buzz_radar.models import Record
from ai_buzz_radar.research_sources import ARTICLE_BODY_SELECTOR

LOG = logging.getLogger(__name__)
IMAGE_CDNS = {
    "openai.com": {"images.ctfassets.net", "cdn.openai.com"},
    "www.anthropic.com": {"www-cdn.anthropic.com", "assets.claude.com"},
    "huggingface.co": {"cdn-uploads.huggingface.co"},
    "blog.cloudflare.com": {"cf-assets.www.cloudflare.com"},
    "www.langchain.com": {"cdn.prod.website-files.com"},
    "lilianweng.github.io": set(),
    "arxiv.org": set(),
}


class OriginalImage(Record):
    title: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    alt: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://[^\s]+$")
    asset_url: str = Field(pattern=r"^https://[^\s]+$")
    filename: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*\.(png|jpe?g|gif|webp)$")


class ImageChoice(Record):
    index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=90)
    caption: str = Field(min_length=1, max_length=260)
    alt: str = Field(min_length=1, max_length=260)


@dataclass(frozen=True)
class ImageCandidate:
    asset_url: str
    source_url: str
    heading: str
    alt: str
    caption: str
    context: str = ""


def image_candidates(data, article_url):
    soup = BeautifulSoup(data, "html.parser")
    body = soup.select_one(ARTICLE_BODY_SELECTOR)
    body = body or soup.select_one("article")
    publisher = urlsplit(article_url).netloc
    if body is None or publisher not in IMAGE_CDNS:
        return []
    allowed = {publisher} | IMAGE_CDNS[publisher]
    candidates = []
    seen = set()
    heading, section_url = "", article_url
    for tag in body.select('h2,h3,h4,img,object[type="image/svg+xml"]'):
        if tag.find_parent(["nav", "footer", "aside"]):
            continue
        if tag.name.startswith("h"):
            heading = tag.get_text(" ", strip=True)
            if heading.casefold() in {"keep reading", "related articles", "related posts"}:
                break
            anchor = tag if tag.get("id") else tag.select_one("[id]")
            anchor = anchor or next((p for p in list(tag.parents)[:2] if p.get("id")), None)
            fragment = (
                quote(anchor["id"], safe="") if anchor else ":~:text=" + quote(heading, safe="")
            )
            section_url = article_url + "#" + fragment
            continue
        figure = tag.find_parent("figure")
        legend = figure.find("figcaption") if figure else None
        caption = legend.get_text(" ", strip=True) if legend else ""
        image_source = section_url
        if tag.name == "object" and publisher != "arxiv.org":
            continue
        if publisher == "arxiv.org":
            # A caption can describe a whole multi-panel figure. Only use images
            # that actually represent that whole figure.
            if not figure or not caption or len(figure.select("img,object,svg")) != 1:
                continue
            if figure.get("id"):
                image_source = article_url + "#" + quote(figure["id"], safe="")
        alt = tag.get("alt", "").strip()
        if tag.find_parent("a", href=re.compile(r"/(?:author|profile)s?/")):
            continue
        responsive = sorted(
            (int(width), url) for url, width in re.findall(r"(\S+)\s+(\d+)w", tag.get("srcset", ""))
        )
        src = tag.get("data") if tag.name == "object" else tag.get("src") or tag.get("data-src", "")
        if responsive:
            src = next((url for width, url in responsive if width >= 1000), responsive[-1][1])
        if not src:
            continue
        asset = urljoin(article_url, src)
        parts = urlsplit(asset)
        if parts.scheme != "https" or parts.netloc not in allowed or asset in seen:
            continue
        if re.search(
            r"(?:^|[-_/. ])(?:logo|icon|avatar|emoji|art[-_ ]card|social[-_ ]card)(?:$|[-_/. ])",
            (unquote(parts.path) + " " + alt).lower(),
        ) or (parts.path.lower().endswith(".svg") and publisher != "arxiv.org"):
            continue
        context = ""
        if not (alt or caption):
            # Webflow blog figures often have no alt/caption. Offer an identifiable body
            # figure with the publisher's descriptive asset name and adjacent explanation.
            if publisher != "www.langchain.com" or not figure or not heading:
                continue
            asset_name = unquote(Path(parts.path).stem).rsplit("_", 1)[-1]
            following = figure.find_next_sibling()
            if not re.search(r"[A-Za-z]{3}", asset_name) or not following or following.name != "p":
                continue
            explanation = following.get_text(" ", strip=True)[:600]
            context = f"Asset name: {asset_name}. Following paragraph: {explanation}"
        candidates.append(
            ImageCandidate(asset, image_source, heading[:200], alt[:800], caption[:800], context)
        )
        seen.add(asset)
        if len(candidates) == 24:
            break
    return candidates


def image_catalog(candidates):
    return [
        {"index": i, "section": c.heading, "alt": c.alt, "caption": c.caption, "context": c.context}
        for i, c in enumerate(candidates)
    ]


def raster_extension(data):
    if len(data) < 16 or len(data) > 4_000_000:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR" and data[-8:-4] == b"IEND":
        return "png"
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a") and data.endswith(b";"):
        return "gif"
    if (
        data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
        and data[12:16] in (b"VP8 ", b"VP8L", b"VP8X")
        and int.from_bytes(data[4:8], "little") == len(data) - 8
    ):
        return "webp"
    return None


def rasterize_paper_svg(data):
    # Render a standalone drawing only. No external styles, fonts, other documents
    # or raster resources should be read on the publisher's behalf.
    if len(data) > 4_000_000:
        raise ValueError("SVG exceeds download limit")
    markup = data.decode("utf-8-sig")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet|@import", markup, re.I):
        raise ValueError("SVG contains external resource declarations")
    root = ElementTree.fromstring(markup)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Expected an SVG document")
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() in {
            "image",
            "feimage",
            "foreignobject",
            "script",
            "filter",
        }:
            raise ValueError("SVG is not a standalone static drawing")
        for name, value in node.attrib.items():
            if name.rsplit("}", 1)[-1] == "href" and not value.strip().startswith("#"):
                raise ValueError("SVG references an external resource")
    if any(
        not url.strip(" '\"").startswith("#") for url in re.findall(r"url\(([^)]*)\)", markup, re.I)
    ):
        raise ValueError("SVG contains an external paint or font reference")
    return svg_to_bytes(svg_string=markup, dpi=96, width=1400, height=1400)


def save_original(choice, candidates, output_folder, loader, *, audit=None):
    audit = {} if audit is None else audit
    audit.update(candidate_count=len(candidates), status="unavailable")
    if not candidates:
        audit["reason"] = "原文没有可识别并核实出处的候选图"
        return None
    if choice is None:
        audit["reason"] = "成稿未选中能支持本篇摘要的原图"
        return None
    if choice.index >= len(candidates):
        audit["reason"] = "原图选择超出候选目录"
        return None
    candidate = candidates[choice.index]
    audit.update(source_url=candidate.source_url, asset_url=candidate.asset_url)
    try:
        data = loader(candidate.asset_url)
        publisher_sha = hashlib.sha256(data).hexdigest()
        link = urlsplit(candidate.asset_url)
        converted = link.netloc == "arxiv.org" and link.path.lower().endswith(".svg")
        if converted:
            data = rasterize_paper_svg(data)
    except (OSError, ValueError, ElementTree.ParseError) as error:
        audit["reason"] = f"获取或转换原图失败：{error}"
        LOG.warning("Could not retrieve publisher image %s: %s", candidate.asset_url, error)
        return None
    extension = raster_extension(data)
    if not extension:
        audit["reason"] = "原图格式不支持或文件不完整"
        LOG.warning("Unsupported or incomplete publisher image: %s", candidate.asset_url)
        return None
    digest = hashlib.sha256(data).hexdigest()
    filename = digest + "." + extension
    folder = output_folder / "figures" / "originals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        with NamedTemporaryFile(dir=folder, delete=False) as temp:
            temp.write(data)
        Path(temp.name).replace(path)
        path.chmod(0o644)
    audit.update(
        status="saved",
        sha256=digest,
        publisher_sha256=publisher_sha,
        format="svg_to_png" if converted else extension,
    )
    return OriginalImage(
        title=choice.title,
        caption=choice.caption,
        alt=choice.alt,
        source_url=candidate.source_url,
        asset_url=candidate.asset_url,
        filename=filename,
    )
