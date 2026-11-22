import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from openai.types.responses import ResponseFunctionToolCall
from test_radar import response, sdk_response

from ai_buzz_radar.blog_agent import ReadingList, run_blog, validate_picks
from ai_buzz_radar.blogs import SOURCES, Reader, discover
from ai_buzz_radar.store import BudgetExceeded, Store

DAY = date(2026, 11, 22)
ARTICLE = "https://www.anthropic.com/research/memory"
HTML = b"""<article><h2>Controlled experiment</h2><p>Search alone met half the criteria.</p>
<h3>Limits</h3><p>Single-file tasks showed little benefit.</p></article>"""
RSS = b"""<rss><channel><item><title>Older harness paper</title>
<link>https://lilianweng.github.io/posts/harness/</link>
<pubDate>Sat, 04 Jul 2026 00:00:00 +0000</pubDate></item></channel></rss>"""


def card(slug, day):
    return (
        f'<article><time>{day}</time><h3><a href="/research/{slug}">{slug}</a></h3>'
        "<p>A comparison of retrieval methods.</p></article>"
    ).encode()


def corpus():
    sources = {
        s.index: RSS if s.rss else card("memory", "Nov 6, 2026") + card("future", "Nov 23, 2026")
        for s in SOURCES
    }
    items, warnings = discover(DAY, 30, sources.__getitem__)
    return Reader(items, {ARTICLE: HTML}.__getitem__), warnings


def pick():
    return dict(
        article=0,
        section=0,
        topic="上下文与记忆",
        reason="比较检索方案",
        overview="简单搜索满足一半评分项。",
        evidence_quote="half the criteria",
        deep_read=[
            {"minutes": 20, "task": "读 Controlled experiment"},
            {"minutes": 40, "task": "复核对照实验"},
        ],
    )


class BlogTests(unittest.TestCase):
    def setUp(self):
        self.reader, self.warnings = corpus()
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.store = Store(Path(temp) / "test.sqlite3")

    def test_sources_filter_dates_merge_urls_and_handle_partial_outage(self):
        self.assertEqual([a.url for a in self.reader.candidates], [ARTICLE])
        self.assertEqual(self.warnings, [])

        def loader(url):
            if url == SOURCES[0].index:
                raise OSError("source offline")
            return RSS if url.endswith("xml") else card("memory", "2026-11-06")

        rows, warnings = discover(DAY, 30, loader)
        self.assertEqual(len(rows), 1)
        self.assertIn("offline", warnings[0])

    def test_long_section_tail_remains_readable(self):
        body = "<article><h2>Results</h2><p>" + "Evidence. " * 600 + "Tail marker.</p></article>"
        reader = Reader(self.reader.candidates, lambda _: body.encode())
        outline = reader.read('{"article":0,"section":-1}')
        last = outline["sections"][-1]["section"]
        self.assertGreater(last, 0)
        page = reader.read(json.dumps({"article": 0, "section": last}))
        self.assertIn("Tail marker.", page["text"])
        self.assertLessEqual(len(page["text"]), 4000)

    def test_empty_catalog_records_zero_cost_and_no_calls(self):
        client = Mock()
        run_id, markdown = run_blog(client, self.store, Reader([]), DAY, 30, Decimal("1"), [])
        client.responses.create.assert_not_called()
        report = self.store.export_request(self.store.get_request(run_id))
        self.assertEqual(report["blog_markdown"], markdown)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(self.store.attempts(), [])

    def test_tool_evidence_and_reading_time_required(self):
        result = ReadingList(picks=[pick()])
        self.reader.read('{"article":0,"section":-1}')
        with self.assertRaisesRegex(ValueError, "evidence"):
            validate_picks(result, self.reader)
        self.reader.read('{"article":0,"section":0}')
        validate_picks(result, self.reader)
        self.assertIn("error", self.reader.read('{"article":-1,"section":0}'))
        result.picks[0].deep_read[0].minutes = 2
        with self.assertRaisesRegex(ValueError, "time"):
            validate_picks(result, self.reader)

    def test_tool_loop_uses_shared_budget_and_preserves_feed_state(self):
        first = response()
        first.output = [
            ResponseFunctionToolCall(
                type="function_call",
                call_id="read1",
                name="read_article",
                arguments='{"article":0,"section":0}',
            )
        ]
        final = response()
        final.output = final.output[-1:]
        final.output[0].content[0].text = json.dumps({"picks": [pick()]})
        client = Mock()
        streams = []
        for item in (first, final):
            sdk_response(client, final_response=item)
            streams.append(client.responses.create.return_value)
        client.responses.create.side_effect = streams
        run_id, markdown = run_blog(client, self.store, self.reader, DAY, 30, Decimal("1"), [])
        self.assertIn("half the criteria", markdown)
        trace = self.store.export_request(self.store.get_request(run_id))
        self.assertEqual(len(trace["rounds"]), 2)
        self.assertEqual(trace["opened_pages"], [ARTICLE])
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["rounds"][1]["input"]["input"][-1]["call_id"], "read1")
        self.assertEqual(trace["rounds"][1]["blog_markdown"], markdown)
        self.assertIsNone(self.store.feed_run(DAY))
        with self.assertRaises(BudgetExceeded):
            run_blog(client, self.store, self.reader, DAY, 30, Decimal(".01"), [])
        self.assertEqual(client.responses.create.call_count, 2)
