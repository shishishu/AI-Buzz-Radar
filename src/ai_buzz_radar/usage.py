from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openai.types.responses import Response

from ai_buzz_radar.models import Record

MODEL = "gpt-6.2-sol"
REASONING_EFFORT = "high"
MAX_WEB_CALLS = 6
MAX_OUTPUT_TOKENS = 6_500
DEFAULT_BUDGET_USD = Decimal("1")
RATE_DATE = "2026-11-22"
STANDARD_INPUT = Decimal("2")
STANDARD_CACHE_READ = Decimal("0.10")
STANDARD_CACHE_WRITE_30M = Decimal("2.50")
STANDARD_CACHE_WRITE_12H = Decimal("5")
STANDARD_OUTPUT = Decimal("10")
WEB_SEARCH_ACTION = Decimal("0.01")
MILLION = 1_000_000

# The documented web-search context window is 128k. Allow additional input headroom and
# reserve for each requested web action plus one before sending the only API request.
REQUEST_RESERVE_USD = (
    200_000 * STANDARD_CACHE_WRITE_30M + MAX_OUTPUT_TOKENS * STANDARD_OUTPUT
) / MILLION + (MAX_WEB_CALLS + 1) * WEB_SEARCH_ACTION


def parse_budget(value: str) -> Decimal:
    try:
        budget = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Use a positive USD amount for the budget") from error
    if not budget.is_finite() or budget <= 0:
        raise ValueError("Use a positive USD amount for the budget")
    return budget


class Usage(Record):
    input_tokens: int
    uncached_input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cache_write_30m_tokens: int
    cache_write_12h_tokens: int
    output_tokens: int
    reasoning_tokens: int
    web_searches: int
    web_pages_opened: int
    web_find_actions: int
    estimated_cost_usd: Decimal

    @classmethod
    def from_response(cls, response: Response) -> "Usage | None":
        reported = response.usage
        if reported is None:
            return None
        input_details = reported.input_tokens_details
        reads = input_details.cached_tokens
        writes = input_details.cache_write_tokens
        write_details = input_details.cache_write_tokens_details
        extended_writes = write_details.ttl_12h_tokens if write_details else 0
        default_writes = writes - extended_writes
        uncached = reported.input_tokens - reads - writes

        actions = [
            item.action.type
            for item in response.output
            if item.type == "web_search_call" and item.status == "completed"
        ]
        # Include every completed hosted web action in the estimate for budget planning.
        long_context = reported.input_tokens > 272_000
        input_cost = (
            uncached * STANDARD_INPUT
            + reads * STANDARD_CACHE_READ
            + default_writes * STANDARD_CACHE_WRITE_30M
            + extended_writes * STANDARD_CACHE_WRITE_12H
        ) * (2 if long_context else 1)
        output_cost = (
            reported.output_tokens * STANDARD_OUTPUT * (Decimal("1.5") if long_context else 1)
        )
        cost = (input_cost + output_cost) / MILLION + len(actions) * WEB_SEARCH_ACTION

        return cls(
            input_tokens=reported.input_tokens,
            uncached_input_tokens=uncached,
            cache_read_tokens=reads,
            cache_write_tokens=writes,
            cache_write_30m_tokens=default_writes,
            cache_write_12h_tokens=extended_writes,
            output_tokens=reported.output_tokens,
            reasoning_tokens=reported.output_tokens_details.reasoning_tokens,
            web_searches=actions.count("search"),
            web_pages_opened=actions.count("open_page"),
            web_find_actions=actions.count("find_in_page"),
            estimated_cost_usd=cost,
        )


class Attempt(Record):
    day: date
    started_at: datetime
    model: str = MODEL
    reasoning_effort: str = REASONING_EFFORT
    pricing_date: str = RATE_DATE
    reserved_usd: Decimal = REQUEST_RESERVE_USD
    status: str = "pending"
    response_id: str | None = None
    response_status: str | None = None
    usage: Usage | None = None
    duration_seconds: float | None = None
    published_stories: int | None = None
    request_id: str | None = None

    @property
    def consumed_usd(self) -> Decimal:
        if self.usage is not None:
            return self.usage.estimated_cost_usd
        return Decimal("0") if self.status == "rejected" else self.reserved_usd
