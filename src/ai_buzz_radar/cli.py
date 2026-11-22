import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from time import sleep

from dotenv import load_dotenv
from openai import APIError, OpenAI

from ai_buzz_radar.agent import TIMEZONE, describe_error, open_client, run_research
from ai_buzz_radar.models import DATABASE_PATH, Brief, LeaderboardSnapshot, Selection, start_date
from ai_buzz_radar.store import Store
from ai_buzz_radar.usage import (
    COMPACT_LIMITS,
    DEFAULT_BUDGET_USD,
    DEFAULT_LIMITS,
    RequestLimits,
    parse_budget,
)

logger = logging.getLogger(__name__)


def run_once(
    client: OpenAI,
    store: Store,
    *,
    day: date,
    days: int,
    budget_usd: Decimal,
    force: bool = False,
    limits: RequestLimits = DEFAULT_LIMITS,
    snapshot: LeaderboardSnapshot | None = None,
) -> Brief:
    with store.run_lock():
        existing = store.feed_run(day)
        if existing is not None and not force:
            if existing.result is None:
                raise RuntimeError(
                    f"Feed run {existing.request_id} for {day} is {existing.status}. "
                    "Use --force to retry explicitly."
                )
            logger.info("Using the recorded update for %s", day)
            return existing.result
        return run_research(
            client,
            store,
            selection=Selection(window_start=start_date(day, days), window_end=day),
            budget_usd=budget_usd,
            limits=limits,
            snapshot=snapshot,
        )


def due_day(store: Store, now: datetime, hour: int) -> date | None:
    today = now.date()
    return today if now.hour >= hour and store.feed_run(today) is None else None


def daily_worker(
    client: OpenAI,
    store: Store,
    *,
    hour: int,
    days: int,
    budget_usd: Decimal,
    limits: RequestLimits,
) -> None:
    logger.info("Daily feed update at %02d:00 %s", hour, TIMEZONE)
    while True:
        day = due_day(store, datetime.now(TIMEZONE), hour)
        if day is not None:
            try:
                report = run_once(
                    client, store, day=day, days=days, budget_usd=budget_usd, limits=limits
                )
                logger.info("Added %s feed items for %s", len(report.stories), report.day)
            except (APIError, RuntimeError, ValueError) as error:
                logger.error("Daily update for %s: %s", day, describe_error(error))
        sleep(60)


def usage_report(store: Store, day: date | None) -> str:
    attempts = store.attempts(day)
    consumed = sum((attempt.consumed_usd for _, attempt in attempts), Decimal("0"))
    estimated = sum(
        (attempt.usage.estimated_cost_usd for _, attempt in attempts if attempt.usage),
        Decimal("0"),
    )
    return json.dumps(
        {
            "estimated_cost_usd": str(estimated),
            "reserved_for_unknown_usage_usd": str(consumed - estimated),
            "attempts": [
                {"id": attempt_id, **attempt.model_dump(mode="json")}
                for attempt_id, attempt in attempts
            ],
        },
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env.local")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="radar", description="AI Buzz Radar · Product Hunt")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("RADAR_DB", DATABASE_PATH)))
    commands = parser.add_subparsers(dest="command", required=True)
    generation = argparse.ArgumentParser(add_help=False)
    generation.add_argument("--days", type=int, default=3, help="Calendar days, including today")
    generation.add_argument(
        "--compact", action="store_true", help="Allow two web actions and 1,600 output tokens"
    )
    generation.add_argument(
        "--budget-usd",
        type=parse_budget,
        default=os.getenv("RADAR_BUDGET_USD", str(DEFAULT_BUDGET_USD)),
        help="Cumulative estimated spend allowed for this database (default: $1)",
    )
    run = commands.add_parser("run", parents=[generation], help="Refresh the feed once")
    run.add_argument("--day", type=date.fromisoformat)
    run.add_argument("--snapshot", type=Path, help="Use a verified Product Hunt leaderboard JSON")
    run.add_argument(
        "--force", action="store_true", help="Run an additional update for the same date"
    )
    daily = commands.add_parser("daily", parents=[generation], help="Refresh the feed daily")
    daily.add_argument("--hour", type=int, default=21, help="Hour in Asia/Shanghai (default: 21)")
    show = commands.add_parser("show", help="Print saved feed items as JSON")
    show.add_argument("--day", type=date.fromisoformat)
    usage = commands.add_parser("usage", help="Print request usage and budget accounting as JSON")
    usage.add_argument("--day", type=date.fromisoformat)
    trace = commands.add_parser("request", help="Print a saved request and its tool trace as JSON")
    trace.add_argument("request_id")
    serve = commands.add_parser("serve", help="Start the local site")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "serve":
        from ai_buzz_radar.web import create_app

        create_app(args.db).run(host="127.0.0.1", port=args.port)
        return 0

    store = Store(args.db)
    if args.command == "request":
        saved = store.get_request(args.request_id)
        if saved is None:
            parser.exit(1, "No saved request with that ID\n")
        print(json.dumps(store.export_request(saved), ensure_ascii=False, indent=2))
        return 0
    if args.command == "usage":
        print(usage_report(store, args.day))
        return 0
    if args.command == "show":
        items = store.feed(start=args.day, end=args.day) if args.day else store.feed()
        print(
            json.dumps(
                [item.model_dump(mode="json") for item in items], ensure_ascii=False, indent=2
            )
        )
        return 0

    if not 1 <= args.days <= 4:
        parser.error("--days must be 1–4")
    if args.command == "run":
        today = datetime.now(TIMEZONE).date()
        day = args.day or today
        if day > today or day.year < 2000:
            parser.error("--day must be between 2000-01-01 and today")
        cached = store.feed_run(day)
        if cached and not args.force:
            print(f"{day} · request {cached.request_id} · {cached.status} (cached)")
            return 0 if cached.result is not None else 1
    elif not 0 <= args.hour <= 23:
        parser.error("--hour must be 0–23")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY or provide it through .env.local")

    try:
        limits = COMPACT_LIMITS if args.compact else DEFAULT_LIMITS
        with open_client() as client:
            if args.command == "daily":
                daily_worker(
                    client,
                    store,
                    hour=args.hour,
                    days=args.days,
                    budget_usd=args.budget_usd,
                    limits=limits,
                )
                return 0
            brief = run_once(
                client,
                store,
                day=day,
                days=args.days,
                budget_usd=args.budget_usd,
                force=args.force,
                limits=limits,
                snapshot=LeaderboardSnapshot.model_validate_json(
                    args.snapshot.read_text(encoding="utf-8")
                )
                if args.snapshot
                else None,
            )
        print(f"{brief.day} · {len(brief.stories)} stories · request {brief.request_id}")
    except (APIError, OSError, RuntimeError, ValueError) as error:
        logger.error("%s. See radar usage for request accounting.", describe_error(error))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
