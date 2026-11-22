import re
from datetime import date, datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRODUCT_HUNT = "producthunt.com"
DATABASE_PATH = "data/product-hunt.sqlite3"
MAX_SOURCE_RANK = 20
UseCase = Literal[
    "sales_marketing",
    "content_creation",
    "knowledge_research",
    "developer_tools",
    "customer_support",
    "productivity",
    "infrastructure",
    "other",
]
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
LAUNCH_PATH = re.compile(rf"/(?:(?:posts|products)/{SLUG}|products/{SLUG}/launches/{SLUG})")
PRODUCT_HUNT_LINK = r"\[(?:www\.)?producthunt\.com\]\(https?://[^\s)]+\)"
INLINE_CITATION = re.compile(rf"[（(]{PRODUCT_HUNT_LINK}[）)]|{PRODUCT_HUNT_LINK}", re.IGNORECASE)


def launch_key(url: str) -> str | None:
    """Identify an on-site launch page, preserving any explicit launch selector."""
    if any(character.isspace() or ord(character) < 32 for character in url) or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc.lower() not in {PRODUCT_HUNT, f"www.{PRODUCT_HUNT}"}:
        return None
    path = parts.path.removesuffix("/").lower()
    if not LAUNCH_PATH.fullmatch(path):
        return None
    launch = parse_qs(parts.query, keep_blank_values=True).get("launch", [])
    if launch:
        if len(launch) != 1 or not re.fullmatch(SLUG, launch[0]):
            return None
        if path.startswith("/products/") and path.count("/") == 2:
            return f"{path}?launch={launch[0]}"
        if launch[0] != path.rsplit("/", 1)[-1]:
            return None
    return path


def launch_slug(key: str) -> str:
    path, _, selector = key.partition("?launch=")
    return selector or path.rsplit("/", 1)[-1]


def leaderboard_url(day: date) -> str:
    return f"https://www.{PRODUCT_HUNT}/leaderboard/daily/{day.year}/{day.month}/{day.day}"


def observed_leaderboard(url: str, day: date) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.netloc in {PRODUCT_HUNT, f"www.{PRODUCT_HUNT}"}
        and parts.path.rstrip("/")
        in {
            urlsplit(leaderboard_url(day)).path,
            f"/leaderboard/daily/{day:%Y/%m/%d}",
        }
    )


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Story(Record):
    title: str
    published_on: date
    summary: str
    why_it_matters: str | None = None
    caveat: str | None = None
    launch_url: str
    source_rank: int | None = Field(default=None, ge=1, le=MAX_SOURCE_RANK)
    use_case: UseCase | None = None

    @field_validator("title", "summary", "why_it_matters", "caveat")
    @classmethod
    def clean_inline_citations(cls, value: str | None) -> str | None:
        return INLINE_CITATION.sub("", value).strip() if value is not None else None

    @property
    def identity(self) -> str:
        key = launch_key(self.launch_url)
        if key is None:
            raise ValueError("A feed item requires a Product Hunt launch URL")
        if key.startswith("/products/") and key.count("/") == 2 and "?" not in key:
            return f"{launch_slug(key)}@{self.published_on}"
        return launch_slug(key)

    @property
    def title_key(self) -> str:
        return re.sub(r"[^\w]+", "", self.title.casefold()) or self.title.casefold()


class FeedItem(Record):
    id: int
    story: Story


class TopEdition(Record):
    day: date
    items: list[FeedItem] = Field(min_length=3, max_length=5)


def select_top(items: list[FeedItem], *, day: date, window_start: date) -> TopEdition | None:
    candidates = sorted(
        (
            item
            for item in items
            if item.story.source_rank is not None and window_start <= item.story.published_on <= day
        ),
        key=lambda item: (-item.story.published_on.toordinal(), item.story.source_rank),
    )
    unique = []
    seen_items = set()
    seen_ranks = set()
    seen_launches = set()
    for item in candidates:
        rank_on_day = (item.story.published_on, item.story.source_rank)
        key = launch_key(item.story.launch_url)
        if (
            key is None
            or key in seen_launches
            or item.id in seen_items
            or rank_on_day in seen_ranks
        ):
            continue
        seen_launches.add(key)
        seen_items.add(item.id)
        seen_ranks.add(rank_on_day)
        unique.append(item)

    today = [item for item in unique if item.story.published_on == day]
    selected = today[:3]
    use_cases = {item.story.use_case for item in selected}
    for item in today[3:]:
        use_case = item.story.use_case
        if use_case and use_case != "other" and use_case not in use_cases:
            selected.append(item)
            use_cases.add(use_case)
        if len(selected) == 5:
            break
    if len(selected) < 3:
        backfill = [item for item in unique if item.story.published_on < day]
        selected.extend(backfill[: 3 - len(selected)])
    return TopEdition(day=day, items=selected) if len(selected) >= 3 else None


