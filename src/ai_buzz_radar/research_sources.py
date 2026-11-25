"""Research-paper and publisher-index discovery for the daily edition."""

import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode, urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from ai_buzz_radar.blogs import SOURCES, Candidate, Source, discover, fetch

ARXIV_HTML = Source("arXiv", "https://arxiv.org/", ("/html/",))
ARXIV_LIMIT = 80
LANGCHAIN = Source("LangChain", "https://www.langchain.com/blog", ("/blog/",))
DEVELOPER_SOURCES = (LANGCHAIN,)
ARTICLE_BODY_SELECTOR = (
    ".article-content, .blog-content, [data-article-body], .post-content, "
    ".text-rich-text-v2-blog-post"
)


def arxiv_query_url(day, days):
    start = day - timedelta(days=days - 1)
    params = {
        "search_query": (
            '(ti:agent OR ti:agents OR ti:agentic OR ti:"tool use" OR ti:"tool-use") AND '
            f"submittedDate:[{start:%Y%m%d}0000 TO {day:%Y%m%d}2359]"
        ),
        "max_results": ARXIV_LIMIT,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    return "https://export.arxiv.org/api/query?" + urlencode(params)


def arxiv_candidates(data, start, day):
    feed = ElementTree.fromstring(data)
    if feed.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("Expected an arXiv Atom feed")
    by_id = {}
    for entry in feed.findall("{*}entry"):
        identifier = entry.findtext("{*}id", "")
        match = re.fullmatch(r"https?://arxiv\.org/abs/(\d{4}\.\d{4,5})v(\d+)", identifier)
        if not match:
            raise ValueError(f"Invalid arXiv entry: {entry.findtext('{*}title', '')[:100]}")
        published = date.fromisoformat(entry.findtext("{*}published", "")[:10])
        updated = date.fromisoformat(entry.findtext("{*}updated", "")[:10])
        # The index only supplies the current title and abstract. Backdated editions
        # cannot safely use an entry whose returned version postdates the cutoff.
        if not (start <= published <= updated <= day):
            continue
        paper_id, version = match.groups()
        title = " ".join(entry.findtext("{*}title", "").split())
        if title and (paper_id not in by_id or int(version) > by_id[paper_id][0]):
            summary = " ".join(entry.findtext("{*}summary", "").split())
            item = Candidate(
                title, f"https://arxiv.org/html/{paper_id}v{version}", published, "arXiv", summary
            )
            by_id[paper_id] = int(version), item
    return [item for _, item in by_id.values()]


def langchain_candidates(day, start, loader):
    # Webflow's RSS pubDate can reflect re-publication months after the original.
    # The dated, paginated Recent Stories cards match the publication's own bylines.
    page = LANGCHAIN.index
    seen = set()
    rows = {}
    while page:
        if page in seen:
            return list(rows.values()), ["LangChain: repeated index page"]
        seen.add(page)
        try:
            soup = BeautifulSoup(loader(page), "html.parser")
            dates = []
            for card in soup.select(".blog-list.is-normal > .blog-item"):
                heading, stamp = card.select_one("h2"), card.select_one(".date-color")
                link = card.select_one("a.blog-link-absolute[href]")
                if not (heading and stamp and link):
                    continue
                url = urljoin(page, link["href"])
                if not LANGCHAIN.accepts(url):
                    continue
                published = datetime.strptime(stamp.get_text(strip=True), "%B %d, %Y").date()
                dates.append(published)
                if start <= published <= day:
                    labels = [t.get_text(strip=True) for t in card.select(".blog-categories-label")]
                    picture = card.select_one(".blog-thumbnail[alt]")
                    if picture and picture["alt"]:
                        labels.append(picture["alt"])
                    rows[url] = Candidate(
                        heading.get_text(" ", strip=True),
                        url,
                        published,
                        LANGCHAIN.name,
                        " · ".join(labels)[:350],
                    )
            if not dates:
                raise ValueError("No dated recent stories")
            next_page = soup.select_one("a.w-pagination-next[href]")
            if min(dates) < start or not next_page:
                break
            page = urljoin(LANGCHAIN.index, next_page["href"])
            parts = urlsplit(page)
            if (parts.scheme, parts.netloc, parts.path) != ("https", "www.langchain.com", "/blog"):
                raise ValueError("Unexpected pagination destination")
        except (OSError, ValueError) as exc:
            return list(rows.values()), [f"LangChain: {exc}"]
    return list(rows.values()), []


def discover_editions(day, days, loader=fetch, sources=SOURCES):
    publishers = [s for s in sources if s != LANGCHAIN]
    try:
        rows, warnings = discover(day, days, loader, publishers) if publishers else ([], [])
    except RuntimeError as exc:
        rows, warnings = [], [str(exc)]
    if LANGCHAIN in sources:
        posts, alerts = langchain_candidates(day, day - timedelta(days=days - 1), loader)
        rows.extend(posts)
        warnings.extend(alerts)
    try:
        data = loader(arxiv_query_url(day, days))
        papers = arxiv_candidates(data, day - timedelta(days=days - 1), day)
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        warnings.append(f"arXiv: {exc}")
        papers = []
    return sorted(rows + papers, key=lambda c: (c.published, c.title), reverse=True), warnings
