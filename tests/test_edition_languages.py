import json
import unittest
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from ai_buzz_radar.editions import (
    Article,
    MobileDraft,
    archive,
    article_html,
    article_md,
    chinese_alternate,
)
from ai_buzz_radar.editions import original_reading_url as original_url


class ReadingLanguageTest(unittest.TestCase):
    def test_bilingual_issue_translates_copy_and_scopes_reading_links(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        issue = next(ed for ed in archive(examples) if ed.day == date(2026, 11, 25))
        page_path = examples / f"agent-reading-{issue.day}.html"
        page = BeautifulSoup(page_path.read_text(), "html.parser")
        self.assertEqual(page.html["lang"], "zh-CN")
        switch = page.select(".language-switch button[data-language]")
        self.assertEqual([b.get_text(strip=True) for b in switch], ["中文", "English"])
        self.assertEqual([b["aria-pressed"] for b in switch], ["true", "false"])
        self.assertFalse(page.footer.select('a[href="index.html"]'))
        self.assertNotIn("最新一期", page.footer.get_text())
        self.assertEqual(
            page.footer.select_one('[data-en="Edited by Mr. Tree & GPT"]').get_text(),
            "编辑：树先生 & GPT",
        )
        self.assertIsNotNone(issue.updated_at)
        self.assertEqual(page.footer.time["datetime"], issue.updated_at.isoformat())
        self.assertIn("UTC+8", page.footer.time.get_text())
        english_cards = json.loads(page.select_one("script#english-cards").string)
        for article, zh, html in zip(
            issue.articles, page.select("article"), english_cards, strict=True
        ):
            with self.subTest(url=article.url):
                copy = article.localization
                self.assertEqual(zh.h2.get_text(), article.title)
                self.assertEqual(
                    [h.get_text() for h in zh.select("h3")], ["核心看点", "内容摘要", "延伸思考"]
                )
                en = BeautifulSoup(html, "html.parser")
                self.assertEqual(en.h2.get_text(), article.title)
                self.assertEqual(
                    [h.get_text() for h in en.select("h3")],
                    ["Highlight", "Summary", "Takeaways"],
                )
                text = en.get_text(" ", strip=True)
                for value in (copy.topic_en, copy.reason_en, copy.summary_en, copy.thinking_en):
                    for paragraph in value.splitlines():
                        self.assertIn(paragraph.strip(), text)
                self.assertNotRegex(text, r"[\u4e00-\u9fff]")
                self.assertEqual(en.img["alt"], copy.image_alt_en)
                self.assertEqual(en.figcaption.strong.get_text(), copy.image_title_en)
                self.assertIn(copy.image_caption_en, en.figcaption.get_text())
                source = original_url(article.url)
                self.assertEqual([a["href"] for a in en.select(".full a")], [source])
                chinese_reading_links = [source]
                if article.translation_url:
                    chinese_reading_links.append(article.translation_url)
                self.assertEqual([a["href"] for a in zh.select(".full a")], chinese_reading_links)
                evidence_links = "p:not(.full) a, figcaption a"
                self.assertEqual(
                    [a["href"] for a in en.select(evidence_links)],
                    [a["href"] for a in zh.select(evidence_links)],
                )

    def test_english_entry_preserves_source_fragment(self):
        url = "https://openai.com/index/control-room"
        self.assertEqual(
            original_url(url + "#sections"), url.replace("/index", "/en-US/index") + "/#sections"
        )
        url = "https://www.anthropic.com/research/components-of-agent-memory"
        self.assertEqual(original_url(url), url)

    def test_prefer_publishers_simplified_chinese(self):
        url = "https://blog.cloudflare.com/story/"
        markup = (
            '<link rel="alternate" hreflang="zh-Hans" href="https://example.com/wrong">'
            '<link rel="alternate" hreflang="zh-TW" href="/zh-tw/story/">'
        )
        self.assertEqual(chinese_alternate(markup, url), "https://blog.cloudflare.com/zh-tw/story/")
        markup += '<link rel="alternate" hreflang="zh-CN" href="/zh-cn/story/">'
        self.assertEqual(chinese_alternate(markup, url), "https://blog.cloudflare.com/zh-cn/story/")
        self.assertIsNone(
            chinese_alternate('<link rel="alternate" hreflang="zh" href="/story/">', url)
        )

    def test_article_links_only_to_the_original_and_available_official_translation(self):
        url = "https://www.anthropic.com/research/components-of-agent-memory"
        draft = MobileDraft(
            topic="记忆系统",
            overview="给跨会话记忆选择合适的组织方式。",
            reason="阅读这篇可以对照自己的跨会话记忆设计。",
            blocks=[
                dict(
                    body="研究者让模型回查原始日志，修正记忆笔记中的错误。\n可以记录回查前后的误判率，再判断检索的收益。",
                    section=0,
                    evidence="some notes",
                )
            ]
            * 2,
        )
        article = Article(
            title="The components of agent memory",
            source="Anthropic",
            published="2026-11-06",
            url=url,
            note="",
            links=[url + "#notes", url + "#:~:text=some%20notes"],
            draft=draft,
        )
        for translated in (None, url.replace("/research", "/zh-CN/research")):
            article.translation_url = translated
            with self.subTest(translated=translated):
                doc = BeautifulSoup(str(article_html(article_md(article))), "html.parser")
                expected = [("英文原文", url)]
                if translated:
                    expected.append(("官方中文译文", translated))
                self.assertEqual(
                    [(a.get_text(), a["href"]) for a in doc.select(".full a")], expected
                )
                self.assertIsNone(doc.select_one(".full button"))
                _, summary, thinking = doc.select("h3")
                self.assertEqual(
                    summary.find_next_sibling("p").find_next_sibling("p").a.get_text(), "原文章节"
                )
                fact = thinking.find_next_sibling("p")
                self.assertEqual(fact.a.get_text(), "定位原句")
                self.assertIsNone(fact.find_next_sibling("p").a)
