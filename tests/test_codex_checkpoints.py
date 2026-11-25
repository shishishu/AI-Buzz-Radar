import json
import os
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from ai_buzz_radar.blogs import Candidate
from ai_buzz_radar.codex_cli import CodexCLI, run_cli
from ai_buzz_radar.editions import CoarseRanking, FineRanking, IllustratedCopy, generate
from ai_buzz_radar.selection_log import selection_log_path
from ai_buzz_radar.store import Store


class CheckpointTest(unittest.TestCase):
    def test_new_process_resumes_after_interruption_and_rejects_bad_quote(self):
        day = date(2026, 11, 25)
        urls = [f"https://example.org/article/{i}" for i in range(3)]
        rows = [
            Candidate(f"Article {i}", url, day, "Technical blog", "") for i, url in enumerate(urls)
        ]
        counts = Counter()
        loader = Mock(return_value=b"<article><p>" + b"measured baseline " * 65 + b"</p></article>")

        def discovery(day, days, load, sources):
            load("https://example.org/feed")
            return rows, []

        def transport(folder, prompt, schema, **kwargs):
            counts[schema] += 1
            if schema is CoarseRanking:
                reply = {
                    "shortlist": [{"candidate": i, "reason": "controlled"} for i in range(3)],
                    "exclusions": [],
                }
            elif schema is FineRanking:
                if counts[schema] == 1:
                    raise KeyboardInterrupt("Unexpected process interruption")
                evidence = "bad quote" if counts[schema] == 2 else "measured baseline"
                reply = {
                    "decisions": [
                        dict(
                            url=url,
                            eligible=True,
                            reader_value="读者可以核对助手是否漏掉工具返回的记录。",
                            genre="技术解析",
                            reason="证据",
                            section=0,
                            evidence=evidence,
                            importance=25,
                            evidence_quality=24,
                            knowledge_gain=16,
                            discussion=0,
                            discussion_index=-1,
                            classic_reason="",
                        )
                        for url in urls
                    ],
                    "portfolio_reason": "三个不同的适用场景",
                }
            else:
                self.assertIs(schema, IllustratedCopy)
                self.assertIn("读者可以核对助手是否漏掉工具返回的记录。", prompt)
                reply = {
                    "draft": {
                        "topic": "原型开发",
                        "overview": "对照实验给出了不同设计的适用条件。",
                        "reason": "供开发人员参考其中的对照实验。",
                        "blocks": [
                            {
                                "section": 0,
                                "evidence": "measured baseline",
                                "body": "这组独立的对照实验说明了不同开发设计的适用条件。",
                            }
                            for _ in range(2)
                        ],
                    },
                    "image": None,
                    "localization": {
                        "topic_en": "Prototypes",
                        "reason_en": "Controlled trials.",
                        "summary_en": "An observed result.",
                        "thinking_en": "Try a control.",
                        "image_title_en": "",
                        "image_caption_en": "",
                        "image_alt_en": "",
                    },
                }
            output = schema.model_validate(reply)
            (Path(folder) / "result.json").write_text(output.model_dump_json())
            return output, f"{schema.__name__}-{counts[schema]}"

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "examples"
            folder.mkdir()
            (folder / "index.html").write_text("earlier publication")
            with (
                patch("ai_buzz_radar.editions.discover", side_effect=discovery),
                patch("ai_buzz_radar.editions.hn_discussions", return_value=({}, [], [])),
                patch("ai_buzz_radar.codex_cli.run_cli", side_effect=transport),
            ):
                for error, message in [
                    (KeyboardInterrupt, "interruption"),
                    (ValueError, "evidence"),
                ]:
                    with self.assertRaisesRegex(error, message):
                        generate(
                            CodexCLI(), Store(Path(temp) / "db"), 1, day, folder, loader=loader
                        )
                    self.assertEqual((folder / "index.html").read_text(), "earlier publication")
                generate(CodexCLI(), Store(Path(temp) / "db"), 1, day, folder, loader=loader)
            self.assertEqual(counts, {CoarseRanking: 1, FineRanking: 3, IllustratedCopy: 3})
            self.assertEqual(loader.call_count, 4)
            log = selection_log_path(folder, day)
            record = json.loads(log.read_text())
            self.assertEqual(record["coarse"]["request_id"], "CoarseRanking-1")
            self.assertEqual(record["fine"]["request_id"], "FineRanking-3")
            attempts = [json.loads(p.read_text()) for p in log.parent.glob("attempts/*.json")]
            self.assertEqual(len(attempts), 2)
            interrupted = next(a for a in attempts if "interruption_detected_at" in a)
            self.assertEqual(interrupted["active_stage"], "FineRanking")
            self.assertEqual(interrupted["coarse"]["request_id"], "CoarseRanking-1")
            cache = log.parent / record["checkpoint_directory"]
            self.assertFalse(cache.is_relative_to(folder))
            self.assertEqual(len(list(cache.glob("calls/*/accepted.json"))), 5)
            self.assertFalse((cache / "in-progress.json").exists())

    def test_corrupt_snapshots_and_changed_requests_do_not_reuse_wrong_data(self):
        with tempfile.TemporaryDirectory() as temp:
            day_path = Path(temp) / "2026-11-25.json"
            client = CodexCLI().for_edition(day_path, None)
            counter = Mock(side_effect=[b"first", b"second"])
            read = client.snapshot_loader(counter)
            self.assertEqual(read("https://example.org/page"), b"first")
            self.assertEqual(read("https://example.org/page"), b"first")
            next((client.directory / "sources").iterdir()).write_bytes(b"truncated")
            self.assertEqual(read("https://example.org/page"), b"second")
            revised = CodexCLI().for_edition(day_path, b"old published edition")
            self.assertNotEqual(client.directory, revised.directory)

            response = CoarseRanking(shortlist=[], exclusions=[])

            def transport(folder, *_args, **_kwargs):
                (Path(folder) / "result.json").write_text(response.model_dump_json())
                return response, "abc"

            with patch("ai_buzz_radar.codex_cli.run_cli", side_effect=transport) as run:
                _, rid = client.ask("policy one", CoarseRanking, {})
                client.accept(rid)
                client.ask("policy one", CoarseRanking, {})
                self.assertEqual(run.call_count, 1)
                result = next(client.directory.glob("calls/*/*/result.json"))
                result.write_text('{"shortlist":[],"exclusions":[],"extra":true}')
                _, rid = client.ask("policy one", CoarseRanking, {})
                client.accept(rid)
                client.ask("policy two", CoarseRanking, {})
                self.assertEqual(run.call_count, 3)

    def test_cli_checks_completion_event_and_stops_a_stalled_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            binary = path / "codex"
            binary.write_text(
                '#!/bin/sh\nprintf \'%s\\n\' \'{"type":"thread.started","thread_id":"x"}\'\n'
            )
            binary.chmod(0o700)
            with patch.dict(os.environ, PATH=str(path) + ":" + os.environ["PATH"]):
                with self.assertRaisesRegex(RuntimeError, "did not complete"):
                    run_cli(path, "prompt", CoarseRanking, model="test", effort="low")
                binary.write_text("#!/bin/sh\nsleep 15\n")
                with (
                    patch("ai_buzz_radar.codex_cli.CALL_TIMEOUT_SECONDS", 0.1),
                    self.assertRaisesRegex(RuntimeError, "timed out"),
                ):
                    run_cli(path, "prompt", CoarseRanking, model="test", effort="low")