class RankedLaunch(Record):
    title: str
    published_on: date
    launch_url: str
    source_rank: int
    use_case: UseCase
    summary: str


class RankedResearch(Record):
    stories: list[RankedLaunch]


class SnapshotEntry(Record):
    title: str = Field(min_length=1, max_length=120)
    source_rank: int = Field(ge=1, le=MAX_SOURCE_RANK)
    launch_url: str
    evidence: str = Field(min_length=1, max_length=400)


class LeaderboardSnapshot(Record):
    day: date
    source_url: str
    entries: list[SnapshotEntry] = Field(min_length=1, max_length=MAX_SOURCE_RANK)

    @model_validator(mode="after")
    def validate_source(self) -> "LeaderboardSnapshot":
        if not observed_leaderboard(self.source_url, self.day):
            raise ValueError("Snapshot requires the official Product Hunt daily leaderboard URL")
        keys = {launch_key(entry.launch_url) for entry in self.entries}
        ranks = {entry.source_rank for entry in self.entries}
        if None in keys or len(keys) != len(self.entries) or len(ranks) != len(self.entries):
            raise ValueError("Snapshot must contain distinct Product Hunt launch URLs and ranks")
        return self


class Research(Record):
    stories: list[Story]


class Selection(Record):
    window_start: date
    window_end: date
    topic: str = Field(default="", max_length=240)

    @field_validator("topic", mode="before")
    @classmethod
    def strip_topic(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def check_window(self) -> "Selection":
        if self.window_start > self.window_end:
            raise ValueError("Start date must be on or before the end date")
        return self


class Brief(Record):
    day: date
    window_start: date
    generated_at: datetime
    stories: list[Story]
    attempt_id: int
    launch_pages_observed: int
    rejected_stories: int
    duplicate_stories: int
    request_id: str | None = None


class RequestTrace(Record):
    request_id: str
    user_id: str | None
    requested_at: datetime
    selection: Selection
    input: dict[str, Any]
    status: str = "pending"
    attempt_id: int | None = None
    http_request_id: str | None = None
    response: dict[str, Any] | None = None
    result: Brief | None = None
    error: str | None = None

    @property
    def web_actions(self) -> list[dict[str, Any]]:
        output = self.response.get("output", []) if self.response else []
        return [item for item in output if item.get("type") == "web_search_call"]

    @property
    def search_queries(self) -> list[str]:
        queries = []
        for item in self.web_actions:
            action = item["action"]
            if action["type"] == "search":
                queries.extend(
                    action.get("queries") or ([action["query"]] if action.get("query") else [])
                )
        return queries

    @property
    def opened_pages(self) -> list[str]:
        return [
            item["action"]["url"]
            for item in self.web_actions
            if item["status"] == "completed"
            and item["action"]["type"] == "open_page"
            and item["action"].get("url")
        ]


def build_brief(
    research: Research,
    *,
    day: date,
    window_start: date,
    generated_at: datetime,
    observed: set[str],
    previously_published: set[str],
    attempt_id: int,
    require_launch_pages: bool = True,
    max_stories: int = 5,
) -> Brief:
    if not observed and (require_launch_pages or research.stories):
        raise ValueError("Search returned no verifiable Product Hunt launch pages")

    stories = []
    rejected = duplicates = 0
    seen = set(previously_published)
    for story in research.stories:
        key = launch_key(story.launch_url)
        fields = (story.title, story.summary)
        if (
            key is None
            or key not in observed
            or not window_start <= story.published_on <= day
            or not all(field.strip() for field in fields)
        ):
            rejected += 1
            continue
        identity = story.identity
        if identity in seen:
            duplicates += 1
            continue
        stories.append(story.model_copy(update={"launch_url": f"https://www.{PRODUCT_HUNT}{key}"}))
        seen.add(identity)
        if len(stories) == max_stories:
            break

    if research.stories and not stories and not duplicates:
        raise ValueError("All proposed stories failed date or evidence validation")

    return Brief(
        day=day,
        window_start=window_start,
        generated_at=generated_at,
        stories=stories,
        attempt_id=attempt_id,
        launch_pages_observed=len(observed),
        rejected_stories=rejected,
        duplicate_stories=duplicates,
    )


def start_date(day: date, days: int) -> date:
    return day - timedelta(days=days - 1)
