"""Check disclosure focus after real pointer, keyboard and zoom interactions."""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import Locator, expect, sync_playwright

from ai_buzz_radar.editions import Edition, publish


def render_bilingual_fixture(folder: Path):
    examples = Path(__file__).resolve().parents[2] / "examples"
    edition = Edition.model_validate_json((examples / "editions/2026-11-25.json").read_bytes())
    (folder / "figures").symlink_to(examples / "figures", target_is_directory=True)
    publish(folder, [edition])
    return (folder / "index.html").as_uri()


def expect_no_box(summary: Locator):
    expect(summary).to_have_css("outline-style", "none")
    expect(summary).to_have_css("border-top-width", "0px")
    expect(summary).to_have_css("box-shadow", "none")


def check_page(page, *, touch, english):
    card = page.locator("article").first
    summary = card.locator("summary")
    details = card.locator("details")
    title = card.locator("h2")
    hit = Locator.tap if touch else Locator.click

    if english:
        hit(page.get_by_role("button", name="English", exact=True))
    label = "Read more" if english else "展开全文"
    expect(summary).to_have_accessible_name(label)
    for target in (title, summary):
        for _ in range(2):
            hit(target)
            expect(details).to_have_js_property("open", True)
            expect_no_box(summary)
            hit(target)
            expect(details).to_have_js_property("open", False)
            expect_no_box(summary)

    hit(title)
    image = card.locator(".enlarge-image")
    hit(image)
    dialog = page.locator("dialog")
    expect(dialog).to_be_visible()
    hit(dialog.locator("button[autofocus]"))
    expect(dialog).not_to_be_visible()
    expect(details).to_have_js_property("open", True)
    hit(card.locator(".close-card"))
    expect(summary).to_be_focused()
    expect_no_box(summary)

    # Return through normal tab order after pointer use. The visible text itself
    # marks keyboard focus, including after a keyboard-activated return from the end.
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    expect(summary).to_be_focused()
    for key, opened in (("Enter", True), ("Space", False), ("Enter", True)):
        page.keyboard.press(key)
        expect(details).to_have_js_property("open", opened)
        expect(summary.locator("span:visible")).to_have_css("text-decoration-style", "double")
        expect_no_box(summary)
    card.locator(".close-card").focus()
    page.keyboard.press("Enter")
    expect(summary).to_be_focused()
    expect(summary).to_have_accessible_name(label)
    expect(summary.locator("span:visible")).to_have_css("text-decoration-style", "double")
    expect_no_box(summary)

    if touch:
        expect(summary).to_have_css("-webkit-tap-highlight-color", "rgba(0, 0, 0, 0)")
        cdp = page.context.new_cdp_session(page)
        for factor in (2, 1):
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": factor})
            expect_no_box(summary)
        cdp.detach()


if __name__ == "__main__":
    with TemporaryDirectory() as temp, sync_playwright() as playwright:
        url = sys.argv[1] if len(sys.argv) > 1 else render_bilingual_fixture(Path(temp))
        browser = playwright.chromium.launch()
        for width in (320, 390, 1280):
            touch = width < 500
            for english in (False, True):
                page = browser.new_page(
                    viewport={"width": width, "height": 844}, is_mobile=touch, has_touch=touch
                )
                page.goto(url)
                check_page(page, touch=touch, english=english)
                page.close()
                print(f"Passed at {width}px, {'en' if english else 'zh'}", flush=True)
        browser.close()
