import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from ai_buzz_radar.blogs import Candidate
from ai_buzz_radar.editions import (
    Article,
    Draft,
    archive,
    evidence_links,
    exception_note,
    extract,
    generate,
)
from ai_buzz_radar.store import Store

DAY = date(2026, 11, 21)
URL = "https://huggingface.co/blog/test"
SOURCE = b"""<main><article>sidebar</article><div class="blog-content"><h2>
<a id="measured" href="#measured"></a>Measurements</h2><p>Our experiment controls variance.</p>
<h2>Limits</h2><p>Time was not controlled.</p></div></main>"""


def fixture(url):
    draft = Draft(
        topic="评测",
        overview="程序员可以通过控制变量理解这项实验的结果。",
        reason="这项对照实验可以指导工具的选择。",
        blocks=[
            dict(
                title="方法",
                body="段落文本" * 25,
                section=i,
                evidence=["controls variance", "not controlled"][i],
            )
            for i in (0, 0, 1)
        ],
        figure_title="实验对照",
        rows=[dict(label=label, detail="说明") for label in "甲乙"],
        figure_section=1,
    )
    return Article(
        title="Controls",
        url=url,
        source="Test",
        published=DAY,
        request_id="offline",
        note="",
        draft=draft,
        links=evidence_links(draft, url, extract(SOURCE)),
    )


class EditionTest(unittest.TestCase):
    def test_article_targets_and_invalid_evidence(self):
        a = fixture(URL)
        self.assertEqual(a.links[0], URL + "#measured")
        self.assertEqual(a.links[2], URL + "#:~:text=not%20controlled")
        a.draft.blocks[0].evidence = "not mentioned"
        with self.assertRaisesRegex(ValueError, "Evidence"):
            evidence_links(a.draft, URL, extract(SOURCE))

    def test_calendar_threshold_and_repeat(self):
        a = fixture(URL)
        self.assertEqual(exception_note(DAY + timedelta(days=29), a, {}), "")
        note = exception_note(DAY + timedelta(days=30), a, {URL: DAY})
        self.assertIn("30 天", note)
        self.assertIn(str(DAY), note)

    def test_atomic_publication_caching_and_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            store = Store(folder / "db")
            urls = [URL + str(i) for i in range(3)]
            rows = [Candidate("Test", u, DAY, "Test", "") for u in urls]
            with (
                patch("ai_buzz_radar.editions.discover", return_value=(rows, [])),
                patch(
                    "ai_buzz_radar.editions.write_article",
                    side_effect=lambda c, s, b, d, i, n, loader: fixture(i.url),
                ) as writer,
            ):
                with self.assertRaises(ValueError):
                    generate(None, store, 1, DAY, folder, [urls[0]] * 3)
                self.assertFalse((folder / "index.html").exists())
                generate(None, store, 1, DAY, folder, urls)
                generate(None, store, 1, DAY, folder, urls)
                self.assertEqual(writer.call_count, 3)
                tomorrow = DAY + timedelta(days=1)
                with patch("ai_buzz_radar.editions.rank", return_value=([], None)):
                    saved = generate(None, store, 1, tomorrow, folder)
                self.assertTrue(all(str(DAY) in a.note for a in saved.articles))
                self.assertEqual(len(archive(folder)), 2)
                page = BeautifulSoup((folder / "index.html").read_text(), "html.parser")
                self.assertEqual(len(page.select("article details table")), 3)
                self.assertEqual(len(page.select("article h4")), 6)
                self.assertEqual(len(page.select("article > .full")), 3)
                self.assertEqual(len(page.select("nav a")), 2)

    def test_reviewed_november_backfill(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        issues = {ed.day: ed for ed in archive(examples)}
        seen = set()
        for offset in range(3):
            day = DAY + timedelta(days=offset)
            ed = issues[day]
            self.assertEqual(len(ed.articles), 3)
            page = BeautifulSoup(
                (examples / f"agent-reading-{day}.html").read_text(), "html.parser"
            )
            for article, card in zip(ed.articles, page.select("article"), strict=True):
                self.assertNotIn(article.url, seen)
                self.assertTrue(0 <= (day - article.published).days < 30)
                self.assertFalse(article.note)
                self.assertEqual(card.h2.get_text(), article.title)
                meta = card.h2.find_previous_sibling()
                self.assertEqual(
                    meta.get_text(), f"{article.draft.topic}　{article.published}　{article.source}"
                )
                self.assertEqual(
                    [h.get_text() for h in card.select("details h4")], ["Summary", "Thinking"]
                )
                self.assertNotRegex(card.details.get_text(), r"(?:3|7|5) 分钟 ·")
                self.assertEqual(card.select_one(".full a")["href"], article.url)
                self.assertEqual({a["href"] for a in card.select("details a")}, set(article.links))
                seen.add(article.url)

    def test_control_uses_same_article_layout_and_links_back_to_same_day(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        control = examples / "codex-cli"
        controls = archive(control)
        self.assertIn(DAY + timedelta(days=2), [e.day for e in controls])
        for edition in controls:
            name = f"agent-reading-{edition.day}.html"
            for base, destination in ((examples, control), (control, examples)):
                doc = BeautifulSoup((base / name).read_text(), "html.parser")
                link = doc.select_one('footer a[href*="agent-reading-"]')
                self.assertEqual((base / link["href"]).resolve(), destination / name)
                for card in doc.select("article"):
                    self.assertEqual(card.select_one(".meta").find_next_sibling().name, "h2")
                    self.assertEqual(
                        [h.get_text() for h in card.select("details h4")], ["Summary", "Thinking"]
                    )
