import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI
from pydantic import ValidationError

from ai_buzz_radar.agent import TIMEZONE, run_research
from ai_buzz_radar.models import DATABASE_PATH, Brief
from ai_buzz_radar.store import Store
from ai_buzz_radar.usage import DEFAULT_BUDGET_USD

logger = logging.getLogger(__name__)


def run_once(
    client: OpenAI, store: Store, *, day: date, days: int, budget_usd: Decimal, force: bool = False
) -> Brief:
    with store.run_lock():
        existing = store.get(day)
        if existing is not None and not force:
            logger.info("Using the saved brief for %s", day)
            return existing
        brief, attempt = run_research(client, store, day=day, days=days, budget_usd=budget_usd)
        store.publish(brief, attempt)
        return brief


def describe_error(error: Exception) -> str:
    if isinstance(error, APIError):
        status = getattr(error, "status_code", None)
        detail = f" ({status}, {error.code})" if status else ""
        return f"OpenAI API {type(error).__name__}{detail}"
    if isinstance(error, ValidationError):
        return f"Structured brief validation failed ({error.error_count()} errors)"
    return str(error)


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


def parse_budget(value: str) -> Decimal:
    try:
        budget = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("Use a positive USD amount") from error
    if not budget.is_finite() or budget <= 0:
        raise argparse.ArgumentTypeError("Use a positive USD amount")
    return budget


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env.local")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="radar", description="AI Buzz Radar · Product Hunt")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("RADAR_DB", DATABASE_PATH)))
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Research and save a brief")
    run.add_argument("--day", type=date.fromisoformat)
    run.add_argument("--days", type=int, default=3, help="Product Hunt calendar days to search")
    run.add_argument(
        "--force", action="store_true", help="Replace an existing brief if research succeeds"
    )
    run.add_argument(
        "--budget-usd",
        type=parse_budget,
        default=DEFAULT_BUDGET_USD,
        help="Cumulative estimated spend allowed for this database (default: $1)",
    )
    show = commands.add_parser("show", help="Print a saved brief as JSON")
    show.add_argument("--day", type=date.fromisoformat)
    usage = commands.add_parser("usage", help="Print request usage and budget accounting as JSON")
    usage.add_argument("--day", type=date.fromisoformat)
    serve = commands.add_parser("serve", help="Start the local read-only site")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.command == "serve":
        from ai_buzz_radar.web import create_app

        create_app(args.db).run(host="127.0.0.1", port=args.port)
        return 0

    store = Store(args.db)
    if args.command == "usage":
        print(usage_report(store, args.day))
        return 0
    if args.command == "show":
        brief = store.get(args.day)
        if brief is None:
            parser.exit(1, "No saved brief for that date\n")
        print(brief.model_dump_json(indent=2))
        return 0

    if not 1 <= args.days <= 7:
        parser.error("--days must be 1–7")
    today = datetime.now(TIMEZONE).date()
    day = args.day or today
    if day > today or day.year < 2000:
        parser.error("--day must be between 2000-01-01 and today")

    cached = store.get(day)
    if cached is not None and not args.force:
        print(f"{cached.day} · {len(cached.stories)} stories · cached")
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY or provide it through .env.local")

    try:
        with OpenAI(base_url="https://api.openai.com/v1", timeout=240, max_retries=0) as client:
            brief = run_once(
                client, store, day=day, days=args.days, budget_usd=args.budget_usd, force=args.force
            )
        print(f"{brief.day} · {len(brief.stories)} stories · attempt {brief.attempt_id}")
    except (APIError, RuntimeError, ValueError) as error:
        logger.error("%s. See radar usage for request accounting.", describe_error(error))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
