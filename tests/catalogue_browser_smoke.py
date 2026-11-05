"""Optional real-browser smoke, run ONLY on the dedicated host against test fixtures.

Usage: python tests/catalogue_browser_smoke.py http://127.0.0.1:8781/
Requires Playwright+Chromium in a separate test environment. Never target production.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    url = sys.argv[1]
    parsed = urlsplit(url)
    if parsed.hostname != "127.0.0.1" or parsed.port != 8781:
        raise SystemExit("Refusing non-test dashboard URL")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)

        def view(section):
            page.locator(f'.sidebar a[href="#{section}"]').click()

        page.locator("#password").fill("catalogue-browser-test")
        page.locator("#login-form button").click()
        expect(page.locator("#dashboard")).to_be_visible()
        expect(page.locator("#summary")).to_contain_text("Downloads: disabled")
        expect(page.locator("#execute")).to_be_disabled()
        view("media-tools")
        expect(page.locator("#queue-section")).not_to_be_visible()
        expect(page.locator('.sidebar a[href="#media-tools"]')).to_have_attribute("aria-current", "page")
        expect(page.locator("#media-download")).to_be_visible()
        with page.expect_download() as media_download:
            page.locator("#media-download").click()
        if media_download.value.suggested_filename != "media-release.pyz":
            raise RuntimeError("Unexpected standalone tool download")
        expect(page.locator("#media-root option")).to_have_count(1)
        page.locator("#media-browse").click()
        page.get_by_role("button", name="File: Film.2026.1080p.AMZN.mkv", exact=True).click()
        expect(page.get_by_label("Remove Font (kept by default): fixture-font.ttf", exact=True)).not_to_be_checked()
        page.get_by_label("Remove Tag COMMENT", exact=True).check()
        expect(page.locator("#media-inspection")).to_contain_text("mkvmerge v74.0.0")
        expect(page.locator("#media-identity")).to_contain_text("tt1234567")
        page.get_by_label("Container title", exact=True).fill("Reviewed live title")
        page.get_by_label("Track name for track 0", exact=True).fill("Reviewed video")
        page.get_by_label("Language (ISO/BCP47) for track 1", exact=True).fill("ta")
        expect(page.locator("#media-plan")).to_contain_text("Reviewed live title", timeout=15000)
        expect(page.locator("#media-plan")).to_contain_text("Reviewed video")
        expect(page.locator("#media-plan")).to_contain_text("Film.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-Kitsune.mkv")
        page.route("**/api/media/process", lambda route: route.fulfill(status=200, content_type="application/json", body='{"started":true}'))
        with page.expect_request("**/api/media/process") as process_click:
            page.locator("#media-process").click()
        if "confirmation" in process_click.value.post_data_json:
            raise RuntimeError("Single processing still requires typed confirmation")
        page.locator("#media-group").fill("CustomGroup")
        page.locator("#media-add-tag").click()
        page.get_by_label("New tag name", exact=True).fill("COMMENT")
        page.get_by_label("New tag value", exact=True).fill("Fixture tag")
        page.locator("#media-save-preferences").click()
        expect(page.locator("#media-message")).to_contain_text("preferences saved")
        page.get_by_label("Select Film.2026.1080p.AMZN.mkv", exact=True).check()
        page.locator("#media-batch-match").click()
        # Prepare now matches and previews automatically; assert the stable
        # prepared state, not a transient message replaced by live preview.
        expect(page.locator("#media-batch-process")).to_be_enabled(timeout=15000)
        expect(page.locator("#media-batch-rows")).to_contain_text("Film.2026.1080p")
        page.route("**/api/media/batch-process", lambda route: route.fulfill(status=200, content_type="application/json", body='{"started":true}'))
        with page.expect_request("**/api/media/batch-process") as batch_click:
            page.locator("#media-batch-process").click()
        if "confirmation" in batch_click.value.post_data_json:
            raise RuntimeError("Batch processing still requires typed confirmation")
        view("saved-lists")
        expect(page.locator("#media-tools")).not_to_be_visible()
        page.locator("#lists-scope").select_option("all")
        page.locator("#lists-title").fill("Saved browser fixture")
        page.locator("#lists-save").click()
        expect(page.locator("#lists-current")).to_contain_text("61 results")
        expect(page.locator("#lists-results tr")).to_have_count(50)
        page.locator("#lists-select-page").click()
        page.locator("#lists-review-note").fill("Manual-upload shortlist fixture")
        page.locator("#lists-review-save").click()
        expect(page.locator("#lists-message")).to_contain_text("checklist saved")
        expect(page.locator("#lists-results")).to_contain_text("Manual-upload shortlist fixture")
        with page.expect_download() as checklist:
            page.locator("#lists-review-export").click()
        if not checklist.value.suggested_filename.startswith("manual-upload-review-"):
            raise RuntimeError("Manual checklist export unavailable")
        page.locator("#lists-next").click()
        expect(page.locator("#lists-results tr")).to_have_count(11)
        with page.expect_download() as saved_export:
            page.locator("#lists-export").click()
        if not saved_export.value.suggested_filename.endswith(".json"):
            raise RuntimeError("Missing saved-list JSON export")
        view("queue-section")
        expect(page.locator("#page-label")).to_contain_text("Page 1 of 3")
        page.locator("#page-next").click()
        expect(page.locator("#page-label")).to_contain_text("Page 2 of 3")
        page.locator("#queue-search").fill("Fixture 059")
        expect(page.locator("#queue-count")).to_have_text("1")
        expect(page.locator("#queue")).to_contain_text("Fixture 059")
        page.locator("#queue-search").fill("no-such-fixture")
        expect(page.locator("#queue")).to_contain_text("No matching titles")
        page.locator("#queue-search").fill("<img")
        expect(page.locator("#queue-count")).to_have_text("1")
        expect(page.locator("#queue")).to_contain_text("<img src=x onerror=alert(1)>")
        if page.locator("#queue img").count():
            raise RuntimeError("Queue rendered unsafe HTML")
        page.locator(".job-action").click()
        expect(page.locator("#recheck-dialog")).to_be_visible()
        page.locator("#recheck-form button[type=submit]").click()
        expect(page.locator("#recheck-dialog")).not_to_be_visible()
        expect(page.locator("#message")).to_contain_text("No API requests or downloads started")
        page.locator("#queue-search").fill("")
        expect(page.locator("#queue-count")).to_have_text("61")
        view("overview")
        page.locator("#health").click()
        expect(page.locator("#health-result")).to_contain_text("3.10.16", timeout=15000)
        view("settings-section")
        page.locator("#search-preset-name").fill("Browser saved search")
        page.locator("#search-preset-save").click()
        expect(page.locator("#message")).to_contain_text("preset saved")
        page.locator("#search-preset-load").click()
        expect(page.locator("#message")).to_contain_text("Preset loaded")
        page.locator("#preset-rare").click()
        expect(page.locator("#message")).to_contain_text("staged only")
        expect(page.locator("#max_imdb_votes")).to_have_value("5000")
        expect(page.locator("#discovery_start_offset")).to_have_value("0")
        page.reload()
        expect(page.locator("#max_imdb_votes")).to_have_value("0")
        page.locator("#preset-rare").click()
        page.locator("#countries").fill("JP")
        page.locator("#original-languages").fill("JA, ta")
        page.locator("#video-mode").select_option("hdr10")
        page.locator("#daily_limit").fill("3")
        page.locator("#media-tv").check()
        page.locator("#eligibility").select_option("missing_or_free_slot")
        page.locator("#save-settings").click()
        expect(page.locator("#message")).to_contain_text("Settings saved")
        page.reload()
        expect(page.locator("#countries")).to_have_value("JP")
        expect(page.locator("#original-languages")).to_have_value("ja, ta")
        expect(page.locator("#video-mode")).to_have_value("hdr10")
        expect(page.locator("#daily_limit")).to_have_value("3")
        expect(page.locator("#max_imdb_votes")).to_have_value("5000")
        expect(page.locator("#discovery_start_offset")).to_have_value("0")
        expect(page.locator("#media-tv")).to_be_checked()
        expect(page.locator("#eligibility")).to_have_value("missing_or_free_slot")
        artifacts = Path.cwd() / "browser-artifacts"
        artifacts.mkdir(exist_ok=True, mode=0o700)
        page.screenshot(path=str(artifacts / "catalogue-desktop.png"), full_page=True)
        captured = []

        def intercept(route):
            captured.append(route.request.post_data_json)
            route.fulfill(status=202, content_type="application/json", body=json.dumps({"ok": True}))

        # Browser buttons are tested without allowing any real runner/API invocation.
        page.route("**/api/run", intercept)
        view("queue-section")
        expect(page.locator("#quick-source-netflix")).to_be_checked()
        expect(page.locator("#quick-region-netflix")).to_have_text("US")
        page.locator("#search-production-country").fill("NZ")
        expect(page.locator("#search-scope")).to_contain_text("Film production: NZ")
        expect(page.locator("#search-scope")).to_contain_text("Netflix US")
        page.locator("#search-any-production").click()
        expect(page.locator("#search-production-country")).to_have_value("")
        page.locator("#search-production-country").fill("JP")
        page.locator("#queue-only").check()
        page.locator("#plan").click()
        expect(page.locator("#message")).to_contain_text("Dry-run started")
        if captured != [{"mode": "plan", "queue_only": True}]:
            raise RuntimeError("Incorrect dry-run request")
        view("settings-section")
        page.locator("#allow-downloads").check()
        page.locator("#save-settings").click()
        expect(page.locator("#summary")).to_contain_text("Downloads: enabled")
        view("queue-section")
        page.locator("#execute").click()
        expect(page.locator("#message")).to_contain_text("Execution requested")
        if captured[-1] != {"mode": "execute", "queue_only": True, "confirmation": "ENABLE DOWNLOADS"}:
            raise RuntimeError("Incorrect execution request")
        page.locator("#pause").click()
        expect(page.locator("#message")).to_contain_text("Schedule paused")
        page.set_viewport_size({"width": 390, "height": 844})
        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
            raise RuntimeError("Mobile layout overflows viewport")
        page.screenshot(path=str(artifacts / "catalogue-mobile.png"), full_page=True)
        view("media-tools")
        expect(page.locator("#media-group")).to_have_value("CustomGroup")
        expect(page.locator("#media-download")).to_be_visible()
        expect(page.locator("#queue-section")).not_to_be_visible()
        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
            raise RuntimeError("Mobile media tab overflows viewport")
        page.screenshot(path=str(artifacts / "catalogue-media-mobile.png"), full_page=True)
        page.locator("#logout").click()
        expect(page.locator("#login-panel")).to_be_visible()
        if errors:
            raise RuntimeError("Browser JavaScript errors: " + "; ".join(errors))
        browser.close()
    print("Browser smoke passed: login, pagination, search, safe rendering, queue recovery, persisted TV/slot settings, mocked health/controls, logout, responsive screenshots")


if __name__ == "__main__":
    main()
