"""Real Chromium checks behind a local, path-stripping Ingress simulation."""

import gzip
import json
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "diagnostic_hub"))
from app import handler_for  # noqa: E402
from collector import Collector, DEFAULTS  # noqa: E402

PREFIX = "/api/hassio_ingress/test-session"


def main():
    with tempfile.TemporaryDirectory() as temp:
        collector = Collector(dict(DEFAULTS), Path(temp))
        backend = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(collector, development=True))

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if not self.path.startswith(PREFIX):
                    self.send_error(404)
                    return
                path = self.path[len(PREFIX) :] or "/"
                if path.startswith("?"):
                    path = "/" + path
                req = urllib.request.Request(
                    f"http://127.0.0.1:{backend.server_port}" + path, headers={"X-Ingress-Path": PREFIX}
                )
                with urllib.request.urlopen(req) as result:
                    self.send_response(result.status)
                    for name, value in result.headers.items():
                        if name.lower() not in ("server", "date", "connection"):
                            self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(result.read())

        proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        for server in (backend, proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{proxy.server_port}" + PREFIX  # deliberately no slash
        report = {"environment": "Chromium + local Ingress proxy; not Home Assistant Android app", "checks": []}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1100}, accept_downloads=True, reduced_motion="reduce"
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url)
                page.get_by_text("Noch kein Diagnosefall gespeichert.", exact=False).wait_for()
                report["checks"].append("empty state and base prefix without trailing slash")
                with patch.object(collector, "fetch", return_value=["INFO ready", "[rct] ERROR connection timeout"]):
                    collector.poll()
                page.get_by_role("button", name="Aktualisieren").click()
                page.get_by_role("heading", name="RCT Power", exact=True).wait_for()
                with page.expect_download() as download:
                    page.get_by_role("link", name="Text herunterladen").click()
                text_download = download.value
                text_download.save_as(str(Path(temp) / "download.txt"))
                assert "[rct] ERROR connection timeout" in (Path(temp) / "download.txt").read_text()
                with page.expect_download() as download:
                    page.get_by_role("link", name="Original", exact=True).click()
                archive = Path(temp) / "download.json.gz"
                download.value.save_as(str(archive))
                assert json.loads(gzip.decompress(archive.read_bytes()))["repeats"] == 1
                report["checks"].append("desktop text and gzip downloads preserve payload")
                page.get_by_text("Sicherungsdetails", exact=True).click()
                assert page.locator("details").first.get_attribute("open") is not None
                page.keyboard.press("Tab")
                focused = page.evaluate("document.activeElement.tagName")
                assert focused in ("A", "BUTTON", "SUMMARY")
                assert page.evaluate("getComputedStyle(document.documentElement).scrollbarColor") != "auto"
                report["checks"].append("details keyboard navigation and scrollbar baseline")
                page.screenshot(path=str(ROOT / "reports" / "desktop.png"), full_page=True)
                # Slow loading leaves refresh disabled; unavailable requests show stale warning.
                page.route("**/api/status", lambda route: route.fulfill(status=503, body="unavailable"))
                page.get_by_role("button", name="Aktualisieren").click()
                page.get_by_role("alert").filter(has_text="Verbindung zur Oberfläche unterbrochen").wait_for()
                assert page.get_by_role("button", name="Aktualisieren").is_enabled()
                page.unroute("**/api/status")
                page.get_by_role("button", name="Aktualisieren").click()
                page.wait_for_function("() => document.querySelector('#error').hidden")
                report["checks"].append("API failure, retained cases, recovery")
                for index in range(22):
                    with patch.object(collector, "fetch", return_value=[f"ERROR failure {index}"]):
                        collector.poll()
                page.get_by_role("button", name="Aktualisieren").click()
                page.wait_for_function("() => document.querySelectorAll('.case').length === 20")
                page.get_by_role("button", name="Weiter").click()
                page.get_by_text("Seite 2 von 2", exact=False).wait_for()
                assert "page=2" in page.url
                report["checks"].append("bounded pagination and URL state")
                mobile = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                    has_touch=True,
                    accept_downloads=True,
                    reduced_motion="reduce",
                )
                narrow = mobile.new_page()
                narrow.goto(url)
                narrow.get_by_role("link", name="Text herunterladen").first.wait_for()
                assert narrow.evaluate("document.documentElement.scrollWidth <= innerWidth")
                with narrow.expect_download() as download:
                    narrow.get_by_role("link", name="Text herunterladen").first.click()
                assert download.value.suggested_filename.endswith(".txt")
                assert narrow.get_by_role("link", name="Text herunterladen").first.bounding_box()["height"] >= 44
                narrow.screenshot(path=str(ROOT / "reports" / "mobile.png"), full_page=True)
                report["checks"].append("390px touch viewport, no horizontal overflow, text download")
                assert not errors, errors
                report["console_errors"] = errors
                browser.close()
        finally:
            for server in (proxy, backend):
                server.shutdown()
                server.server_close()
        (ROOT / "reports" / "browser.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
