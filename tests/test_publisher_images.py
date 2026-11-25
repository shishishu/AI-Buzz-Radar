import base64
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from ai_buzz_radar.publisher_images import (
    ImageChoice,
    OriginalImage,
    image_candidates,
    image_catalog,
    raster_extension,
    save_original,
)

URL = "https://openai.com/index/technical-article"
CDN = "https://images.ctfassets.net"
ARTICLE = f"""<article>
<h2 id="results">Measured results</h2>
<figure><img src="{CDN}/plot.png" srcset="{CDN}/small.png 640w, {CDN}/large.png 1200w"
 alt="Throughput by input size"><figcaption>Median over five runs.</figcaption></figure>
<img src="https://external.example/a.png" alt="a">
<img src="http://openai.com/insecure.png" alt="b">
<img src="/author-avatar.png" alt="Author">
<img src="/icon.svg" alt="">
<h2>Keep reading</h2><img src="/related.png" alt="Unrelated topic"></article>"""
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvXYAAAAASUVORK5CYII="
)


class PublisherImageTest(unittest.TestCase):
    def test_candidates_keep_article_figures_source_and_relative_urls(self):
        images = image_candidates(ARTICLE, URL)
        self.assertEqual(len(images), 1)
        image = images[0]
        self.assertEqual(image.asset_url, CDN + "/large.png")
        self.assertEqual(image.source_url, URL + "#results")
        self.assertEqual(image_catalog(images)[0]["caption"], "Median over five runs.")
        relative = image_candidates('<article><img src="/a.png" alt="A diagram"></article>', URL)
        self.assertEqual(relative[0].asset_url, "https://openai.com/a.png")
        self.assertEqual(relative[0].source_url, URL)
        self.assertEqual(image_candidates(ARTICLE, "https://external.example/post"), [])

    def test_download_keeps_original_bytes_and_skips_invalid_assets(self):
        images = image_candidates(ARTICLE, URL)
        choice = ImageChoice(
            index=0, title="吞吐量", caption="五次运行的中位数。", alt="按输入大小比较吞吐量。"
        )
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            loader = Mock(return_value=PNG)
            self.assertIsNone(save_original(None, images, folder, loader))
            self.assertIsNone(
                save_original(choice.model_copy(update={"index": 1}), images, folder, loader)
            )
            loader.assert_not_called()
            loader.return_value = b"<!DOCTYPE html><title>unavailable</title>"
            self.assertIsNone(save_original(choice, images, folder, loader))
            loader.side_effect = OSError("unreachable")
            self.assertIsNone(save_original(choice, images, folder, loader))
            self.assertFalse((folder / "figures").exists())
            loader.side_effect = None
            loader.return_value = PNG
            result = save_original(choice, images, folder, loader)
            self.assertEqual(result.asset_url, images[0].asset_url)
            self.assertEqual(result.source_url, URL + "#results")
            saved = folder / "figures" / "originals" / result.filename
            self.assertEqual(saved.read_bytes(), PNG)
            saved.write_bytes(b"truncated")
            save_original(choice, images, folder, loader)
            self.assertEqual(saved.read_bytes(), PNG)
            with self.assertRaises(ValueError):
                OriginalImage.model_validate({**result.model_dump(), "filename": "../other.png"})

    def test_raster_headers_reject_truncation_and_oversize_data(self):
        self.assertEqual(raster_extension(PNG), "png")
        self.assertIsNone(raster_extension(PNG[:-3]))
        self.assertIsNone(raster_extension(b"<svg></svg>"))
        self.assertIsNone(raster_extension(PNG + bytes(4_000_000)))

    def test_paper_object_is_rasterized_with_publisher_source_and_digest(self):
        url = "https://arxiv.org/html/2611.00001v1"
        html = """<article><figure id="S4.F2">
          <object type="image/svg+xml" data="2611.00001v1/curve.svg"></object>
          <figcaption>Figure 2: Correct deliveries by row count.</figcaption>
        </figure></article>"""
        figures = image_candidates(html, url)
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0].source_url, url + "#S4.F2")
        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="150pt" height="75pt">'
            b'<rect width="80" height="20" fill="blue"/></svg>'
        )
        choice = ImageChoice(index=0, title="结果", caption="按行数比较", alt="曲线图")
        with tempfile.TemporaryDirectory() as tmp:
            output, audit = Path(tmp), {}
            original = save_original(choice, figures, output, lambda _: svg, audit=audit)
            rendered = (output / "figures" / "originals" / original.filename).read_bytes()
            self.assertEqual(raster_extension(rendered), "png")
            self.assertEqual(struct.unpack(">II", rendered[16:24]), (1400, 700))
            self.assertEqual(audit["sha256"], hashlib.sha256(rendered).hexdigest())
            self.assertEqual(audit["publisher_sha256"], hashlib.sha256(svg).hexdigest())
            self.assertEqual(audit["format"], "svg_to_png")
            for unsupported in (
                svg.replace(b"<rect", b'<image href="other.png"/><rect'),
                b"<html>not an SVG</html>",
            ):
                audit = {}
                failed = save_original(
                    choice, figures, output, Mock(return_value=unsupported), audit=audit
                )
                self.assertIsNone(failed)
                self.assertEqual(audit["status"], "unavailable")
                self.assertIn("reason", audit)

    def test_untitled_publisher_figure_offers_its_labeled_context(self):
        url = "https://www.langchain.com/blog/graph-study"
        cdn = "https://cdn.prod.website-files.com/123"
        html = f"""<div class="text-rich-text-v2-blog-post"><h2>Measured costs</h2>
          <figure><img src="{cdn}/123_Wiki%20and%20Graph%20results.png" alt=""></figure>
          <p>The graph cut median answer time.</p>
          <img src="{cdn}/unlabelled.png">
        </div>"""
        figures = image_candidates(html, url)
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0].source_url, url + "#:~:text=Measured%20costs")
        offered = image_catalog(figures)[0]
        self.assertEqual(offered["caption"], "")
        self.assertIn("Wiki and Graph results", offered["context"])
        self.assertIn("cut median answer time", offered["context"])
        with tempfile.TemporaryDirectory() as tmp:
            audit, loader = {}, Mock()
            self.assertIsNone(save_original(None, figures, Path(tmp), loader, audit=audit))
            self.assertEqual(audit["status"], "unavailable")
            self.assertEqual(audit["candidate_count"], 1)
            self.assertIn("成稿", audit["reason"])
            loader.assert_not_called()
