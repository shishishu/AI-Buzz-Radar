import unittest
from datetime import date
from unittest.mock import Mock

from ai_buzz_radar.blogs import Source
from ai_buzz_radar.editions import extract
from ai_buzz_radar.publisher_images import image_candidates
from ai_buzz_radar.research_sources import (
    DEVELOPER_SOURCES,
    arxiv_candidates,
    arxiv_query_url,
    discover_editions,
)

DAY = date(2026, 11, 25)


def feed(entries):
    rows = "".join(
        f"<entry><id>http://arxiv.org/abs/{paper_id}</id><published>{first}T12:00:00Z</published>"
        f"<updated>{updated}T12:00:00Z</updated><title>Study {paper_id}</title>"
        "<summary>Control and ablation.</summary></entry>"
        for paper_id, first, updated in entries
    )
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{rows}</feed>'.encode()


class ResearchSourcesTest(unittest.TestCase):
    def test_developer_source_lists_and_reads_author_guides(self):
        url = "https://www.langchain.com/blog/knowledge-factory"

        def card(slug, day):
            return (
                f'<div class="blog-list is-normal"><div class="blog-item"><h2>{slug}</h2>'
                f'<div class="date-color">{day}</div><a class="blog-link-absolute" '
                f'href="/blog/{slug}"></a></div></div>'
            ).encode()

        first_page = card("knowledge-factory", "November 21, 2026") + (
            b'<a class="w-pagination-next" href="?posts_page=2"></a>'
        )
        next_page = card("last-eligible", "October 27, 2026") + card("old", "October 1, 2026")
        loader = Mock(side_effect=[first_page, next_page, feed([])])
        page = b"""
        <p>Subscribe</p><div class="text-rich-text-v2-blog-post w-richtext">
        <h2 id="loop">The loop</h2><p>Trace errors are inputs for the editors.</p>
        <img src="https://cdn.prod.website-files.com/team/loop.png" alt="Knowledge loop"></div>
        """
        rows, alerts = discover_editions(DAY, 30, loader, DEVELOPER_SOURCES)
        self.assertFalse(alerts)
        self.assertEqual([row.title for row in rows], ["knowledge-factory", "last-eligible"])
        self.assertEqual(
            loader.call_args_list[1].args[0], "https://www.langchain.com/blog?posts_page=2"
        )
        entry = rows[0]
        self.assertEqual((entry.url, entry.published), (url, date(2026, 11, 21)))
        self.assertEqual(
            extract(page), [("The loop", "loop", "Trace errors are inputs for the editors.")]
        )
        self.assertEqual(image_candidates(page, entry.url)[0].source_url, url + "#loop")

    def test_first_publication_date_and_as_of_version(self):
        data = feed(
            [
                ("2611.01234v1", "2026-11-10", "2026-11-10"),
                ("2611.01234v2", "2026-11-10", "2026-11-22"),
                ("2611.02222v2", "2026-11-12", "2026-11-26"),
                ("2610.00001v2", "2026-10-26", "2026-11-21"),
            ]
        )
        rows = arxiv_candidates(data, date(2026, 10, 27), DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].url, "https://arxiv.org/html/2611.01234v2")
        self.assertEqual(rows[0].published, date(2026, 11, 10))
        self.assertIn("202610270000+TO+202611252359", arxiv_query_url(DAY, 30))

    def test_partial_outages_preserve_other_source(self):
        blog = Source("Test", "https://example.org/", ("/",))
        page = (
            b'<article><h3><a href="/article">Agent research</a></h3>'
            b"<time>Nov 8, 2026</time></article>"
        )
        paper = feed([("2611.01234v1", "2026-11-10", "2026-11-10")])
        for replies, expected in [
            ([page, OSError("offline")], "Test"),
            ([b"<html>No posts</html>", paper], "arXiv"),
        ]:
            with self.subTest(source=expected):
                rows, warnings = discover_editions(DAY, 30, Mock(side_effect=replies), (blog,))
                self.assertEqual([a.source for a in rows], [expected])
                self.assertTrue(warnings)

    def test_paper_figure_links_to_exact_panel_and_keeps_caption(self):
        url = "https://arxiv.org/html/2611.01234v2"
        page = """
        <article><h2>Results</h2>
        <img src="/logo.png" alt="arXiv">
        <figure id="S2.F2"><img src="2611.01234v2/ablation.png" alt="Refer to caption">
          <figcaption>Figure 2. Held-out performance by model size.</figcaption></figure>
        <figure id="S2.F3"><img src="left.png"><img src="right.png">
          <figcaption>Separate panels.</figcaption></figure></article>
        """
        figs = image_candidates(page, url)
        self.assertEqual(len(figs), 1)
        self.assertEqual(figs[0].source_url, url + "#S2.F2")
        self.assertEqual(figs[0].asset_url, url + "/ablation.png")
        self.assertIn("Held-out performance", figs[0].caption)
