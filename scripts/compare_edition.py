"""Replay an archived automatic edition's selection and source material in local Codex CLI."""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ConfigDict, Field

from ai_buzz_radar.agent import TIMEZONE
from ai_buzz_radar.blogs import fetch
from ai_buzz_radar.codex_cli import run_cli as run_structured_cli
from ai_buzz_radar.editions import (
    EDITOR,
    SITES,
    Article,
    Edition,
    EvidenceVerdict,
    FineRanking,
    IllustratedCopy,
    Ranking,
    apply_fine_ranking,
    archive,
    atomic,
    evidence_links,
    exception_note,
    extract,
    publish,
)
from ai_buzz_radar.models import DATABASE_PATH, Record
from ai_buzz_radar.publisher_images import image_candidates, image_catalog, save_original
from ai_buzz_radar.research_sources import ARXIV_HTML
from ai_buzz_radar.store import Store
from ai_buzz_radar.usage import MODEL, REASONING_EFFORT


class Entry(IllustratedCopy):
    url: str


class Interpretations(Record):
    articles: list[Entry] = Field(min_length=3, max_length=3)


class ArchivedVerdict(EvidenceVerdict):
    model_config = ConfigDict(extra="ignore")


def ranking_schema(catalog, saved_schema):
    if catalog.get("stage") != "fine":
        return Ranking
    if any(
        "discussion_index" in item.get("properties", {})
        for item in saved_schema.get("$defs", {}).values()
    ):
        return FineRanking

    # Earlier editorial prompts had several different verdict formats. Send the
    # exact recorded schema; their common validated fields suffice for ordering.
    class ArchivedFineRanking(Record):
        model_config = ConfigDict(extra="ignore")
        decisions: list[ArchivedVerdict] = Field(max_length=12)

        @classmethod
        def model_json_schema(cls, **kwargs):
            return saved_schema

    return ArchivedFineRanking


def run_cli(folder, prompt, schema):
    return run_structured_cli(
        folder, prompt, schema, model=MODEL, effort=REASONING_EFFORT, read_files=True
    )


def select_urls(ranking, catalog, day):
    rows = {r["url"]: r for r in catalog["candidates"]}
    if isinstance(ranking, FineRanking):
        sources = {}
        for url, row in rows.items():
            parts = {s["section"]: (s["heading"], "", s["text"]) for s in row["sections"]}
            sources[url] = (dict(row), parts, {i: p[2] for i, p in parts.items()})
        urls = apply_fine_ranking(day, ranking, sources, {})
    elif catalog.get("stage") == "fine":
        urls = [d.url for d in ranking.decisions if d.eligible]
    else:
        urls = ranking.urls
    ordered = list(dict.fromkeys(url for url in urls if url in rows))
    # Replays use the selection policy of the archived catalog.
    if "recent_editions" not in catalog and catalog.get("stage") != "fine":
        ordered.sort(
            key=lambda url: (
                bool(rows[url]["previous"]),
                (day - date.fromisoformat(rows[url]["published"])).days >= 30,
            )
        )
    if len(ordered) < 3:
        raise ValueError("CLI selection contained fewer than three catalog articles")
    return [rows[url] for url in ordered[:3]]


def source_packet(row, original, store):
    url = row["url"]
    sites = [site for site in (*SITES, ARXIV_HTML) if site.accepts(url)]
    if not sites:
        raise ValueError(f"Unknown source URL {url}")
    data = fetch(url)
    parts = extract(data)
    if original:
        saved = store.get_request(original.request_id)
        if not saved:
            raise ValueError("The API source trace is missing from this database")
        packet = json.loads(saved.input["input"][0]["content"])
        name = original.source
    else:
        name = sites[0].name if len(sites) == 1 else "Anthropic"
        allowance = min(6000, 47000 // max(len(parts), 1))
        packet = {
            "article": row,
            "sections": [
                (i, heading, passage[:allowance]) for i, (heading, _, passage) in enumerate(parts)
            ],
        }
    images = image_candidates(data, url)
    packet["images"] = image_catalog(images)
    return packet, parts, name, images


def compare(folder, day, store, traces):
    editions = archive(folder)
    baseline = next((e for e in editions if e.day == day), None)
    if not baseline or not baseline.ranking_request_id:
        raise ValueError("Choose an archived day that used automatic API selection")
    trace = store.get_request(baseline.ranking_request_id)
    if not trace:
        raise ValueError("The original ranking request is missing from this database")
    rank_dir, write_dir = traces / "rank", traces / "writing"
    rank_dir.mkdir(parents=True)
    write_dir.mkdir()
    catalog_text = trace.input["input"][0]["content"]
    (rank_dir / "catalog.json").write_text(catalog_text)
    catalog = json.loads(catalog_text)
    ranking, ranking_id = run_cli(
        rank_dir,
        trace.input["instructions"]
        + " Read only catalog.json. Do not use the network or other files.",
        ranking_schema(catalog, trace.input.get("text", {}).get("format", {}).get("schema", {})),
    )
    rows = select_urls(ranking, catalog, day)
    originals = {a.url: a for a in baseline.articles}
    sources = {}
    for i, row in enumerate(rows, 1):
        url = row["url"]
        packet, parts, name, images = source_packet(row, originals.get(url), store)
        (write_dir / f"article-{i}.json").write_text(json.dumps(packet, ensure_ascii=False))
        sources[url] = parts, name, packet, images
    result, writing_id = run_cli(
        write_dir,
        "Use only article-1.json through article-3.json in file order. Read the "
        "numbered source excerpts and return the URL and draft for each. No network.\n" + EDITOR,
        Interpretations,
    )
    if [entry.url for entry in result.articles] != [row["url"] for row in rows]:
        raise ValueError("CLI writing did not preserve the independently selected URLs")
    articles = []
    output = folder / "codex-cli"
    history = {a.url: e.day for e in editions if e.day < day for a in e.articles}
    for row, entry in zip(rows, result.articles, strict=True):
        parts, name, packet, images = sources[entry.url]
        excerpts = {i: text for i, _, text in packet["sections"]}
        if any(b.evidence not in excerpts.get(b.section, "") for b in entry.draft.blocks):
            raise ValueError("Evidence missing from the CLI source packet")
        a = Article(
            title=row["title"],
            url=entry.url,
            published=row["published"],
            source=name,
            request_id=writing_id,
            note="",
            draft=entry.draft,
            localization=entry.localization,
            original_image=save_original(entry.image, images, output, fetch),
            links=evidence_links(entry.draft, entry.url, parts),
        )
        a.note = exception_note(day, a, history)
        a.note_en = exception_note(day, a, history, lang="en")
        articles.append(a)
    edition = Edition(
        day=day, ranking_request_id=ranking_id, articles=articles, updated_at=datetime.now(TIMEZONE)
    )
    with store.run_lock():
        atomic(output / "editions" / f"{day}.json", edition.model_dump_json(indent=2))
        publish(output, archive(output))
        publish(folder, archive(folder))
    return output / f"agent-reading-{day}.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=Path("examples"))
    parser.add_argument("--db", type=Path, default=Path(DATABASE_PATH))
    args = parser.parse_args()
    path = args.db.parent / "cli-comparisons" / str(uuid4())
    print(compare(args.output, args.day, Store(args.db), path))
