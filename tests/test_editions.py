import base64
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from hashlib import sha256
from os.path import relpath
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from ai_buzz_radar.blogs import Candidate
from ai_buzz_radar.editions import (
    Article,
    CoarseRanking,
    Draft,
    Edition,
    FineRanking,
    archive,
    evidence_links,
    exception_note,
    extract,
    generate,
    original_reading_url,
    publish,
    rank,
)
from ai_buzz_radar.selection_log import selection_log_path
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

    def test_failed_selection_leaves_homepage_and_original_record_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "examples"
            store = Store(Path(temp) / "db")
            urls = [URL + str(i) for i in range(3)]
            rows = [Candidate("Test", u, DAY, "Test", "") for u in urls]
            with (
                patch("ai_buzz_radar.editions.discover", return_value=(rows, [])),
                patch(
                    "ai_buzz_radar.editions.write_article",
                    side_effect=lambda c, s, b, d, item, *rest: fixture(item.url),
                ) as writer,
            ):
                with self.assertRaises(ValueError):
                    generate(None, store, 1, DAY, folder, [urls[0]] * 3)
                self.assertFalse((folder / "index.html").exists())
                first_issue = generate(None, store, 1, DAY, folder, urls)
                self.assertIsNotNone(first_issue.updated_at)
                first_page = (folder / "index.html").read_bytes()
                log_path = selection_log_path(folder, DAY)
                before = log_path.stat().st_mtime_ns, log_path.read_bytes()
                generate(None, store, 1, DAY, folder, urls)
                self.assertEqual((log_path.stat().st_mtime_ns, log_path.read_bytes()), before)
                self.assertEqual((folder / "index.html").read_bytes(), first_page)
                self.assertEqual(writer.call_count, 3)
                latest = (folder / "index.html").read_bytes()
                tomorrow = DAY + timedelta(days=1)
                with (
                    patch("ai_buzz_radar.editions.coarse_rank", return_value=[]),
                    self.assertRaisesRegex(ValueError, "Fewer than three"),
                ):
                    generate(None, store, 1, tomorrow, folder)
                self.assertEqual(len(archive(folder)), 1)
                self.assertEqual((folder / "index.html").read_bytes(), latest)
                self.assertFalse(selection_log_path(folder, tomorrow).exists())
                failures = list((log_path.parent / "attempts").glob(f"{tomorrow}-*.json"))
                self.assertEqual(json.loads(failures[0].read_text())["status"], "failed")
                page = BeautifulSoup(latest.decode(), "html.parser")
                self.assertEqual(len(page.select("article figure > img")), 3)
                self.assertEqual(len(page.select("article h3")), 9)
                self.assertEqual(len(page.select("article.reading-card > details:not([open])")), 3)
                self.assertEqual(len(page.select("article details .close-card[type=button]")), 3)
                self.assertFalse(page.select("article > blockquote"))
                self.assertEqual(len(page.select("article details > .article-body > .full")), 3)
                self.assertFalse(page.select("nav a"))
                self.assertEqual(
                    [tag.get_text() for tag in page.select("article .meta em")], ["首次入选"] * 3
                )

    def test_same_day_reselection_keeps_original_audit_and_rolls_back_render_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            folder, store = Path(temp) / "examples", Store(Path(temp) / "db")
            urls = [URL + str(i) for i in range(6)]
            rows = [Candidate("Test", url, DAY, "Test", "") for url in urls]
            with (
                patch("ai_buzz_radar.editions.discover", return_value=(rows, [])),
                patch(
                    "ai_buzz_radar.editions.write_article",
                    side_effect=lambda c, s, b, d, item, *rest: fixture(item.url),
                ),
            ):
                original = generate(None, store, 1, DAY, folder, urls[:3])
                current = selection_log_path(folder, DAY)
                md = current.with_suffix(".md")
                md.write_text("编辑补录，参见 [JSON](" + current.name + ")。")
                old_json, old_md = current.read_bytes(), md.read_bytes()
                old_html = (folder / "index.html").read_bytes()
                old_edition = (folder / "editions" / f"{DAY}.json").read_bytes()

                def broken(staged, editions, **kwargs):
                    (staged / "index.html").with_suffix(".tmp").write_text("incomplete")
                    (staged / "index.tmp").replace(staged / "index.html")
                    raise ValueError("Cannot render")

                with (
                    patch("ai_buzz_radar.editions.publish", side_effect=broken),
                    self.assertRaisesRegex(ValueError, "Cannot render"),
                ):
                    generate(None, store, 1, DAY, folder, urls[3:], reselect=True)
                self.assertEqual((folder / "index.html").read_bytes(), old_html)
                self.assertEqual(current.read_bytes(), old_json)
                self.assertEqual(md.read_bytes(), old_md)
                self.assertEqual((folder / "editions" / f"{DAY}.json").read_bytes(), old_edition)
                self.assertFalse((current.parent / "revisions").exists())

                result = generate(None, store, 1, DAY, folder, urls[3:], reselect=True)
                self.assertEqual([a.url for a in result.articles], urls[3:])
                self.assertNotEqual(result, original)
                self.assertEqual(len(archive(folder)), 1)
                self.assertEqual(
                    (folder / "index.html").read_bytes(),
                    (folder / f"agent-reading-{DAY}.html").read_bytes(),
                )
                self.assertNotEqual((folder / "index.html").read_bytes(), old_html)
                updated = json.loads(current.read_text())
                prior = {k: current.parent / v for k, v in updated["supersedes"].items()}
                self.assertEqual(prior["record"].read_bytes(), old_json)
                self.assertEqual(prior["report"].read_bytes(), old_md)
                self.assertEqual(prior["edition"].read_bytes(), old_edition)
                self.assertIn(updated["supersedes"]["report"], md.read_text())
                self.assertNotIn("编辑补录", md.read_text())
                generate(None, store, 1, DAY, folder, urls[:3], reselect=True)
                second = json.loads(current.read_text())["supersedes"]
                archived = current.parent / second["report"]
                self.assertEqual(len(list(archived.parent.parent.iterdir())), 2)
                self.assertIn(relpath(prior["report"], archived.parent), archived.read_text())

    def test_first_publication_requires_valid_render_before_success_or_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "nested" / "examples"
            store = Store(Path(temp) / "db")
            urls = [URL + str(i) for i in range(3)]
            rows = [Candidate("Test", u, DAY, "Test", "") for u in urls]

            def invalid_render(staged, editions, **kwargs):
                publish(staged, editions, **kwargs)
                (staged / "index.html").unlink()
                (staged / "index.html").write_text("<html></html>")

            with (
                patch("ai_buzz_radar.editions.discover", return_value=(rows, [])),
                patch(
                    "ai_buzz_radar.editions.write_article", side_effect=lambda *a: fixture(a[4].url)
                ),
            ):
                with (
                    patch("ai_buzz_radar.editions.publish", side_effect=invalid_render),
                    self.assertRaisesRegex(ValueError, "homepage"),
                ):
                    generate(None, store, 1, DAY, folder, urls)
                current = selection_log_path(folder, DAY)
                self.assertFalse(current.exists())
                self.assertFalse((folder / "index.html").exists())
                self.assertFalse((folder / "editions" / f"{DAY}.json").exists())
                self.assertEqual(len(list((current.parent / "attempts").glob("*.json"))), 1)
                generate(None, store, 1, DAY, folder, urls)
                checksum = sha256((folder / "editions" / f"{DAY}.json").read_bytes()).hexdigest()
                self.assertEqual(json.loads(current.read_text())["edition_sha256"], checksum)

    def test_latest_only_and_selection_history(self):
        issues = [
            Edition(
                day=DAY + timedelta(days=offset),
                articles=[fixture(URL + letter) for letter in letters],
            )
            for offset, letters in enumerate(("abc", "acd", "abe"))
        ]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            publish(folder, reversed(issues))
            latest = (folder / "index.html").read_bytes()
            self.assertEqual(latest, (folder / f"agent-reading-{issues[-1].day}.html").read_bytes())
            self.assertTrue((folder / f"agent-reading-{DAY}.html").is_file())
            page = BeautifulSoup(latest.decode(), "html.parser")
            self.assertFalse(page.select('a[href*="agent-reading-"]'))
            cards = page.select("article .meta")
            self.assertEqual(
                [meta.em.get_text() for meta in cards], ["连续入选", "再度入选", "首次入选"]
            )
            self.assertIn("第 3 天", cards[0].get_text())
            self.assertNotIn("第 ", cards[1].get_text())
            first_page = folder / f"agent-reading-{DAY}.html"
            self.assertFalse(page.select(".like, [data-counter], #views"))
            self.assertNotIn("abacus.jasoncameron.dev", latest.decode())
            first_page.write_text("Already published")
            publish(folder, issues, only_day=issues[-1].day)
            self.assertEqual(first_page.read_text(), "Already published")
            self.assertEqual((folder / "index.html").read_bytes(), latest)

    def test_fine_ranking_requires_reader_value_for_every_eligible_item(self):
        decision = dict(
            url=URL, eligible=True, genre="技术解析", reason="有可复核的实验",
            section=0, evidence="matched trials", reader_value="  ",
        )
        with self.assertRaisesRegex(ValueError, "reader_value"):
            FineRanking(decisions=[decision], portfolio_reason="问题互补")
        decision.update(eligible=False, reader_value="")
        result = FineRanking(decisions=[decision], portfolio_reason="问题互补")
        self.assertFalse(result.decisions[0].eligible)

    def test_three_stages_keep_evidence_reasons_reserves_and_no_history_in_model_inputs(self):
        urls = [URL + str(i) for i in range(9)]
        rows = [Candidate("Study " + str(i), u, DAY, "Test", "") for i, u in enumerate(urls)]
        rows[-1] = Candidate("Stale study", urls[-1], DAY - timedelta(days=35), "Test", "")
        source = (
            b'<article><h2 id="m">Method</h2><p>'
            + b"Repeated, matched trials. " * 44
            + b"</p></article>"
        )

        def ask(*args, **kwargs):
            schema, payload = args[5:7]
            self.assertNotIn("recent_editions", payload)
            self.assertNotIn("previous", json.dumps(payload, default=str))
            if schema is CoarseRanking:
                self.assertEqual(len(payload["candidates"]), 8)
                return schema(
                    shortlist=[
                        dict(candidate=i, reason="Evidence to inspect")
                        for i in [0, 1, 2, 3, 4, 5, 7]
                    ],
                    exclusions=[dict(reason="routine_test", candidates=[6])],
                ), "coarse-call"
            self.assertIs(schema, FineRanking)
            self.assertEqual(len(payload["candidates"]), 6)
            self.assertIn("可能从未开发过", payload["audience"])
            for row in payload["candidates"]:
                self.assertIn("matched trials", row["sections"][0]["text"])
            return schema(
                portfolio_reason="工具接口、上下文设计和部署验证三种问题互补，候补重复了验证环节。",
                decisions=[
                    dict(
                        url=urls[i],
                        eligible=i != 3,
                        reader_value=f"读者在情境 {i} 下可以核对工具的结果。" if i != 3 else "",
                        genre="实战复盘" if i % 2 else "技术解析",
                        section=0,
                        evidence="matched trials",
                        reason="检查了等预算对照",
                    )
                    for i in [0, 1, 2, 4, 7, 3]
                ],
            ), "fine-call"

        def read(url):
            if url == urls[5]:
                raise OSError("Source unavailable")
            return source

        def write(*args):
            i = urls.index(args[4].url)
            self.assertEqual(args[-1], f"读者在情境 {i} 下可以核对工具的结果。")
            if args[4].url == urls[1]:
                raise ValueError("Evidence link missing")
            return fixture(args[4].url)

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "examples"
            store = Store(Path(temp) / "db")
            with (
                patch("ai_buzz_radar.editions.discover", return_value=(rows, [])),
                patch("ai_buzz_radar.editions.ask", side_effect=ask),
                patch(
                    "ai_buzz_radar.editions.write_article", side_effect=lambda *a: fixture(a[4].url)
                ),
            ):
                generate(None, store, 1, DAY, folder, urls[:3], loader=read)
            previously_published = folder / f"agent-reading-{DAY}.html"
            previously_published.write_text("Original published page")
            tomorrow = DAY + timedelta(days=1)
            with (
                patch("ai_buzz_radar.editions.discover", return_value=(rows, ["Index B offline"])),
                patch("ai_buzz_radar.editions.ask", side_effect=ask),
                patch("ai_buzz_radar.editions.write_article", side_effect=write),
            ):
                issue = generate(None, store, 1, tomorrow, folder, loader=read)
            self.assertEqual([a.url for a in issue.articles], [urls[0], urls[2], urls[4]])
            log = json.loads(selection_log_path(folder, tomorrow).read_text())
            self.assertFalse(log["history_used_for_ranking"])
            self.assertEqual(log["recall"]["count"], 8)
            self.assertEqual(log["recall"]["by_date"], {DAY.isoformat(): 8})
            self.assertEqual(log["recall"]["by_source"], {"Test": 8})
            self.assertEqual(log["recall"]["by_channel"], {"first_party_sites": 8, "arxiv": 0})
            self.assertTrue(all(item["channel"] == "first_party_sites" for item in log["selected"]))
            start, end = [datetime.fromisoformat(log[key]) for key in ["started_at", "finished_at"]]
            self.assertIsNotNone(start.utcoffset())
            self.assertGreaterEqual(end, start)
            self.assertEqual(previously_published.read_text(), "Original published page")
            self.assertEqual(log["recall"]["warnings"], ["Index B offline"])
            self.assertEqual(log["coarse"]["items"][6]["status"], "excluded")
            self.assertEqual(log["coarse"]["request_id"], "coarse-call")
            self.assertEqual(log["fine"]["request_id"], "fine-call")
            self.assertEqual(log["fine"]["proposed_urls"], urls[:3])
            self.assertIn("三种问题互补", log["fine"]["portfolio_reason"])
            reviews = {r["url"]: r for r in log["fine"]["items"]}
            self.assertEqual(reviews[urls[1]]["status"], "draft_failed")
            self.assertEqual(reviews[urls[1]]["genre"], "实战复盘")
            self.assertTrue(all(r["genre"] == reviews[r["url"]]["genre"] for r in log["selected"]))
            self.assertEqual(reviews[urls[3]]["status"], "excluded")
            self.assertEqual(reviews[urls[5]]["status"], "source_unavailable")
            self.assertEqual(reviews[urls[7]]["status"], "reserve")
            self.assertIn("情境 7", reviews[urls[7]]["reader_value"])
            report = selection_log_path(folder, tomorrow).with_suffix(".md").read_text()
            for winner in log["selected"]:
                self.assertIn(reviews[winner["url"]]["reader_value"], report)
            self.assertEqual(reviews[urls[4]]["evidence_url"], urls[4] + "#m")
            for review in reviews.values():
                if "evidence" in review:
                    excerpts = {part["section"]: part for part in review["excerpts"]}
                    cited = excerpts[review["evidence_section"]]
                    self.assertEqual(cited["heading"], "Method")
                    self.assertIn(review["evidence"], cited["text"])
            self.assertEqual([r["url"] for r in log["selected"]], [a.url for a in issue.articles])
            self.assertNotIn("selection-records", (folder / "index.html").read_text())

    def test_independent_channel_nominations_merge_before_unrestricted_fine_ranking(self):
        papers = [
            Candidate(str(i), f"https://arxiv.org/html/2611.{i:05}v1", DAY, "arXiv", "")
            for i in range(12)
        ]
        posts = [Candidate(str(i), URL + str(i), DAY, "Hugging Face", "") for i in range(12)]
        source = b"<article><p>" + b"matched trials " * 100 + b"</p></article>"

        def nominations(count):
            return CoarseRanking(
                shortlist=[
                    dict(candidate=i, reason=f"matched evidence {i}")
                    for i in reversed(range(count))
                ],
                exclusions=[dict(reason="routine_test", candidates=list(range(count, 12)))],
            )

        for count in (12, 2, 0):
            with self.subTest(nominated_posts=count):
                # Both editorial lists start strongest first, in reverse index order.
                forwarded_posts = min(count, 6)
                chosen_posts = list(reversed(posts[:count]))[:forwarded_posts]
                chosen_papers = list(reversed(papers))[: 12 - forwarded_posts]
                mixed = []
                for i, paper in enumerate(chosen_papers):
                    if i < forwarded_posts:
                        mixed.append(chosen_posts[i].url)
                    mixed.append(paper.url)
                fine = FineRanking(
                    portfolio_reason="三篇的对照分别能指导三种开发决定，其他原文证据较弱。",
                    decisions=[
                        dict(
                            url=item.url,
                            eligible=i < 3,
                            reader_value="读者可以判断回答是否有依据。" if i < 3 else "",
                            genre="研究论文" if item in chosen_papers else "开发指南",
                            reason="原文提供了所需的证据",
                            section=0,
                            evidence="matched trials",
                        )
                        for i, item in enumerate(chosen_papers + chosen_posts)
                    ],
                )
                record = {"coarse": {}, "fine": {}}
                with patch(
                    "ai_buzz_radar.editions.ask",
                    side_effect=[
                        (nominations(count), "sites-call"),
                        (nominations(12), "arxiv-call"),
                        (fine, "fine-call"),
                    ],
                ) as ask:
                    eligible, _ = rank(None, None, 0, DAY, papers + posts, record, lambda _: source)
                site_payload, paper_payload, fine_payload = [
                    call.args[6] for call in ask.call_args_list
                ]
                self.assertEqual(
                    {r["source"] for r in site_payload["candidates"]}, {"Hugging Face"}
                )
                self.assertEqual({r["source"] for r in paper_payload["candidates"]}, {"arXiv"})
                self.assertEqual([r["url"] for r in fine_payload["candidates"]], mixed)
                self.assertEqual(eligible, [p.url for p in chosen_papers[:3]])
                channels = record["coarse"]["channels"]
                self.assertEqual(
                    channels["first_party_sites"],
                    dict(
                        request_id="sites-call",
                        presented_count=12,
                        nomination_count=count,
                        shortlist_count=forwarded_posts,
                    ),
                )
                self.assertEqual(
                    channels["arxiv"],
                    dict(
                        request_id="arxiv-call",
                        presented_count=12,
                        nomination_count=12,
                        shortlist_count=len(chosen_papers),
                    ),
                )
                overflow = [r for r in record["coarse"]["items"] if r["status"] == "merge_cap"]
                self.assertEqual(len(overflow), count)
                for row in overflow:
                    self.assertIn("精读上限", row["reason"])
                    self.assertIn("matched evidence", row["nomination_reason"])
                    self.assertGreater(
                        row["nomination_rank"], channels[row["channel"]]["shortlist_count"]
                    )

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
                if meta.em:
                    self.assertEqual(meta.em.extract().get_text(), "首次入选")
                self.assertEqual(
                    meta.get_text().strip(),
                    f"{article.draft.topic}　{article.published}　{article.source}",
                )
                self.assertEqual(
                    [h.get_text() for h in card.select("h3")], ["推荐理由", "内容摘要", "延伸思考"]
                )
                self.assertNotRegex(card.get_text(), r"(?:3|7|5) 分钟 ·")
                self.assertEqual(
                    card.select_one(".full a")["href"],
                    original_reading_url(article.url),
                )
                self.assertEqual(
                    {a["href"] for a in card.select("p:not(.full) a, figcaption a")},
                    {original_reading_url(url) for url in article.links},
                )
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
                        [h.get_text() for h in card.select("h3")],
                        ["推荐理由", "内容摘要", "延伸思考"],
                    )

    def test_mobile_edition_round_trip(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        issue = next(e for e in archive(examples) if e.day == date(2026, 11, 24))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            shutil.copytree(examples / "figures/originals", folder / "figures/originals")
            publish(folder, [issue])
            page = BeautifulSoup((folder / "index.html").read_text(), "html.parser")
            for article, card in zip(issue.articles, page.select("article"), strict=True):
                self.assertFalse(card.details.has_attr("open"))
                self.assertIsNotNone(card.details.summary)
                self.assertEqual(card.h2.find_next_sibling("h3").get_text(), "核心看点")
                figure = card.figure
                self.assertEqual(figure.find_previous_sibling("h3").get_text(), "内容摘要")
                self.assertEqual(figure.find_next_sibling("h3").get_text(), "延伸思考")
                original_image = article.original_image
                self.assertIsNotNone(original_image)
                self.assertEqual(figure.img["alt"], original_image.alt)
                blob = base64.b64decode(figure.img["src"].split(",")[1], validate=True)
                path = folder / "figures/originals" / original_image.filename
                self.assertEqual(blob, path.read_bytes())
                self.assertGreater(len(blob), 1000)
                self.assertEqual(
                    figure.figcaption.a["href"], original_reading_url(original_image.source_url)
                )
                self.assertIn(article.draft.reason, card.get_text())
                self.assertTrue(article.draft.reason.strip())
                self.assertEqual(
                    [h.get_text() for h in card.select("h3")], ["核心看点", "内容摘要", "延伸思考"]
                )
                self.assertNotIn("分钟速览", page.get_text())
                self.assertEqual(
                    [a["href"] for a in card.select("p:not(.full) a")],
                    [original_reading_url(url) for url in article.links],
                )
                self.assertTrue(article.translation_url)
                original, translated = [a["href"] for a in card.select(".full a")]
                self.assertEqual(original, original_reading_url(article.url))
                self.assertNotEqual(original, translated)
                self.assertEqual(translated, article.translation_url)
