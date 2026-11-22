import fcntl
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ai_buzz_radar.models import Brief, RequestTrace
from ai_buzz_radar.usage import Attempt


class RunInProgress(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class RequestExists(RuntimeError):
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
                CREATE TABLE IF NOT EXISTS research_requests (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    requested_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS research_requests_user
                    ON research_requests(user_id, requested_at DESC);
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

    def finish(self, brief: Brief, attempt: Attempt, trace: RequestTrace) -> None:
        trace.result = brief
        trace.status = "completed"
        with closing(self.connect()) as db, db:
            if trace.user_id is None:
                attempt.status = "published"
                attempt.published_stories = len(brief.stories)
                db.execute(
                    """INSERT INTO product_hunt_briefs(day, payload) VALUES (?, ?)
                       ON CONFLICT(day) DO UPDATE SET payload = excluded.payload""",
                    (brief.day.isoformat(), brief.model_dump_json()),
                )
            else:
                attempt.status = "completed"
            self._update_attempt(db, brief.attempt_id, attempt, trace)

    @contextmanager
    def run_lock(self):
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RunInProgress("Another research run is in progress") from error
            yield

    def reserve(
        self, attempt: Attempt, budget_usd: Decimal, trace: RequestTrace | None = None
    ) -> int:
        budget_error = None
        attempt_id = None
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if (
                trace
                and db.execute(
                    "SELECT 1 FROM research_requests WHERE request_id = ?", (trace.request_id,)
                ).fetchone()
            ):
                raise RequestExists(trace.request_id)
            consumed = sum(
                (
                    Attempt.model_validate_json(row[0]).consumed_usd
                    for row in db.execute("SELECT payload FROM attempts")
                ),
                Decimal("0"),
            )
            if consumed + attempt.reserved_usd > budget_usd:
                budget_error = BudgetExceeded(
                    f"Budget ${budget_usd}: ${consumed:.6f} used or reserved, "
                    f"${attempt.reserved_usd:.3f} required for the next request"
                )
            else:
                cursor = db.execute(
                    "INSERT INTO attempts(day, payload) VALUES (?, ?)",
                    (attempt.day.isoformat(), attempt.model_dump_json()),
                )
                attempt_id = cursor.lastrowid
            if trace:
                trace.attempt_id = attempt_id
                if budget_error:
                    trace.status = "budget_blocked"
                    trace.error = str(budget_error)
                db.execute(
                    """INSERT INTO research_requests(request_id, user_id, requested_at, payload)
                       VALUES (?, ?, ?, ?)""",
                    (
                        trace.request_id,
                        trace.user_id,
                        trace.requested_at.isoformat(),
                        trace.model_dump_json(),
                    ),
                )
        if budget_error:
            raise budget_error
        assert attempt_id is not None
        return attempt_id

    def update_attempt(self, attempt_id: int, attempt: Attempt, trace: RequestTrace) -> None:
        with closing(self.connect()) as db, db:
            self._update_attempt(db, attempt_id, attempt, trace)

    @staticmethod
    def _update_attempt(
        db: sqlite3.Connection, attempt_id: int, attempt: Attempt, trace: RequestTrace
    ) -> None:
        db.execute(
            "UPDATE attempts SET payload = ? WHERE id = ?",
            (attempt.model_dump_json(), attempt_id),
        )
        db.execute(
            "UPDATE research_requests SET payload = ? WHERE request_id = ?",
            (trace.model_dump_json(), trace.request_id),
        )

    def get_request(self, request_id: str) -> RequestTrace | None:
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT payload FROM research_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        return RequestTrace.model_validate_json(row[0]) if row else None

    def request_history(self, user_id: str, limit: int = 30) -> list[RequestTrace]:
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT payload FROM research_requests WHERE user_id = ?
                   ORDER BY requested_at DESC LIMIT ?""",
                (user_id, limit),
            )
            return [RequestTrace.model_validate_json(row[0]) for row in rows]

    def get_attempt(self, attempt_id: int | None) -> Attempt | None:
        if attempt_id is None:
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT payload FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return Attempt.model_validate_json(row[0]) if row else None

    def export_request(self, trace: RequestTrace) -> dict:
        attempt = self.get_attempt(trace.attempt_id)
        return {
            **trace.model_dump(mode="json"),
            "search_queries": trace.search_queries,
            "opened_pages": trace.opened_pages,
            "attempt": attempt.model_dump(mode="json") if attempt else None,
        }

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
