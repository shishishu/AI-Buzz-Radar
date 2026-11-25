"""Publication dates, canonical article links and source passages for the blog reader."""

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from textwrap import wrap
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Source:
    name: str
    index: str
    paths: tuple[str, ...]
    rss: bool = False

    def accepts(self, url: str) -> bool:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.netloc == urlsplit(self.index).netloc
            and parts.path.startswith(self.paths)
            and not parts.query
            and not parts.fragment
        )


SOURCES = (
    Source(
        "Anthropic Engineering",
        "https://www.anthropic.com/engineering",
        ("/research/", "/engineering/"),
    ),
    Source(
        "Anthropic Research", "https://www.anthropic.com/research", ("/research/", "/engineering/")
    ),
    Source("Lil’Log", "https://lilianweng.github.io/index.xml", ("/posts/",), rss=True),
)


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != "https" or new.netloc != old.netloc:
            raise ValueError("Unexpected cross-site redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> bytes:
    # METR syndicates full reports in one feed, already larger than an article.
    limit = 12_000_000 if url == "https://metr.org/feed.xml" else 4_000_000
    request = Request(url, headers={"User-Agent": "AI-Buzz-Radar/0.1 (technical blog reader)"})
    with build_opener(SameSiteRedirect()).open(request, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Source exceeded article size limit")
    return data


@dataclass(frozen=True)
class Candidate:
    title: str
    url: str
    published: date
    source: str
    description: str


def listings(source: Source, data: bytes) -> list[Candidate]:
    rows = []
    if source.rss:
        for item in ElementTree.fromstring(data).findall("./channel/item"):
            url = item.findtext("link", "")
            if source.accepts(url):
                desc = BeautifulSoup(item.findtext("description", ""), "html.parser")
                rows.append(
                    Candidate(
                        item.findtext("title", ""),
                        url,
                        parsedate_to_datetime(item.findtext("pubDate")).date(),
                        source.name,
                        desc.get_text(" ", strip=True)[:350],
                    )
                )
    else:
        soup = BeautifulSoup(data, "html.parser")
        for card in soup.select("article"):
            link, stamp = card.select_one("h3 a[href], h2 a[href]"), card.select_one("time")
            if not link or not stamp:
                continue
            url = urljoin(source.index, link["href"])
            if not source.accepts(url):
                continue
            day = stamp.get("datetime") or stamp.get_text(strip=True)
            published = (
                date.fromisoformat(day[:10])
                if re.match(r"^\d{4}-", day)
                else datetime.strptime(day, "%b %d, %Y").date()
            )
            desc = card.select_one("p")
            rows.append(
                Candidate(
                    link.get_text(" ", strip=True),
                    url,
                    published,
                    source.name,
                    desc.get_text(" ", strip=True)[:350] if desc else "",
                )
            )
    if not rows:
        raise ValueError("No dated article links found")
    return rows


def discover(
    day: date, days: int, loader=fetch, sources=SOURCES
) -> tuple[list[Candidate], list[str]]:
    start = day - timedelta(days=days - 1)
    by_url = {}
    warnings = []
    for source in sources:
        try:
            rows = listings(source, loader(source.index))
        except (OSError, ValueError, TypeError, ElementTree.ParseError) as err:
            warnings.append(f"{source.name}: {err}")
            continue
        for item in rows:
            if start <= item.published <= day:
                old = by_url.get(item.url)
                if old is None:
                    by_url[item.url] = item
                elif len(item.description) > len(old.description):
                    by_url[item.url] = replace(old, description=item.description)
    if len(warnings) == len(sources):
        raise RuntimeError("; ".join(warnings))
    return sorted(
        by_url.values(), key=lambda item: (item.published, item.title), reverse=True
    ), warnings


def sections(data: bytes) -> list[tuple[str, str]]:
    soup = BeautifulSoup(data, "html.parser")
    body = soup.select_one("[data-article-body], .post-content") or soup.select_one("article")
    if body is None:
        raise ValueError("Article text unavailable")
    result = []
    title, paragraphs = "Introduction", []
    for tag in body.select("h2,h3,h4,p,li,figcaption"):
        if tag.find_parent(["p", "li", "figcaption"]):
            continue
        content = " ".join(tag.stripped_strings)
        if tag.name.startswith("h"):
            if paragraphs:
                result.append((title, "\n".join(paragraphs)))
            title, paragraphs = content, []
        elif content:
            paragraphs.append(content)
    if paragraphs:
        result.append((title, "\n".join(paragraphs)))
    if not result:
        raise ValueError("Article has no readable sections")
    # Keep long sections addressable without putting an entire article into a tool result.
    passages = []
    for heading, text in result:
        chunks = wrap(text, width=4000, replace_whitespace=False) if len(text) > 4000 else [text]
        for index, chunk in enumerate(chunks):
            label = heading if len(chunks) == 1 else f"{heading} ({index + 1}/{len(chunks)})"
            passages.append((label, chunk))
    return passages


class Reader:
    def __init__(self, candidates, loader=fetch):
        self.candidates = candidates
        self.loader = loader
        self.errors = {}
        self.cache = {}
        self.passages = {}

    def catalog(self):
        return [
            {**asdict(item), "published": item.published.isoformat(), "article": i}
            for i, item in enumerate(self.candidates)
        ]

    def read(self, arguments: str) -> dict:
        try:
            params = json.loads(arguments)
            article, section = params["article"], params["section"]
            if type(article) is not int or not 0 <= article < len(self.candidates):
                raise ValueError("Unknown article")
            if type(section) is not int or section < -1:
                raise ValueError("Unknown section")
            if article not in self.cache:
                url = self.candidates[article].url
                try:
                    self.cache[article] = sections(self.loader(url))
                except (ValueError, OSError) as error:
                    self.errors[url] = str(error)
                    raise
                self.errors.pop(url, None)
            parts = self.cache[article]
            if section == -1:
                return {
                    "article": article,
                    "sections": [
                        {"section": i, "heading": h, "preview": p[:75]}
                        for i, (h, p) in enumerate(parts)
                    ],
                }
            heading, passage = parts[section]
            self.passages[article, section] = passage
            return {"article": article, "section": section, "heading": heading, "text": passage}
        except (KeyError, IndexError, ValueError, TypeError, URLError, OSError) as err:
            return {"error": str(err)}
