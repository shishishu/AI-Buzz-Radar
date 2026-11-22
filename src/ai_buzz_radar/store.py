import fcntl
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ai_buzz_radar.models import (
    Brief,
    FeedItem,
    RequestTrace,
    Story,
    TopEdition,
    launch_key,
    select_top,
)
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
                CREATE TABLE IF NOT EXISTS research_requests (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    requested_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feed_runs (
                    day TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES research_requests(request_id)
                );
                CREATE TABLE IF NOT EXISTS feed_items (
                    id INTEGER PRIMARY KEY,
                    identity TEXT NOT NULL UNIQUE,
                    published_on TEXT NOT NULL,
                    title_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(published_on, title_key)
                );
                CREATE INDEX IF NOT EXISTS feed_items_date ON feed_items(published_on DESC, id);
                CREATE TABLE IF NOT EXISTS top_editions (
                    day TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visitors (
                    user_id TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visitor_events (
                    id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES visitors(user_id),
                    kind TEXT NOT NULL CHECK(kind IN (
                        'feed_view', 'item_view', 'source_click', 'feedback'
                    )),
                    item_id INTEGER REFERENCES feed_items(id),
                    occurred_at TEXT NOT NULL,
                    value TEXT,
                    CHECK((kind = 'feed_view') = (item_id IS NULL)),
                    CHECK((kind = 'feedback') = (value IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS visitor_events_user
                    ON visitor_events(user_id, occurred_at DESC);
                """)
            if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                self.migrate_briefs(db)

    @staticmethod
    def migrate_briefs(db: sqlite3.Connection) -> None:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] != 0:
                return
            for (payload,) in db.execute("SELECT payload FROM product_hunt_briefs ORDER BY day"):
                brief = Brief.model_validate_json(payload)
                for story in brief.stories:
                    if launch_key(story.launch_url) is not None:
                        Store.insert_story(db, story)
            db.execute("PRAGMA user_version = 1")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @staticmethod
    def insert_story(db: sqlite3.Connection, story: Story) -> bool:
        cursor = db.execute(
            """INSERT INTO feed_items(identity, published_on, title_key, payload)
               VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                story.identity,
                story.published_on.isoformat(),
                story.title_key,
                story.model_dump_json(),
            ),
        )
        return cursor.rowcount == 1

    def feed(self, start: date = date.min, end: date = date.max, limit: int = 40) -> list[FeedItem]:
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT id, payload FROM feed_items WHERE published_on BETWEEN ? AND ?
                   ORDER BY published_on DESC, id LIMIT ?""",
                (start.isoformat(), end.isoformat(), limit),
            )
            return [
                FeedItem(id=item_id, story=Story.model_validate_json(payload))
                for item_id, payload in rows
            ]

    def feed_item(self, item_id: int) -> Story | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT payload FROM feed_items WHERE id = ?", (item_id,)).fetchone()
        return Story.model_validate_json(row[0]) if row else None

    def top_edition(self, day: date) -> TopEdition | None:
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT payload FROM top_editions WHERE day <= ? ORDER BY day DESC LIMIT 1",
                (day.isoformat(),),
            ).fetchone()
        return TopEdition.model_validate_json(row[0]) if row else None

    def feed_run(self, day: date | None = None) -> RequestTrace | None:
        with closing(self.connect()) as db:
            query = """SELECT research_requests.payload FROM feed_runs
                       JOIN research_requests USING (request_id)"""
            if day is None:
                row = db.execute(query + " ORDER BY day DESC LIMIT 1").fetchone()
            else:
                row = db.execute(query + " WHERE day = ?", (day.isoformat(),)).fetchone()
        return RequestTrace.model_validate_json(row[0]) if row else None

    def record_event(
        self,
        user_id: str,
        kind: str,
        occurred_at: datetime,
        item_id: int | None = None,
        *,
        value: str | None = None,
    ) -> None:
        timestamp = occurred_at.isoformat()
        with closing(self.connect()) as db, db:
            db.execute(
                """INSERT INTO visitors(user_id, first_seen_at, last_seen_at) VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   last_seen_at = max(visitors.last_seen_at, excluded.last_seen_at)""",
                (user_id, timestamp, timestamp),
            )
            db.execute(
                """INSERT INTO visitor_events(user_id, kind, item_id, occurred_at, value)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, kind, item_id, timestamp, value),
            )

    def finish(self, brief: Brief, attempt: Attempt, trace: RequestTrace) -> None:
        with closing(self.connect()) as db, db:
            sources = []
            for story in brief.stories:
                self.insert_story(db, story)
                item_id, saved_date = db.execute(
                    """SELECT id, published_on FROM feed_items
                       WHERE identity = ? OR (published_on = ? AND title_key = ?)
                       ORDER BY (identity = ?) DESC LIMIT 1""",
                    (
                        story.identity,
                        story.published_on.isoformat(),
                        story.title_key,
                        story.identity,
                    ),
                ).fetchone()
                if saved_date != story.published_on.isoformat():
                    brief.duplicate_stories += 1
                    continue
                db.execute(
                    "UPDATE feed_items SET payload = ? WHERE id = ?",
                    (story.model_dump_json(), item_id),
                )
                sources.append(FeedItem(id=item_id, story=story))

            fresh_days = {item.story.published_on for item in sources}
            archived = db.execute(
                """SELECT id, payload FROM feed_items WHERE published_on >= ? AND published_on < ?
                   ORDER BY published_on DESC, id""",
                (brief.window_start.isoformat(), brief.day.isoformat()),
            )
            for item_id, payload in archived:
                story = Story.model_validate_json(payload)
                if story.source_rank is not None and story.published_on not in fresh_days:
                    sources.append(FeedItem(id=item_id, story=story))

            edition = select_top(sources, day=brief.day, window_start=brief.window_start)
            if edition is not None:
                db.execute(
                    """INSERT INTO top_editions(day, payload) VALUES (?, ?)
                       ON CONFLICT(day) DO UPDATE SET payload = excluded.payload""",
                    (brief.day.isoformat(), edition.model_dump_json()),
                )
            brief.stories = [item.story for item in edition.items] if edition else []
            trace.result = brief
            trace.status = "completed"
            attempt.status = "published" if edition else "insufficient_items"
            attempt.published_stories = len(brief.stories)
            self._update_attempt(db, brief.attempt_id, attempt, trace)

    @contextmanager
    def run_lock(self):
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RunInProgress("Another feed run is in progress") from error
            yield

    @staticmethod
    def _insert_request(db: sqlite3.Connection, trace: RequestTrace) -> None:
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

    def save_unbilled_request(self, trace: RequestTrace) -> None:
        with closing(self.connect()) as db, db:
            self._insert_request(db, trace)

    def reserve(
        self, attempt: Attempt, budget_usd: Decimal, trace: RequestTrace, *, feed_run: bool = True
    ) -> int:
        budget_error = None
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
                budget_error = BudgetExceeded(
                    f"Budget ${budget_usd}: ${consumed:.6f} used or reserved, "
                    f"${attempt.reserved_usd:.3f} required for the next request"
                )
                trace.status = "budget_blocked"
                trace.error = str(budget_error)
            else:
                cursor = db.execute(
                    "INSERT INTO attempts(day, payload) VALUES (?, ?)",
                    (attempt.day.isoformat(), attempt.model_dump_json()),
                )
                trace.attempt_id = cursor.lastrowid
            self._insert_request(db, trace)
            if feed_run:
                db.execute(
                    """INSERT INTO feed_runs(day, request_id) VALUES (?, ?)
                       ON CONFLICT(day) DO UPDATE SET request_id = excluded.request_id""",
                    (attempt.day.isoformat(), trace.request_id),
                )
        if budget_error:
            raise budget_error
        assert trace.attempt_id is not None
        return trace.attempt_id

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

    def get_attempt(self, attempt_id: int | None) -> Attempt | None:
        if attempt_id is None:
            return None
        with closing(self.connect()) as db:
            row = db.execute("SELECT payload FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return Attempt.model_validate_json(row[0]) if row else None

    def export_request(self, trace: RequestTrace) -> dict:
        attempt = self.get_attempt(trace.attempt_id)
        report = {
            **trace.model_dump(mode="json"),
            "search_queries": trace.search_queries,
            "opened_pages": trace.opened_pages,
            "attempt": attempt.model_dump(mode="json") if attempt else None,
        }
        if trace.blog_run_id != trace.request_id:
            return report
        with closing(self.connect()) as db:
            rows = db.execute(
                """SELECT r.payload, a.payload FROM research_requests r
                   LEFT JOIN attempts a ON a.id = json_extract(r.payload, '$.attempt_id')
                   WHERE json_extract(r.payload, '$.blog_run_id') = ? ORDER BY r.rowid""",
                (trace.blog_run_id,),
            ).fetchall()
        rounds = [
            {**json.loads(payload), "attempt": json.loads(usage) if usage else None}
            for payload, usage in rows
        ]
        catalog = json.loads(trace.input["input"][0]["content"])["candidates"]
        opened = []
        for turn in rounds:
            for read in turn["blog_reads"]:
                result = json.loads(read["output"])
                if "article" in result:
                    opened.append(catalog[result["article"]]["url"])
        report.update(
            rounds=rounds,
            status=rounds[-1]["status"],
            blog_markdown=rounds[-1].get("blog_markdown"),
            error=rounds[-1].get("error"),
            opened_pages=list(dict.fromkeys(opened)),
        )
        return report

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
