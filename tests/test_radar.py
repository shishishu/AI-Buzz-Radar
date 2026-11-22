import json
import re
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from openai.types.responses import Response, ResponseOutputItem, ResponseUsage
from pydantic import TypeAdapter, ValidationError

from ai_buzz_radar.agent import TIMEZONE
from ai_buzz_radar.cli import due_day, run_once, usage_report
from ai_buzz_radar.models import (
    FeedItem,
    LaunchMedia,
    LeaderboardSnapshot,
    RankedLaunch,
    RankedResearch,
    Research,
    SnapshotEntry,
    Story,
    build_brief,
    launch_key,
    launch_slug,
    leaderboard_url,
    select_top,
)
from ai_buzz_radar.store import BudgetExceeded, RunInProgress, Store
from ai_buzz_radar.usage import COMPACT_LIMITS, REQUEST_RESERVE_USD, Usage
from ai_buzz_radar.web import COOKIE_NAME, browser_id, create_app

DAY = date(2026, 11, 22)
WINDOW_START = date(2026, 11, 20)
LAUNCH = "https://www.producthunt.com/products/example?launch=example-v2"
TOPIC = "https://www.producthunt.com/topics/artificial-intelligence"
LEADERBOARD = "https://www.producthunt.com/leaderboard/daily/2026/11/22"
EXTERNAL = "https://example.com/products/example"
LAUNCH_PATH = "/products/example?launch=example-v2"
STARTED = datetime(2026, 11, 22, 10, tzinfo=TIMEZONE)
BUDGET = Decimal("1")


