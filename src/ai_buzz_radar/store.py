import fcntl
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ai_buzz_radar.models import Brief
from ai_buzz_radar.usage import Attempt


class RunInProgress(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS product_hunt_briefs (
                    day TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY,
                    day TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get(self, day: date | None = None) -> Brief | None:
        with closing(self.connect()) as db:
            if day is None:
                row = db.execute(
                    "SELECT payload FROM product_hunt_briefs ORDER BY day DESC LIMIT 1"
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT payload FROM product_hunt_briefs WHERE day = ?", (day.isoformat(),)
                ).fetchone()
        return Brief.model_validate_json(row[0]) if row else None

    def days(self, limit: int = 30) -> list[str]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT day FROM product_hunt_briefs ORDER BY day DESC LIMIT ?", (limit,)
            )
            return [row[0] for row in rows]

    def history(self, day: date, days: int) -> list[Brief]:
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT payload FROM product_hunt_briefs
                   WHERE day >= ? AND day < ? ORDER BY day DESC""",
                ((day - timedelta(days=days)).isoformat(), day.isoformat()),
            )
            return [Brief.model_validate_json(row[0]) for row in rows]

    def publish(self, brief: Brief, attempt: Attempt) -> None:
        attempt.status = "published"
        attempt.published_stories = len(brief.stories)
        with closing(self.connect()) as db, db:
            db.execute(
                """INSERT INTO product_hunt_briefs(day, payload) VALUES (?, ?)
                   ON CONFLICT(day) DO UPDATE SET payload = excluded.payload""",
                (brief.day.isoformat(), brief.model_dump_json()),
            )
            db.execute(
                "UPDATE attempts SET payload = ? WHERE id = ?",
                (attempt.model_dump_json(), brief.attempt_id),
            )

    @contextmanager
    def run_lock(self):
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RunInProgress("Another research run is in progress") from error
            yield

    def reserve(self, attempt: Attempt, budget_usd: Decimal) -> int:
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            consumed = sum(
                (
                    Attempt.model_validate_json(row[0]).consumed_usd
                    for row in db.execute("SELECT payload FROM attempts")
                ),
                Decimal("0"),
            )
            if consumed + attempt.reserved_usd > budget_usd:
                raise BudgetExceeded(
                    f"Budget ${budget_usd}: ${consumed:.6f} used or reserved, "
                    f"${attempt.reserved_usd:.3f} required for the next request"
                )
            cursor = db.execute(
                "INSERT INTO attempts(day, payload) VALUES (?, ?)",
                (attempt.day.isoformat(), attempt.model_dump_json()),
            )
            return cursor.lastrowid

    def update_attempt(self, attempt_id: int, attempt: Attempt) -> None:
        with closing(self.connect()) as db, db:
            db.execute(
                "UPDATE attempts SET payload = ? WHERE id = ?",
                (attempt.model_dump_json(), attempt_id),
            )

    def attempts(self, day: date | None = None) -> list[tuple[int, Attempt]]:
        with closing(self.connect()) as db:
            if day is None:
                rows = db.execute("SELECT id, payload FROM attempts ORDER BY id")
            else:
                rows = db.execute(
                    "SELECT id, payload FROM attempts WHERE day = ? ORDER BY id",
                    (day.isoformat(),),
                )
            return [(row[0], Attempt.model_validate_json(row[1])) for row in rows]
