import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ai_buzz_radar.pages import push_pages


class PagesTest(unittest.TestCase):
    def test_publish_preserves_homepage_dates_and_skips_duplicate_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root)

            git("init", "--bare", "--initial-branch=main", str(remote))
            git("clone", str(remote), "seed")
            (root / "seed" / "index.html").write_bytes(b"personal website")
            git("-C", "seed", "add", "index.html")
            git(
                "-C",
                "seed",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.org",
                "commit",
                "-m",
                "Initial homepage",
            )
            git("-C", "seed", "push", "origin", "main")
            first, second = date(2026, 11, 25), date(2026, 11, 26)
            for html, day in [(b"first", first), (b"second", second), (b"revised", second)]:
                push_pages(html, day, remote.as_uri())

            def rev(*args):
                return git("--git-dir", str(remote), *args)

            before = rev("rev-parse", "main")
            push_pages(b"revised", second, remote.as_uri())
            self.assertEqual(before, rev("rev-parse", "main"))
            self.assertEqual(rev("show", "main:index.html"), b"personal website")
            self.assertEqual(rev("show", f"main:radar/agent-reading-{first}.html"), b"first")
            self.assertEqual(rev("show", f"main:radar/agent-reading-{second}.html"), b"revised")
            self.assertEqual(rev("show", "main:radar/index.html"), b"revised")
