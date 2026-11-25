"""Run the most recently due Shanghai edition once, including after a missed timer."""

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from ai_buzz_radar.agent import TIMEZONE
from ai_buzz_radar.cli import main as radar
from ai_buzz_radar.selection_log import selection_log_path, selection_summary_ready


def scheduled_day(now):
    return (now.astimezone(TIMEZONE) - timedelta(hours=21)).date()


def matching_record(edition, log, day):
    if not edition.is_file():
        return None
    data = edition.read_bytes()
    try:
        payload = json.loads(data)
        published = [item["url"] for item in payload["articles"]]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Restore damaged edition archive from a verified revision: {edition}"
        ) from exc
    if not log.is_file():
        return None
    try:
        record = json.loads(log.read_bytes())
        selected = [item["url"] for item in record["selected"]]
    except (ValueError, KeyError, TypeError):
        return None
    if (
        record.get("status") == "selected"
        and record.get("day") == payload.get("day") == str(day)
        and all(isinstance(record.get(key), dict) for key in ("recall", "coarse", "fine"))
        and len(set(published)) == len(published) == 3
        and published == selected
        and (
            "edition_sha256" not in record
            or record["edition_sha256"] == hashlib.sha256(data).hexdigest()
        )
    ):
        return record
    return None


def publication_complete(page, log, record):
    homepage = page.with_name("index.html")
    return (
        record is not None
        and selection_summary_ready(log, record)
        and page.with_suffix(".md").is_file()
        and page.with_suffix(".md").stat().st_size > 0
        and page.is_file()
        and homepage.is_file()
        and page.stat().st_size > 0
        and page.read_bytes() == homepage.read_bytes()
    )


def run(output, now):
    day = scheduled_day(now)
    today = now.astimezone(TIMEZONE).date()
    if day < today and (output / "editions" / f"{today}.json").is_file():
        # An editor already published today. Verify that edition on a catch-up trigger.
        day = today
    edition = output / "editions" / f"{day}.json"
    log = selection_log_path(output, day)
    page = output / f"agent-reading-{day}.html"
    record = matching_record(edition, log, day)
    if publication_complete(page, log, record):
        print(f"{day} is published with its selection record")
        return 0

    args = ["edition", "--engine", "codex", "--day", str(day), "--output", str(output)]
    if edition.is_file() and not record:
        # Reconstruct the selection by running it again and archiving the old edition.
        args.append("--reselect")
    result = radar(args)
    if result:
        return result
    if not publication_complete(page, log, matching_record(edition, log, day)):
        raise RuntimeError(
            f"Incomplete local publication or selection report after publishing {day}"
        )
    return 0


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[1]
    os.chdir(project)
    raise SystemExit(run(project / "examples", datetime.now(TIMEZONE)))
