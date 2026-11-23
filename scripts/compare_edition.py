"""Replay an archived automatic edition's selection and source material in local Codex CLI."""

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from ai_buzz_radar.blogs import fetch
from ai_buzz_radar.editions import (
    EDITOR,
    SITES,
    Article,
    Draft,
    Edition,
    Ranking,
    archive,
    atomic,
    evidence_links,
    exception_note,
    extract,
    publish,
)
from ai_buzz_radar.models import DATABASE_PATH, Record
from ai_buzz_radar.store import Store
from ai_buzz_radar.usage import MODEL, REASONING_EFFORT


class Entry(Record):
    url: str
    draft: Draft


class Interpretations(Record):
    articles: list[Entry] = Field(min_length=3, max_length=3)


def run_cli(folder, prompt, schema):
    (folder / "schema.json").write_text(json.dumps(schema.model_json_schema()))
    (folder / "prompt.txt").write_text(prompt)
    events = folder / "events.jsonl"
    with events.open("w") as log, (folder / "stderr.log").open("w") as err:
        subprocess.run(
            [
                "codex",
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "--skip-git-repo-check",
                "-s",
                "read-only",
                "-m",
                MODEL,
                "-c",
                f'model_reasoning_effort="{REASONING_EFFORT}"',
                "--json",
                "--output-schema",
                "schema.json",
                "-o",
                "result.json",
                "-",
            ],
            input=prompt,
            text=True,
            cwd=folder,
            stdout=log,
            stderr=err,
            check=True,
        )
    thread_id = next(
        event["thread_id"]
        for line in events.read_text().splitlines()
        if (event := json.loads(line))["type"] == "thread.started"
    )
    return schema.model_validate_json((folder / "result.json").read_text()), thread_id


def select_urls(ranking, catalog, day):
    rows = {r["url"]: r for r in catalog["candidates"]}
    ordered = list(dict.fromkeys(url for url in ranking.urls if url in rows))
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
    sites = [site for site in SITES if site.accepts(url)]
    if not sites:
        raise ValueError(f"Unknown source URL {url}")
    parts = extract(fetch(url))
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
    return packet, parts, name


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
    ranking, ranking_id = run_cli(
        rank_dir,
        trace.input["instructions"]
        + " Read only catalog.json. Do not use the network or other files.",
        Ranking,
    )
    rows = select_urls(ranking, json.loads(catalog_text), day)
    originals = {a.url: a for a in baseline.articles}
    sources = {}
    for i, row in enumerate(rows, 1):
        url = row["url"]
        packet, parts, name = source_packet(row, originals.get(url), store)
        (write_dir / f"article-{i}.json").write_text(json.dumps(packet, ensure_ascii=False))
        sources[url] = parts, name, packet
    result, writing_id = run_cli(
        write_dir,
        "Use only article-1.json through article-3.json in file order. Read the "
        "numbered source excerpts and return the URL and draft for each. No network.\n" + EDITOR,
        Interpretations,
    )
    if [entry.url for entry in result.articles] != [row["url"] for row in rows]:
        raise ValueError("CLI writing did not preserve the independently selected URLs")
    articles = []
    history = {a.url: e.day for e in editions if e.day < day for a in e.articles}
    for row, entry in zip(rows, result.articles, strict=True):
        parts, name, packet = sources[entry.url]
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
            links=evidence_links(entry.draft, entry.url, parts),
        )
        a.note = exception_note(day, a, history)
        articles.append(a)
    edition = Edition(day=day, ranking_request_id=ranking_id, articles=articles)
    output = folder / "codex-cli"
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
