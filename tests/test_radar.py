import json
import re
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from openai.types.responses import Response, ResponseOutputItem, ResponseUsage
from pydantic import TypeAdapter

from ai_buzz_radar.agent import TIMEZONE
from ai_buzz_radar.cli import run_once, usage_report
from ai_buzz_radar.models import Research, Story, build_brief, launch_key, launch_slug
from ai_buzz_radar.store import BudgetExceeded, RunInProgress, Store
from ai_buzz_radar.usage import REQUEST_RESERVE_USD, Attempt, Usage
from ai_buzz_radar.web import create_app

DAY = date(2026, 11, 22)
WINDOW_START = date(2026, 11, 20)
LAUNCH = "https://www.producthunt.com/products/example?launch=example-v2"
TOPIC = "https://www.producthunt.com/topics/artificial-intelligence"
LEADERBOARD = "https://www.producthunt.com/leaderboard/daily/2026/11/22"
EXTERNAL = "https://example.com/products/example"
LAUNCH_PATH = "/products/example?launch=example-v2"
STARTED = datetime(2026, 11, 22, 10, tzinfo=TIMEZONE)
BUDGET = Decimal("1")


def story(url: str = LAUNCH, *, published_on: date = DAY, title: str = "模型上线") -> Story:
    return Story(
        title=title,
        published_on=published_on,
        summary="发布了面向开发者的本地 AI 工具。",
        why_it_matters="开发者可以在本地运行。",
        caveat=None,
        launch_url=url,
    )


def brief(*stories: Story, previously_published: set[str] | None = None):
    return build_brief(
        Research(stories=list(stories)),
        day=DAY,
        window_start=WINDOW_START,
        generated_at=STARTED,
        observed={LAUNCH_PATH, "/posts/example-v2"},
        previously_published=previously_published or set(),
        attempt_id=1,
    )


def response(*stories: Story, status: str = "completed") -> Response:
    output = TypeAdapter(list[ResponseOutputItem]).validate_python(
        [
            {
                "id": "ws_1",
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "queries": [
                        "site:producthunt.com AI developer tools",
                        "site:producthunt.com AI MCP",
                    ],
                    "sources": [
                        {"type": "url", "url": url}
                        for url in [LAUNCH, TOPIC, LEADERBOARD, EXTERNAL]
                    ],
                },
            },
            {
                "id": "ws_2",
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "open_page", "url": LAUNCH},
            },
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": Research(stories=list(stories)).model_dump_json(),
                        "annotations": [],
                    }
                ],
            },
        ]
    )
    usage = ResponseUsage.model_validate(
        {
            "input_tokens": 12000,
            "input_tokens_details": {
                "cached_tokens": 4000,
                "cache_write_tokens": 7000,
                "cache_write_tokens_details": {"ttl_30m_tokens": 3000, "ttl_12h_tokens": 4000},
            },
            "output_tokens": 1000,
            "output_tokens_details": {"reasoning_tokens": 600},
            "total_tokens": 13000,
        }
    )
    return Response.model_construct(id="resp_1", status=status, output=output, usage=usage)


class EvidenceTests(unittest.TestCase):
    def test_valid_launch_urls_normalize_tracking_and_preserve_versions(self):
        self.assertEqual(launch_key(LAUNCH + "&utm_medium=test#discussion"), LAUNCH_PATH)
        self.assertEqual(
            launch_key("https://producthunt.com/posts/example-v2"), "/posts/example-v2"
        )
        self.assertEqual(launch_slug("/products/example/launches/example-v2"), "example-v2")
        self.assertNotEqual(launch_key(LAUNCH.replace("v2", "v3")), launch_key(LAUNCH))

    def test_only_specific_product_hunt_launch_pages(self):
        for url in (
            TOPIC,
            LEADERBOARD,
            EXTERNAL,
            "javascript:alert(1)",
            "https://www.producthunt.com",
            "https://www.producthunt.com/products/example/reviews",
            "https://producthunt.com@evil.test/products/example",
            "https://www.producthunt.com.evil.test/products/example",
            LAUNCH + "&launch=another",
        ):
            with self.subTest(url=url):
                self.assertIsNone(launch_key(url))

    def test_unobserved_and_stale_stories_are_removed(self):
        result = brief(
            story("https://www.producthunt.com/products/invented"),
            story(EXTERNAL),
            story(LEADERBOARD),
            story(published_on=date(2026, 11, 19)),
            story(LAUNCH + "&utm_source=radar"),
        )
        self.assertEqual([entry.launch_url for entry in result.stories], [LAUNCH])
        self.assertEqual(result.rejected_stories, 4)
        with self.assertRaisesRegex(ValueError, "failed date or evidence"):
            brief(story(LEADERBOARD))

    def test_launch_aliases_and_previously_published_launches_are_deduplicated(self):
        result = brief(story(), story("https://www.producthunt.com/posts/example-v2"))
        self.assertEqual(len(result.stories), 1)
        self.assertEqual(result.duplicate_stories, 1)
        self.assertEqual(brief(story(), previously_published={"example-v2"}).stories, [])

    def test_reads_saved_model_text_without_duplicate_inline_citations(self):
        fields = story().model_dump(mode="json")
        fields["summary"] = f"能调用 run()。 ([producthunt.com]({LAUNCH}))"
        fields["why_it_matters"] = f"方便评估。 [producthunt.com]({LAUNCH})"
        saved = Story.model_validate_json(json.dumps(fields))
        self.assertEqual(saved.summary, "能调用 run()。")
        self.assertEqual(saved.why_it_matters, "方便评估。")
        self.assertEqual(saved.launch_url, LAUNCH)


class RequestTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "test.sqlite3"
        self.store = Store(self.path)
        self.client = Mock()
        self.client.responses.create.return_value = response(story())

    def run_once(self, *, force=False, budget=BUDGET):
        return run_once(self.client, self.store, day=DAY, days=3, budget_usd=budget, force=force)

    def test_one_response_uses_explicit_model_and_domain_and_publishes(self):
        result = self.run_once()
        self.assertEqual(result.stories, [story()])
        self.assertEqual(self.store.get(), result)
        trace = self.store.get_request(result.request_id)
        self.assertIsNone(trace.user_id)
        self.client.responses.create.assert_called_once()
        payload = self.client.responses.create.call_args.kwargs
        self.assertEqual(payload["model"], "gpt-6.2-sol")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertEqual(payload["tools"][0]["filters"], {"allowed_domains": ["producthunt.com"]})
        self.assertEqual(payload["input"][0]["role"], "developer")
        self.assertEqual(payload["max_tool_calls"], 6)
        self.assertEqual(payload["max_output_tokens"], 6500)
        self.assertFalse(payload["store"])
        self.assertEqual(self.run_once(), result)
        self.client.responses.create.assert_called_once()

    def test_cost_breakdown_and_no_double_counting(self):
        usage = Usage.from_response(response())
        self.assertEqual(usage.input_tokens, 12000)
        self.assertEqual(usage.uncached_input_tokens, 1000)
        self.assertEqual(usage.cache_read_tokens, 4000)
        self.assertEqual(usage.cache_write_tokens, 7000)
        self.assertEqual(usage.output_tokens, 1000)
        self.assertEqual(usage.reasoning_tokens, 600)
        self.assertEqual(usage.estimated_cost_usd, Decimal("0.0599"))

    def test_incomplete_response_keeps_accounting_and_last_published_brief(self):
        first = self.run_once()
        self.client.responses.create.return_value = response(status="incomplete")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_once(force=True)
        self.assertEqual(self.store.get(), first)
        report = json.loads(usage_report(self.store, DAY))
        self.assertEqual(Decimal(report["estimated_cost_usd"]), Decimal("0.1198"))
        self.assertEqual(report["attempts"][-1]["status"], "brief_failed")
        self.assertEqual(report["attempts"][-1]["response_status"], "incomplete")

    def test_research_with_no_valid_evidence_is_charged_and_not_published(self):
        self.client.responses.create.return_value = response(story(LEADERBOARD))
        with self.assertRaisesRegex(ValueError, "failed date or evidence"):
            self.run_once()
        self.assertIsNone(self.store.get())
        ((_, attempt),) = self.store.attempts()
        self.assertEqual(attempt.status, "brief_failed")
        self.assertEqual(attempt.usage.estimated_cost_usd, Decimal("0.0599"))

    def test_budget_denies_request_when_pending_attempt_already_reserved(self):
        self.store.reserve(Attempt(day=DAY, started_at=STARTED), BUDGET)
        with self.assertRaises(BudgetExceeded):
            self.run_once()
        self.client.responses.create.assert_not_called()
        report = json.loads(usage_report(self.store, None))
        self.assertEqual(Decimal(report["reserved_for_unknown_usage_usd"]), REQUEST_RESERVE_USD)

    def test_run_lock_excludes_another_writer(self):
        other_process = Store(self.path)
        with self.store.run_lock(), self.assertRaises(RunInProgress), other_process.run_lock():
            self.fail("An existing run must hold the writer lock")
        with other_process.run_lock():
            self.assertIsNone(other_process.get(DAY))

    def test_site_serves_saved_brief_and_escapes_headline(self):
        web = create_app(self.path).test_client()
        self.assertIn("首期简报尚未生成", web.get("/").get_data(as_text=True))
        self.client.responses.create.return_value = response(story(title="<script>x()</script>"))
        self.run_once()
        page = web.get("/")
        html = page.get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn(LAUNCH, html)
        self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
        self.assertEqual(web.get("/healthz").json, {"status": "ok"})
        self.assertEqual(web.get(f"/briefs/{DAY}").status_code, 200)
        self.assertEqual(web.get("/briefs/incorrect").status_code, 404)
        self.assertEqual(web.post("/").status_code, 405)


class PersonalResearchTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "test.sqlite3"
        self.store = Store(self.path)
        self.web = create_app(self.path)
        self.web.config["RADAR_REQUESTS_ENABLED"] = True
        self.sdk = Mock()
        self.sdk.responses.create.return_value = response(story())
        opener = self.enterContext(patch("ai_buzz_radar.web.open_client"))
        opener.return_value.__enter__.return_value = self.sdk
        self.owner = self.web.test_client()

    def form(self, window_start="2026-11-20", topic="MCP"):
        page = self.owner.get("/research")
        html = page.get_data(as_text=True)
        return {
            **dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)"', html)),
            "window_start": window_start,
            "window_end": DAY.isoformat(),
            "topic": topic,
        }

    def test_same_day_topics_get_independent_records_and_keep_the_public_brief(self):
        public = run_once(self.sdk, self.store, day=DAY, days=3, budget_usd=BUDGET)
        first = self.form()
        result = self.owner.post("/research", data=first)
        self.assertEqual(result.status_code, 303)
        duplicate = self.owner.post("/research", data=first)
        self.assertEqual(duplicate.location, result.location)
        second = self.form(window_start="2026-11-21", topic="AI video")
        self.assertNotEqual(second["request_id"], first["request_id"])
        self.assertEqual(self.owner.post("/research", data=second).status_code, 303)
        self.assertEqual(self.sdk.responses.create.call_count, 3)
        self.assertEqual(self.store.get(), public)

        trace = self.owner.get(result.location + "/trace").json
        self.assertEqual(trace["request_id"], first["request_id"])
        self.assertEqual(trace["input"], self.sdk.responses.create.call_args_list[1].kwargs)
        self.assertEqual(trace["selection"]["topic"], "MCP")
        self.assertEqual(
            trace["search_queries"],
            [
                "site:producthunt.com AI developer tools",
                "site:producthunt.com AI MCP",
            ],
        )
        self.assertEqual(trace["opened_pages"], [LAUNCH])
        self.assertEqual(trace["response"]["id"], "resp_1")
        self.assertIsNone(trace["http_request_id"])
        self.assertEqual(trace["result"]["stories"][0]["launch_url"], LAUNCH)
        self.assertEqual(
            Decimal(trace["attempt"]["usage"]["estimated_cost_usd"]), Decimal("0.0599")
        )
        personal_two = self.store.get_request(second["request_id"])
        self.assertEqual(personal_two.user_id, trace["user_id"])
        self.assertEqual(personal_two.selection.window_start, date(2026, 11, 21))
        self.assertEqual(personal_two.selection.topic, "AI video")

    def test_different_browser_cannot_load_another_browsers_history_or_trace(self):
        fields = self.form()
        created = self.owner.post("/research", data=fields)
        guest = self.web.test_client()
        history = guest.get("/research")
        self.assertIn("HttpOnly", history.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", history.headers["Set-Cookie"])
        self.assertNotIn(fields["request_id"], history.get_data(as_text=True))
        self.assertEqual(guest.get(created.location).status_code, 404)
        self.assertEqual(guest.get(created.location + "/trace").status_code, 404)
        self.assertEqual(guest.post("/research", data=fields).status_code, 403)
        self.sdk.responses.create.assert_called_once()
        self.assertEqual(
            self.owner.get(created.location).headers["Cache-Control"], "private, no-store"
        )

    def test_invalid_range_and_budget_denial_do_not_send_an_api_request(self):
        invalid = self.owner.post("/research", data=self.form(window_start="2026-11-23"))
        self.assertEqual(invalid.status_code, 400)
        self.store.reserve(Attempt(day=DAY, started_at=STARTED), BUDGET)
        fields = self.form()
        blocked = self.owner.post("/research", data=fields)
        self.assertEqual(blocked.status_code, 303)
        trace = self.owner.get(blocked.location + "/trace").json
        self.assertEqual(trace["status"], "budget_blocked")
        self.assertIsNone(trace["attempt"])
        self.assertIsNone(trace["response"])
        self.sdk.responses.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
