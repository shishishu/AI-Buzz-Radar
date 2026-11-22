import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

PRODUCT_HUNT = "producthunt.com"
DATABASE_PATH = "data/product-hunt.sqlite3"
HISTORY_DAYS = 14
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


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Story(Record):
    title: str
    published_on: date
    summary: str
    why_it_matters: str
    caveat: str | None
    launch_url: str

    @field_validator("title", "summary", "why_it_matters", "caveat")
    @classmethod
    def clean_inline_citations(cls, value: str | None) -> str | None:
        return INLINE_CITATION.sub("", value).strip() if value is not None else None


class Research(Record):
    stories: list[Story]


class Brief(Record):
    day: date
    window_start: date
    generated_at: datetime
    stories: list[Story]
    attempt_id: int
    launch_pages_observed: int
    rejected_stories: int
    duplicate_stories: int


def build_brief(
    research: Research,
    *,
    day: date,
    window_start: date,
    generated_at: datetime,
    observed: set[str],
    previously_published: set[str],
    attempt_id: int,
) -> Brief:
    if not observed:
        raise ValueError("Search returned no verifiable Product Hunt launch pages")

    stories = []
    rejected = duplicates = 0
    seen = set(previously_published)
    for story in research.stories:
        key = launch_key(story.launch_url)
        fields = (story.title, story.summary, story.why_it_matters)
        if (
            key is None
            or key not in observed
            or not window_start <= story.published_on <= day
            or not all(field.strip() for field in fields)
        ):
            rejected += 1
            continue
        slug = launch_slug(key)
        if slug in seen:
            duplicates += 1
            continue
        stories.append(story.model_copy(update={"launch_url": f"https://www.{PRODUCT_HUNT}{key}"}))
        seen.add(slug)
        if len(stories) == 5:
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
