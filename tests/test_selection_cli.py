import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ai_buzz_radar.cli import main
from ai_buzz_radar.codex_cli import CodexCLI
from ai_buzz_radar.selection_log import selection_log_path


class SelectionCLITest(unittest.TestCase):
    def test_default_engine_and_private_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "examples"
            day = date(2026, 11, 25)
            log = selection_log_path(output, day)
            log.parent.mkdir(parents=True)
            payload = {"day": str(day), "mode": "test"}
            log.write_text(json.dumps(payload))
            with (
                patch("ai_buzz_radar.editions.generate") as generate,
                patch("ai_buzz_radar.cli.open_client") as responses,
                redirect_stdout(io.StringIO()) as stdout,
            ):
                generate.return_value.day = day
                self.assertEqual(
                    main(
                        [
                            "--db",
                            str(root / "db"),
                            "edition",
                            "--day",
                            str(day),
                            "--output",
                            str(output),
                        ]
                    ),
                    0,
                )
            self.assertIsInstance(generate.call_args.args[0], CodexCLI)
            (output / "editions").mkdir(parents=True)
            (output / "editions" / f"{day}.json").write_text("{}")
            with (
                patch("ai_buzz_radar.editions.generate") as again,
                patch("ai_buzz_radar.cli.open_client") as other_engine,
                redirect_stdout(io.StringIO()),
            ):
                again.return_value.day = day
                self.assertEqual(
                    main(
                        [
                            "--db",
                            str(root / "db"),
                            "edition",
                            "--day",
                            str(day),
                            "--output",
                            str(output),
                            "--reselect",
                        ]
                    ),
                    0,
                )
            self.assertIsInstance(again.call_args.args[0], CodexCLI)
            self.assertTrue(again.call_args.kwargs["reselect"])
            other_engine.assert_not_called()
            responses.assert_not_called()
            self.assertIn(str(log), stdout.getvalue())
            self.assertFalse(log.is_relative_to(output))
            summary = "# 选稿记录\n"
            log.with_suffix(".md").write_text(summary)
            for args, expected in (([], log.read_text()), (["--format", "markdown"], summary)):
                with (
                    self.subTest(args=args),
                    redirect_stdout(io.StringIO()) as stdout,
                    patch("ai_buzz_radar.cli.Store") as db,
                ):
                    cmd = ["selection", "--day", str(day), "--output", str(output), *args]
                    self.assertEqual(main(cmd), 0)
                    db.assert_not_called()
                    self.assertEqual(stdout.getvalue(), expected)
