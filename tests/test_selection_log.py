import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ai_buzz_radar.selection_log import save_selection_log, selection_log_path


class SelectionLogTest(unittest.TestCase):
    def test_daily_readable_summary(self):
        items = [
            {"title": f"[实验 {n}]", "url": f"https://arxiv.org/abs/{n}", "source": "arXiv"}
            for n in range(8)
        ]
        results = [
            {**item, "reason": "比较机制与基线", "status": status}
            for item, status in zip(
                items[:-1],
                ["selected"] * 3 + ["reserve", "excluded", "draft_failed", "source_unavailable"],
                strict=True,
            )
        ]
        results[0].update(
            evidence="control group", evidence_url=items[0]["url"] + "#S1", genre="研究论文"
        )
        results[1]["genre"] = "开发指南"
        results[1]["figure"] = {"status": "unavailable", "reason": "作者未提供可核验的原图。"}
        results[2]["genre"] = "实战复盘"
        results[-2]["error"] = "Figure missing"
        record = {
            "schema_version": 1,
            "day": "2026-11-26",
            "status": "selected",
            "mode": "automatic",
            "recall": {
                "start": "2026-10-28",
                "end": "2026-11-26",
                "items": items,
                "count": 8,
                "warnings": ["another feed timed out"],
            },
            "coarse": {
                "rule": "比较摘要",
                "items": [
                    {**item, "status": "shortlisted", "reason": "核对实验"} for item in items[:-1]
                ]
                + [{**items[-1], "status": "excluded", "reason": "仅有基础跑分"}],
            },
            "fine": {
                "rule": "核对原文",
                "items": results,
                "portfolio_reason": "三篇各回答一种开发决策。",
                "proposed_urls": [items[i]["url"] for i in (0, 1, 5)],
            },
            "selected": results[:3],
        }
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp) / "examples"
            log = save_selection_log(public, record)
            report = log.with_suffix(".md")
            summary = report.read_text()
            for expected in (
                "2026-10-28 至 2026-11-26",
                "arXiv（8）",
                "| arXiv 索引 | 8 | — | 7 | 6 | 1 | 3 |",
                "| 一手网站索引 | 0 | — | 0 | 0 | 0 | 0 |",
                "another feed timed out",
                "合并后共 7 篇进入精读",
                "1 篇　仅有基础跑分",
                "候补",
                "未入选",
                "成稿核验失败",
                "取文失败",
                "Figure missing",
                "control group",
                "作者未提供可核验的原图。",
                "三篇各回答一种开发决策",
                "研究论文（1）、开发指南（1）、实战复盘（1）",
                "原提议后未刊发",
                "成稿核验后递补",
                items[0]["url"] + "#S1",
                log.name,
            ):
                self.assertIn(expected, summary)
            self.assertNotIn(items[-1]["url"], summary)
            mtimes = [p.stat().st_mtime_ns for p in (log, report)]
            save_selection_log(public, record)
            self.assertEqual([p.stat().st_mtime_ns for p in (log, report)], mtimes)
            report.write_text("人工补录")
            save_selection_log(public, record)
            self.assertEqual(report.read_text(), "人工补录")
            attempt = save_selection_log(public, {**record, "status": "failed"})
            self.assertFalse(attempt.with_suffix(".md").exists())

    def test_channel_table_keeps_website_candidates_and_editor_picks_visible(self):
        items = [
            {"title": "Paper", "url": "https://arxiv.org/abs/1", "source": "arXiv"},
            {"title": "Report", "url": "https://lab.example/report", "source": "Lab"},
            {"title": "Postmortem", "url": "https://lab.example/incident", "source": "Lab"},
            {"title": "Method", "url": "https://lab.example/method", "source": "Lab"},
            {
                "title": "Second paper",
                "url": "https://arxiv.org/abs/2",
                "source": "arXiv Atom",
                "channel": "arxiv",
            },
        ]
        selected = [{**item, "status": "selected"} for item in items[:3]]
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("automatic", "editor_picks"):
                with self.subTest(mode=mode):
                    reviews = selected.copy()
                    if mode == "automatic":
                        reviews.append({**items[3], "status": "source_unavailable"})
                    record = {
                        "day": "2026-11-26",
                        "schema_version": 1,
                        "mode": mode,
                        "status": "selected",
                        "recall": {"items": items, "count": 5},
                        "coarse": {"mode": mode},
                        "fine": {"items": reviews},
                        "selected": selected,
                    }
                    if mode == "automatic":
                        record["coarse"]["channels"] = {
                            "arxiv": {"nomination_count": 2, "shortlist_count": 1},
                            "first_party_sites": {"nomination_count": 3, "shortlist_count": 3},
                        }
                    path = save_selection_log(Path(tmp) / mode, record)
                    summary = path.with_suffix(".md").read_text()
                    papers = "2" if mode == "automatic" else "—"
                    self.assertIn(f"| arXiv 索引 | 2 | {papers} | 1 | 1 | 0 | 1 |", summary)
                    expected = (
                        "3 | 3 | 3 | 2 | 1 | 2" if mode == "automatic" else "3 | — | 2 | 2 | 0 | 2"
                    )
                    self.assertIn(f"| 一手网站索引 | {expected} |", summary)
                    self.assertEqual("arXiv 索引 1 篇已获渠道提名" in summary, mode == "automatic")

    def test_private_location_and_failed_retries(self):
        day = date(2026, 11, 25)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            public = root / "examples"
            log = selection_log_path(public, day)
            self.assertEqual(log, root / "selection-records" / "2026-11-25.json")
            self.assertFalse(selection_log_path(public / "codex-cli", day).is_relative_to(public))
            self.assertNotEqual(log, selection_log_path(root / "preview", day))
            selected = [{"title": str(n), "url": f"https://example.com/{n}"} for n in range(3)]
            record = dict(
                schema_version=1,
                day=str(day),
                status="selected",
                mode="test",
                recall={},
                coarse={},
                fine={},
                selected=selected,
            )
            self.assertEqual(save_selection_log(public, record), log)
            failed = {**record, "status": "failed", "selected": selected[:1]}
            first = save_selection_log(public, failed)
            second = save_selection_log(public, failed)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text()), failed)
            self.assertEqual(json.loads(log.read_text()), record)
            for picks in (selected[:2], [selected[0]] * 3):
                with self.assertRaises(ValueError):
                    save_selection_log(public, {**record, "selected": picks})
            self.assertEqual(json.loads(log.read_text()), record)
