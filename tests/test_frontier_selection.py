import json
import unittest
from datetime import date, timedelta
from html import escape
from unittest.mock import patch

from ai_buzz_radar.blogs import Candidate
from ai_buzz_radar.editions import FineRanking, frontier_pool, rank
from ai_buzz_radar.selection_signals import hf_discussions, hn_discussions
from scripts.compare_edition import ranking_schema, select_urls

DAY = date(2026, 11, 25)
COMMENT = "How did the matched trials control the cost across repeated tasks and different tools?"


class FrontierSelectionTest(unittest.TestCase):
    def test_old_portfolio_replay_uses_recorded_schema_and_original_order(self):
        urls = [f"https://example.org/{i}" for i in range(4)]
        catalog = {"stage": "fine", "candidates": [{"url": url} for url in urls]}
        stored = {"properties": {"portfolio_reason": {}, "decisions": {}}}
        schema = ranking_schema(catalog, stored)
        self.assertEqual(schema.model_json_schema(), stored)
        result = schema.model_validate(
            {
                "portfolio_reason": "Legacy preference",
                "decisions": [
                    dict(
                        url=url,
                        eligible=True,
                        reason="reason",
                        section=0,
                        evidence="text",
                        reader_value="context",
                        genre="研究论文",
                    )
                    for url in reversed(urls)
                ],
            }
        )
        self.assertEqual([r["url"] for r in select_urls(result, catalog, DAY)], urls[::-1][:3])

    def test_only_recent_dated_discussions_of_exact_work_open_the_exception_window(self):
        rows = [
            Candidate(
                f"Work {age}",
                f"https://metr.org/blog/w{age}/",
                DAY - timedelta(days=age),
                "METR",
                "",
            )
            for age in (0, 29, 30, 60, 89, 90)
        ]
        by_age = {(DAY - r.published).days: r for r in rows}

        def read(url):
            if "/search?" in url:
                return json.dumps(
                    {
                        "hits": [
                            {"objectID": str(i), "url": r.url.rstrip("/")}
                            for i, r in by_age.items()
                        ]
                    }
                ).encode()
            i = int(url.rsplit("/", 1)[1])
            return json.dumps(
                {
                    "url": by_age[i].url,
                    "author": "submitter",
                    "children": [
                        {
                            "id": 1,
                            "author": "submitter",
                            "text": COMMENT,
                            "created_at": "2026-11-22T00:00:00Z",
                        },
                        {
                            "id": 2,
                            "author": "researcher",
                            "text": COMMENT,
                            "created_at": "2026-10-01T00:00:00Z"
                            if i == 60
                            else "2026-11-24T00:00:00Z",
                        },
                        {
                            "id": 3,
                            "author": "reader",
                            "text": COMMENT,
                            "created_at": "2026-11-26T00:00:00Z",
                        },
                    ],
                }
            ).encode()

        audit = {}
        pool = frontier_pool(DAY, rows, read, audit, editorial_picks=False)
        self.assertEqual(set(pool), {by_age[n].url for n in (0, 29, 30, 89)})
        self.assertEqual(audit["primary_count"], 2)
        self.assertEqual(audit["older_index_count"], 3)
        self.assertEqual(audit["discussion_warnings"], [])
        self.assertEqual(len(audit["discussion_queries"]), 4)
        for row in audit["classic_candidates"]:
            self.assertEqual(len(row["triggers"]), 1)
            self.assertEqual(row["triggers"][0]["date"], "2026-11-24")
        no_match = hn_discussions(
            DAY,
            rows,
            lambda u: json.dumps(
                {"hits": [{"objectID": "100", "url": rows[0].url}]}
                if "/search?" in u
                else {"url": rows[1].url, "children": []}
            ).encode(),
        )[0]
        self.assertFalse(no_match)

    def test_hf_discussion_rejects_author_promotion_bots_and_later_edits(self):
        comments = []
        for i, name in enumerate(("author", "reader", "dailybot", "late")):
            comments.append(
                dict(
                    id=f"{i:024x}",
                    type="comment",
                    author={"name": name},
                    createdAt="2026-11-21T00:00:00Z",
                    data={
                        "latest": {
                            "raw": COMMENT,
                            "updatedAt": "2026-11-26T00:00:00Z"
                            if name == "late"
                            else "2026-11-21T00:00:00Z",
                        }
                    },
                )
            )
        props = json.dumps(
            {
                "paper": {"id": "2610.12345", "authors": [{"user": {"name": "author"}}]},
                "comments": comments,
            }
        )
        page = f'<div data-target="PaperContent" data-props="{escape(props, quote=True)}"></div>'
        signals = hf_discussions(DAY, "2610.12345", lambda _: page.encode())
        self.assertEqual([s["author"] for s in signals], ["reader"])
        self.assertTrue(signals[0]["url"].endswith("#" + "1".zfill(24)))

    def test_verified_five_precede_portfolio_and_weak_classic_cannot_displace_a_new_work(self):
        rows = [
            Candidate(
                str(i),
                f"https://metr.org/blog/{i}/",
                DAY - timedelta(days=50 if i in (1, 2) else 1),
                "METR",
                "",
            )
            for i in range(8)
        ]
        signal = dict(
            source="HN",
            date="2026-11-24",
            url="https://news.ycombinator.com/item?id=2",
            author="reader",
            text=COMMENT,
        )
        record = {
            "coarse": {},
            "fine": {},
            "recall": {"signals": {r.url: [signal] for r in rows[1:3]}},
        }
        decisions = [
            dict(
                url=r.url,
                eligible=True,
                reason="等预算实验",
                genre="研究论文",
                evidence="baseline",
                section=0,
                reader_value="研究确认长任务时哪些设置改善完成率。",
                importance=25,
                evidence_quality=24,
                knowledge_gain=5 if i == 0 else 18 if i == 7 else 15,
                discussion=6 if i == 2 else 0,
                discussion_index=0 if i == 2 else -1,
                classic_reason="近期比较检验了原始基线的核心假设。" if i in (1, 2) else "",
            )
            for i, r in enumerate(rows)
        ]
        model = FineRanking(portfolio_reason="模型原始组合。", decisions=decisions)
        source = b"<article><p>" + b"baseline " * 130 + b"</p></article>"
        with (
            patch("ai_buzz_radar.editions.coarse_rank", return_value=rows),
            patch("ai_buzz_radar.editions.ask", return_value=(model, "fine")),
        ):
            publication_order, _ = rank(None, None, 0, DAY, rows, record, lambda _: source)
        fine = record["fine"]
        self.assertEqual(fine["internal_top_five"], [rows[i].url for i in (2, 7, 3, 4, 5)])
        self.assertEqual(fine["proposed_urls"], [rows[i].url for i in (2, 3, 4)])
        self.assertEqual(fine["reserve_order"], [rows[i].url for i in (7, 5, 6, 0)])
        self.assertEqual(publication_order, fine["proposed_urls"] + fine["reserve_order"])
        self.assertNotIn(rows[1].url, publication_order)
        self.assertNotEqual(fine["model_portfolio_reason"], fine["portfolio_reason"])
        self.assertEqual(fine["internal_shortfall"], 0)
        catalog = dict(
            stage="fine",
            candidates=[
                dict(
                    url=r.url,
                    title=r.title,
                    published=str(r.published),
                    discussion_signals=record["recall"]["signals"].get(r.url, []),
                    sections=[dict(section=0, heading="Introduction", text="baseline")],
                )
                for r in rows
            ],
        )
        self.assertIs(ranking_schema(catalog, FineRanking.model_json_schema()), FineRanking)
        self.assertEqual(
            [r["url"] for r in select_urls(model, catalog, DAY)], fine["proposed_urls"]
        )