def story(
    url: str = LAUNCH,
    *,
    published_on: date = DAY,
    title: str = "模型上线",
    rank: int | None = 1,
    use_case="developer_tools",
    **content,
) -> Story:
    return Story(
        title=title,
        published_on=published_on,
        summary="发布了面向开发者的本地 AI 工具。",
        launch_url=url,
        source_rank=rank,
        use_case=use_case,
        ai_relevance="ai_tooling",
        source_note="发布页说明该工具可以在本地连接模型。",
        **content,
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
    ranked = RankedResearch(
        stories=[
            RankedLaunch.model_validate(item.model_dump(include=set(RankedLaunch.model_fields)))
            for item in stories
        ]
    )
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
                        for url in [
                            LAUNCH,
                            TOPIC,
                            LEADERBOARD,
                            EXTERNAL,
                            *(s.launch_url for s in stories),
                            *(leaderboard_url(s.published_on) for s in stories),
                        ]
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
                        "text": ranked.model_dump_json(),
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


def sdk_response(
    client,
    *stories: Story,
    status: str = "completed",
    missing_terminal=False,
    final_response: Response | None = None,
):
    """An offline Responses stream with tool traffic followed by two output deltas."""
    events = [
        SimpleNamespace(type="response.web_search_call.searching"),
        SimpleNamespace(type="response.output_text.delta", delta=""),
        SimpleNamespace(type="response.output_text.delta", delta="{"),
        SimpleNamespace(type="response.output_text.delta", delta="}"),
    ]
    if not missing_terminal:
        events.append(
            SimpleNamespace(
                type=f"response.{status}",
                response=final_response or response(*stories, status=status),
            )
        )
    stream = MagicMock()
    stream.response.headers = {"x-request-id": "req_test"}
    stream.__iter__.return_value = events
    stream.__enter__.return_value = stream
    client.responses.create.return_value = stream


class FeedRunTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "test.sqlite3"
        self.store = Store(self.path)
        self.sdk = Mock()
        self.baseline = [
            story(),
            story("https://www.producthunt.com/products/second", title="第二", rank=2),
            story("https://www.producthunt.com/products/third", title="第三", rank=3),
        ]
        sdk_response(self.sdk, *self.baseline)

    def run_feed(self, *, day=DAY, force=False, budget=BUDGET):
        return run_once(self.sdk, self.store, day=day, days=3, budget_usd=budget, force=force)

    def test_stream_tracks_text_timing_tool_trace_and_daily_idempotency(self):
        with patch("ai_buzz_radar.agent.monotonic", side_effect=[100, 100.2, 100.4, 100.5]):
            report = self.run_feed()
        self.assertEqual(report.stories, self.baseline)
        self.assertEqual(self.run_feed(), report)
        self.sdk.responses.create.assert_called_once()
        request = self.sdk.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "gpt-6.2-sol")
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertEqual(request["tools"][0]["filters"], {"allowed_domains": ["producthunt.com"]})
        self.assertTrue(request["stream"])
        self.assertFalse(request["store"])
        self.assertEqual(request["max_tool_calls"], 4)
        trace = self.store.feed_run(DAY)
        self.assertEqual(trace.result, report)
        self.assertEqual(trace.input, request)
        self.assertEqual(trace.http_request_id, "req_test")
        self.assertEqual(trace.response["id"], "resp_1")
        self.assertEqual(trace.opened_pages, [LAUNCH])
        self.assertEqual(len(trace.search_queries), 2)
        attempt = self.store.get_attempt(report.attempt_id)
        self.assertEqual(attempt.duration_seconds, 0.5)
        self.assertEqual(attempt.ttft_ms, 200)
        self.assertEqual(attempt.tpot_ms, round(200 / 399, 3))
        self.assertEqual(attempt.usage.estimated_cost_usd, Decimal("0.0599"))

    def test_backfill_is_sorted_by_launch_date_and_alternate_urls_are_deduplicated(self):
        sdk_response(self.sdk, story())
        self.run_feed()
        today = DAY + timedelta(days=1)
        newer = story(
            "https://www.producthunt.com/posts/latest", published_on=today, title="当天发布"
        )
        backfill = story(
            "https://www.producthunt.com/posts/missed",
            published_on=DAY - timedelta(days=1),
            title="回补发布",
        )
        alternate = story("https://www.producthunt.com/products/example")
        sdk_response(self.sdk, alternate, backfill, newer)
        report = self.run_feed(day=today)
        self.assertEqual(
            [item.story.title for item in self.store.feed()],
            [
                "当天发布",
                "模型上线",
                "回补发布",
            ],
        )
        self.assertEqual(len(report.stories), 3)

    def test_rolling_product_page_can_document_a_distinct_later_launch(self):
        base = "https://www.producthunt.com/products/rolling-product"
        first = story(base, title="首发")
        later = story(base, title="第二次发布", published_on=DAY + timedelta(days=1))
        sdk_response(self.sdk, first)
        self.run_feed()
        sdk_response(self.sdk, later)
        self.run_feed(day=later.published_on)
        self.assertEqual([item.story for item in self.store.feed()], [later, first])

    def test_incomplete_response_preserves_feed_and_usage(self):
        self.run_feed()
        sdk_response(self.sdk, status="incomplete")
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.run_feed(force=True)
        self.assertEqual([item.story for item in self.store.feed()], self.baseline)
        usage = json.loads(usage_report(self.store, DAY))
        self.assertEqual(Decimal(usage["estimated_cost_usd"]), Decimal("0.1198"))
        self.assertEqual(usage["attempts"][-1]["response_status"], "incomplete")
        self.assertIsNotNone(usage["attempts"][-1]["ttft_ms"])

    def test_stream_without_terminal_event_keeps_the_reservation(self):
        sdk_response(self.sdk, missing_terminal=True)
        with self.assertRaisesRegex(RuntimeError, "without a terminal response"):
            self.run_feed()
        trace = self.store.feed_run(DAY)
        self.assertEqual(trace.status, "usage_unavailable")
        self.assertEqual(trace.http_request_id, "req_test")
        attempt = self.store.get_attempt(trace.attempt_id)
        self.assertEqual(attempt.consumed_usd, REQUEST_RESERVE_USD)
        self.assertIsNotNone(attempt.ttft_ms)
        self.assertIsNone(attempt.tpot_ms)

    def test_compact_retry_rechecks_unverified_candidates_and_requires_daily_rank_source(self):
        original = response(story())
        original.output[0].action.sources = []
        original.output[1].status = "failed"
        sdk_response(self.sdk, final_response=original)
        with self.assertRaisesRegex(ValueError, "daily rank and launch-page"):
            self.run_feed()
        self.assertEqual(self.store.feed(), [])
        verified = response(story())
        sdk_response(self.sdk, final_response=verified)
        result = run_once(
            self.sdk,
            self.store,
            day=DAY,
            days=3,
            budget_usd=BUDGET,
            force=True,
            limits=COMPACT_LIMITS,
        )
        payload = self.sdk.responses.create.call_args.kwargs
        self.assertEqual(payload["max_tool_calls"], 2)
        self.assertEqual(payload["max_output_tokens"], 1600)
        self.assertEqual(
            json.loads(payload["input"][1]["content"])["unverified_retry_urls"], [LAUNCH]
        )
        self.assertEqual(result.stories, [])
        self.assertEqual([item.story for item in self.store.feed()], [story()])

    def test_snapshot_uses_supplied_original_ranks_and_keeps_last_edition_if_short(self):
        snapshot = LeaderboardSnapshot(
            day=DAY,
            source_url=LEADERBOARD,
            entries=[
                SnapshotEntry(
                    title=item.title,
                    source_rank=item.source_rank,
                    launch_url=item.launch_url,
                    evidence=item.summary,
                )
                for item in self.baseline
            ],
        )
        good = response(*self.baseline)
        good.output = good.output[2:]
        sdk_response(self.sdk, final_response=good)
        edition = run_once(
            self.sdk, self.store, day=DAY, days=3, budget_usd=BUDGET, snapshot=snapshot
        )
        self.assertEqual(edition.stories, self.baseline)
        payload = self.sdk.responses.create.call_args.kwargs
        self.assertNotIn("tools", payload)
        self.assertEqual(self.store.top_edition(DAY).day, DAY)

        altered = self.baseline[0].model_copy(update={"source_rank": 19})
        bad = response(altered)
        bad.output = bad.output[2:]
        sdk_response(self.sdk, final_response=bad)
        with self.assertRaisesRegex(ValueError, "daily rank and launch-page"):
            run_once(
                self.sdk,
                self.store,
                day=DAY,
                days=3,
                budget_usd=BUDGET,
                force=True,
                snapshot=snapshot,
            )
        self.assertEqual(len(self.store.top_edition(DAY).items), 3)

    def test_today_top_stops_at_three_by_original_rank_even_with_different_use_cases(self):
        items = [
            FeedItem(
                id=rank,
                story=story(
                    f"https://www.producthunt.com/products/p-{rank}",
                    title=f"发布{rank}",
                    rank=rank,
                ),
            )
            for rank in (1, 2, 5, 6, 7, 8, 9)
        ]
        result = select_top(items[::-1], day=DAY, window_start=WINDOW_START)
        self.assertEqual([item.story.source_rank for item in result.items], [1, 2, 5])
        for item, category in zip(
            items[4:],
            ("productivity", "sales_marketing", "content_creation"),
            strict=True,
        ):
            item.story.use_case = category
        result = select_top(items, day=DAY, window_start=WINDOW_START)
        self.assertEqual([item.story.source_rank for item in result.items], [1, 2, 5])

    def test_ranked_edition_skips_weak_matches_and_keeps_nonconsecutive_ranks(self):
        candidates = [
            story(f"https://www.producthunt.com/posts/p-{rank}", title=f"发布{rank}", rank=rank)
            for rank in (1, 2, 4, 6, 7)
        ]
        result = response(*candidates)
        message = result.output[-1].content[0]
        data = json.loads(message.text)
        data["stories"][0]["ai_relevance"] = "unrelated"
        message.text = json.dumps(data)
        sdk_response(self.sdk, final_response=result)
        report = self.run_feed()
        self.assertEqual([item.source_rank for item in report.stories], [2, 4, 6])
        self.assertEqual(report.rejected_stories, 1)
        self.assertEqual(
            [item.story.source_rank for item in self.store.top_edition(DAY).items], [2, 4, 6]
        )

    def test_new_window_with_under_three_ranked_items_keeps_previous_edition(self):
        self.run_feed()
        old = self.store.top_edition(DAY)
        today = DAY + timedelta(days=4)
        sdk_response(self.sdk, story("https://www.producthunt.com/posts/new", published_on=today))
        result = self.run_feed(day=today)
        self.assertEqual(result.stories, [])
        self.assertEqual(self.store.top_edition(today), old)
        self.assertEqual(self.store.get_attempt(result.attempt_id).status, "insufficient_items")

    def test_daily_worker_only_runs_when_due_and_keeps_budget_blocked_records(self):
        self.assertIsNone(due_day(self.store, STARTED, 21))
        evening = STARTED.replace(hour=21)
        self.assertEqual(due_day(self.store, evening, 21), DAY)
        with self.assertRaises(BudgetExceeded):
            self.run_feed(budget=Decimal("0.48"))
        self.assertEqual(self.store.feed_run(DAY).status, "budget_blocked")
        self.assertEqual(self.store.attempts(), [])
        self.assertIsNone(due_day(self.store, evening, 21))
        self.sdk.responses.create.assert_not_called()

    def test_run_lock_excludes_another_writer(self):
        other = Store(self.path)
        with self.store.run_lock(), self.assertRaises(RunInProgress), other.run_lock():
            self.fail("An existing run must hold the writer lock")

    def test_cost_breakdown_and_no_double_counting(self):
        usage = Usage.from_response(response())
        self.assertEqual(usage.uncached_input_tokens, 1000)
        self.assertEqual(usage.cache_read_tokens, 4000)
        self.assertEqual(usage.cache_write_tokens, 7000)
        self.assertEqual(usage.estimated_cost_usd, Decimal("0.0599"))


class FeedWebTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "legacy.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE product_hunt_briefs(day TEXT PRIMARY KEY, payload TEXT)")
            db.execute(
                "INSERT INTO product_hunt_briefs VALUES (?, ?)",
                (
                    DAY.isoformat(),
                    brief(story(title="<script>unsafe()</script>", rank=None)).model_dump_json(),
                ),
            )
        self.app = create_app(self.path)
        self.store = Store(self.path)

    def test_home_migrates_existing_briefs_and_removes_old_web_routes(self):
        browser = self.app.test_client()
        html = browser.get("/").get_data(as_text=True)
        self.assertEqual(len(self.store.feed()), 1)
        self.assertIn("今日 Top", html)
        self.assertIn("首期 Top 待更新", html)
        self.assertNotIn("unsafe()", html)
        sdk = Mock()
        sdk_response(
            sdk,
            story(title="<script>unsafe()</script>"),
            story("https://www.producthunt.com/products/second", title="第二", rank=2),
            story(
                "https://www.producthunt.com/products/third",
                title="第三",
                rank=3,
                published_on=DAY - timedelta(days=1),
            ),
        )
        run_once(sdk, self.store, day=DAY, days=3, budget_usd=BUDGET)
        html = browser.get("/").get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("回补 · 11 月 21 日", html)
        self.assertIn("日榜第 3 名", html)
        self.assertEqual(browser.get("/healthz").json, {"status": "ok"})
        self.assertEqual(browser.get("/research").status_code, 404)
        self.assertEqual(browser.get(f"/briefs/{DAY}").status_code, 404)

    def test_source_note_and_verified_snapshot_media_render_with_safe_embed(self):
        image = "https://ph-files.imgix.net/e3de00d0-b549-4e7e-b8f9-34222a09983e.jpeg"
        video = "https://www.youtube.com/watch?v=abcdefg1234"
        launches = [
            story(LAUNCH, title="发布图", rank=1),
            story("https://www.producthunt.com/posts/with-video", title="演示", rank=2),
            story("https://www.producthunt.com/posts/text-only", title="摘要", rank=3),
        ]
        snapshot = LeaderboardSnapshot(
            day=DAY,
            source_url=LEADERBOARD,
            entries=[
                SnapshotEntry(
                    title=item.title,
                    source_rank=item.source_rank,
                    launch_url=item.launch_url,
                    evidence=item.source_note,
                    facts=[
                        {"label": "平台", "value": "Mac"},
                        {"label": "AI 接入", "value": "MCP"},
                    ]
                    if index == 0
                    else [],
                    media={"url": [image, video][index], "caption": item.title}
                    if index < 2
                    else None,
                )
                for index, item in enumerate(launches)
            ],
        )
        sdk = Mock()
        sdk_response(sdk, *launches)
        run_once(sdk, self.store, day=DAY, days=3, budget_usd=BUDGET, snapshot=snapshot)
        page = self.app.test_client().get("/")
        html = page.get_data(as_text=True)
        self.assertEqual(html.count("发布页要点"), 3)
        self.assertIn(f'<img src="{image}"', html)
        self.assertIn('<th scope="row">AI 接入</th><td>MCP</td>', html)
        self.assertRegex(
            html,
            r'<template>\s*<iframe src="https://www.youtube-nocookie.com/embed/abcdefg1234"',
        )
        self.assertIn(
            "frame-src https://www.youtube-nocookie.com", page.headers["Content-Security-Policy"]
        )
        with self.assertRaises(ValidationError):
            LaunchMedia(url="https://ph-files.imgix.net.attacker.example/other.png", caption="图")

    def test_cookie_attributes_site_views_and_original_clicks_are_correlated(self):
        browser = self.app.test_client()
        page = browser.get("/")
        self.assertIn("HttpOnly", page.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", page.headers["Set-Cookie"])
        token = browser.get_cookie(COOKIE_NAME).value
        csrf = re.search(r'data-view-token="([^"]+)"', page.get_data(as_text=True))[1]
        item = self.store.feed()[0]
        url = f"/events/view/{item.id}"
        self.assertEqual(self.app.test_client().post(url, data={"csrf": csrf}).status_code, 403)
        self.assertEqual(browser.post(url, data={"csrf": csrf}).status_code, 204)
        self.assertEqual(browser.get(f"/out/{item.id}").location, LAUNCH)
        browser.get(f"/out/{item.id}", headers={"Sec-Purpose": "prefetch"})
        browser.get("/")
        second = self.app.test_client()
        second.get("/")
        self.assertNotEqual(second.get_cookie(COOKIE_NAME).value, token)
        self.store.record_event(browser_id(token), "feedback", STARTED, item.id, value="hide")
        with sqlite3.connect(self.path) as db:
            events = db.execute(
                "SELECT kind, item_id, value FROM visitor_events WHERE user_id = ? ORDER BY id",
                (browser_id(token),),
            ).fetchall()
            self.assertEqual(
                events,
                [
                    ("feed_view", None, None),
                    ("item_view", item.id, None),
                    ("source_click", item.id, None),
                    ("feed_view", None, None),
                    ("feedback", item.id, "hide"),
                ],
            )
            self.assertEqual(db.execute("SELECT count(*) FROM visitors").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
