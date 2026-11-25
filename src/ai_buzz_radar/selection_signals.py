"""Dated external discussion attached only to the primary work it actually links to."""

import json
import re
from datetime import datetime, time, timedelta
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from ai_buzz_radar.agent import TIMEZONE


def work_key(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    paper = re.fullmatch(r"/(?:abs|html|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?", parts.path)
    if parts.hostname in ("arxiv.org", "www.arxiv.org") and paper:
        return "arxiv:" + paper[1]
    return (parts.hostname or "", parts.path.rstrip("/"), parts.query)


def recent(stamp, start, day):
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if (
            value.tzinfo is not None
            and start <= (local := value.astimezone(TIMEZONE).date()) <= day
        ):
            return local.isoformat()
    except (AttributeError, ValueError):
        pass
    return None


def hn_discussions(day, candidates, loader):
    start = day - timedelta(days=29)
    since = int(datetime.combine(start, time.min, TIMEZONE).timestamp())
    until = int(datetime.combine(day + timedelta(days=1), time.min, TIMEZONE).timestamp())
    keys = {work_key(item.url): item.url for item in candidates}
    signals, queries, errors, seen = {}, [], [], set()
    if not keys:
        return signals, queries, errors
    for term in ("agent", "memory", "self-improvement", "time horizon"):
        params = dict(
            tags="story",
            query=term,
            restrictSearchableAttributes="title",
            hitsPerPage=100,
            numericFilters=f"created_at_i>={since},created_at_i<{until}",
        )
        query = "https://hn.algolia.com/api/v1/search?" + urlencode(params)
        queries.append(query)
        try:
            hits = json.loads(loader(query))["hits"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"HN ({term}): {exc}")
            continue
        for hit in hits:
            story = str(hit.get("objectID", ""))
            url = keys.get(work_key(hit.get("url") or ""))
            if (
                not url
                or not story.isdecimal()
                or story in seen
                or len(seen) >= 24
                or len(signals.get(url, [])) >= 3
            ):
                continue
            seen.add(story)
            try:
                thread = json.loads(loader("https://hn.algolia.com/api/v1/items/" + story))
                if work_key(thread.get("url") or "") != work_key(url):
                    continue
                for comment in thread.get("children", []):
                    stamp = recent(comment.get("created_at"), start, day)
                    author = comment.get("author")
                    quote = BeautifulSoup(comment.get("text") or "", "html.parser").get_text(
                        " ", strip=True
                    )
                    cid = str(comment.get("id", ""))
                    if (
                        not stamp
                        or not cid.isdecimal()
                        or not author
                        or author == thread.get("author")
                        or author.lower().endswith("bot")
                        or len(quote) < 60
                    ):
                        continue
                    signals.setdefault(url, []).append(
                        {
                            "source": "Hacker News",
                            "date": stamp,
                            "author": author,
                            "url": "https://news.ycombinator.com/item?id=" + cid,
                            "text": quote[:600],
                        }
                    )
                    if len(signals[url]) >= 3:
                        break
            except (OSError, ValueError, TypeError, KeyError) as exc:
                errors.append(f"HN ({story}): {exc}")
    return signals, queries, errors


def hf_discussions(day, paper_id, loader):
    url = f"https://huggingface.co/papers/{paper_id}"
    soup = BeautifulSoup(loader(url), "html.parser")
    node = soup.select_one('[data-target="PaperContent"][data-props]')
    if not node:
        raise ValueError("Paper discussion unavailable")
    payload = json.loads(node["data-props"])
    paper = payload["paper"]
    if paper.get("id") != paper_id:
        raise ValueError("Discussion is for a different paper")
    authors = {(entry.get("user") or {}).get("name") for entry in paper["authors"]}
    full_names = {entry["name"].casefold() for entry in paper["authors"] if entry.get("name")}
    # The author's opening announcement, automated summaries and votes are not discussion.
    signals = []
    start = day - timedelta(days=29)
    for comment in payload["comments"]:
        name = (comment.get("author") or {}).get("name", "")
        full_name = (comment.get("author") or {}).get("fullname", "")
        data = comment.get("data") or {}
        revision = data.get("latest") or {}
        text = revision.get("raw") or ""
        stamp = recent(comment.get("createdAt"), start, day)
        cid = comment.get("id", "")
        if (
            comment.get("type") != "comment"
            or data.get("hidden")
            or not stamp
            or (revision.get("updatedAt") and not recent(revision["updatedAt"], start, day))
            or not name
            or name in authors
            or full_name.casefold() in full_names
            or name.lower().endswith("bot")
            or not re.fullmatch(r"[a-f0-9]{24}", cid)
            or len(text.strip()) < 60
        ):
            continue
        signals.append(
            dict(
                source="Hugging Face Papers",
                date=stamp,
                author=name,
                url=url + "#" + cid,
                text=text.strip()[:600],
            )
        )
        if len(signals) >= 3:
            break
    return signals
