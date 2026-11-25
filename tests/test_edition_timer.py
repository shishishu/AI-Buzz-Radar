import hashlib
import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

from ai_buzz_radar.selection_log import save_selection_log, selection_summary_ready
from scripts import run_scheduled_edition as timer


class EditionTimerTest(unittest.TestCase):
    def test_due_date_uses_shanghai_2100_including_reboot_before_publication(self):
        self.assertEqual(
            timer.scheduled_day(datetime(2026, 1, 1, 2, tzinfo=UTC)), date(2025, 12, 31)
        )
        self.assertEqual(
            timer.scheduled_day(datetime(2026, 1, 1, 13, tzinfo=UTC)), date(2026, 1, 1)
        )

    def test_cached_edition_verify_repair_and_reselect(self):
        day = "2026-11-25"
        now = datetime(2026, 11, 25, 13, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "examples"
            editions = output / "editions"
            editions.mkdir(parents=True)
            items = [{"url": f"https://example.com/{i}", "title": str(i)} for i in range(3)]
            edition = editions / f"{day}.json"
            edition.write_text(json.dumps({"day": day, "articles": items}))
            record = {
                "schema_version": 1,
                "day": day,
                "status": "selected",
                "mode": "automatic",
                "recall": {},
                "coarse": {},
                "fine": {},
                "selected": items,
                "edition_sha256": hashlib.sha256(edition.read_bytes()).hexdigest(),
            }
            log = save_selection_log(output, record)
            page = output / f"agent-reading-{day}.html"
            page.write_text("published")
            (output / "index.html").write_bytes(page.read_bytes())
            page.with_suffix(".md").write_text("edition")
            with patch.object(timer, "radar") as invoke:
                # The day was published early; an early catch-up must keep it intact.
                self.assertEqual(timer.run(output, now.replace(hour=4)), 0)
                invoke.assert_not_called()
            report = log.with_suffix(".md")
            summary = report.read_bytes()
            report.write_bytes(summary[:-35])
            self.assertFalse(selection_summary_ready(log, record))
            with patch.object(timer, "radar", return_value=1) as invoke:
                self.assertEqual(timer.run(output, now), 1)
                self.assertNotIn("--reselect", invoke.call_args.args[0])
            self.assertTrue(selection_summary_ready(log, record, restore=True))
            self.assertEqual(report.read_bytes(), summary)
            for invalid in ('{"selected":', json.dumps({**record, "edition_sha256": "invalid"})):
                with (
                    self.subTest(invalid=invalid),
                    patch.object(timer, "radar", return_value=1) as invoke,
                ):
                    log.write_text(invalid)
                    self.assertEqual(timer.run(output, now), 1)
                    self.assertIn("--reselect", invoke.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
