"""Real Chromium checks behind a local, path-stripping Ingress simulation."""

import gzip
import json
import shutil
import time
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
from recordings import Recordings  # noqa: E402
from sources import Sources  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from test_recordings import FakeSupervisor  # noqa: E402

PREFIX = "/api/hassio_ingress/test-session"


def main():
    compatibility = "--legacy-webview" in sys.argv
    with tempfile.TemporaryDirectory() as temp:
        collector = Collector(dict(DEFAULTS), Path(temp))
        stamp = [time.time()]
        fake = FakeSupervisor()
        source_registry = Sources(dict(DEFAULTS), fake, clock=lambda: stamp[0])
        hub = Recordings(dict(DEFAULTS), collector, source_registry, clock=lambda: stamp[0])
        backend = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(collector, development=True, hub=hub))

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.forward()

            def do_GET(self):
                self.forward()

            def forward(self):
                if not self.path.startswith(PREFIX):
                    self.send_error(404)
                    return
                path = self.path[len(PREFIX) :] or "/"
                if path.startswith("?"):
                    path = "/" + path
                req = urllib.request.Request(
                    f"http://127.0.0.1:{backend.server_port}" + path,
                    data=self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    if self.command == "POST"
                    else None,
                    headers={
                        "X-Ingress-Path": PREFIX,
                        "Content-Type": "application/json",
                        "X-Diagnostic-Hub": self.headers.get("X-Diagnostic-Hub", ""),
                    },
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
                launch = dict(headless=True, args=["--no-sandbox"])
                if not Path(playwright.chromium.executable_path).exists() and shutil.which("chromium"):
                    launch["executable_path"] = shutil.which("chromium")
                browser = playwright.chromium.launch(**launch)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1100}, accept_downloads=True, reduced_motion="reduce"
                )

                def prepare_context(ctx):
                    if compatibility:
                        ctx.add_init_script(
                            "Object.defineProperty(AbortSignal,'any',{value:undefined});Object.defineProperty(AbortSignal,'timeout',{value:undefined});"
                        )
                        origin = f"http://ha-test.local:{proxy.server_port}"
                        ctx.route(
                            origin + "/**",
                            lambda route: route.fulfill(
                                response=route.fetch(
                                    url=route.request.url.replace(origin, f"http://127.0.0.1:{proxy.server_port}")
                                )
                            ),
                        )

                prepare_context(context)
                browser_url = url.replace("127.0.0.1", "ha-test.local") if compatibility else url
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(browser_url)
                page.get_by_text("Noch keine manuelle Aufnahme.", exact=False).wait_for()
                if compatibility:
                    assert page.evaluate(
                        "!window.isSecureContext && typeof crypto.randomUUID === 'undefined' && typeof AbortSignal.any === 'undefined'"
                    )
                    report["checks"].append(
                        "real non-secure HTTP origin and missing randomUUID/AbortSignal.any/timeout"
                    )
                page.get_by_role("button", name="Aufnahme starten", exact=True).click()
                page.wait_for_function(
                    "() => document.querySelector('#record-app').getAttribute('aria-invalid') === 'true'"
                )
                assert page.locator("#record-app").evaluate("(el) => el === document.activeElement")
                page.locator("#record-app").select_option("addon:local_evcc")
                page.locator("#record-source").select_option("addon:local_evcc")
                page.locator("#record-level").select_option("DEBUG")
                if compatibility:
                    page.get_by_role("button", name="Aufnahme starten", exact=True).click()
                    page.get_by_text("Aufnahme gestartet:", exact=False).wait_for()
                    page.locator("#recordings-list").get_by_role("button", name="Aufnahme beenden").click()
                    page.get_by_text("Aufnahme beendet. Bisherige Daten bleiben erhalten.", exact=True).wait_for()
                    assert not errors, errors
                    report["console_errors"] = errors
                    report["checks"].append(
                        "HTTP startup, discovered app selection, validation, DEBUG profile start and stop; downloads covered separately in standard browser suite"
                    )
                    report["limitations"] = [
                        "HTTP origin is simulated by request interception; intercepted Chromium attachment downloads cancel in this harness and are not asserted here",
                        "Not a real Home Assistant or Android test",
                    ]
                    (ROOT / "reports" / "browser-legacy.json").write_text(json.dumps(report, indent=2) + "\n")
                    print(json.dumps(report, indent=2))
                    browser.close()
                    return

                page.locator("#record-level").focus()
                page.keyboard.press("Alt+ArrowDown")
                page.keyboard.press("Escape")
                page.get_by_role("button", name="Aktuelle Logs abrufen", exact=True).click()
                page.locator("#preview-panel[open]").wait_for()
                with page.expect_download() as saved:
                    page.get_by_role("link", name="Gesamten Puffer herunterladen").click()
                assert saved.value.suggested_filename.endswith(".txt")
                page.get_by_role("button", name="Aufnahme starten", exact=True).click()
                page.get_by_text("Aufnahme gestartet:", exact=False).wait_for()
                hub.tick()
                stamp[0] += 15
                fake.lines += ["TRACE omitted", "DEBUG synthetic recording"]
                hub.tick()
                page.get_by_role("button", name="Neu erkennen").click()
                page.wait_for_function(
                    "() => document.querySelector('#recordings-list').textContent.includes('1 Zeile')"
                )
                manual = page.locator("#recordings-list .record-card").first
                with page.expect_download() as saved:
                    manual.get_by_role("link", name="Text herunterladen").click()
                saved.value.save_as(str(Path(temp) / "manual.txt"))
                text = (Path(temp) / "manual.txt").read_text()
                assert "DEBUG synthetic recording" in text and "TRACE omitted" not in text
                assert hub.page()["items"][0]["deadline"] - hub.page()["items"][0]["started"] == 43200
                manual.get_by_role("button", name="Aufnahme beenden").click()
                page.get_by_text("Aufnahme beendet. Bisherige Daten bleiben erhalten.", exact=True).wait_for()
                report["checks"].append(
                    "manual 12-hour DEBUG profile: discovery, validation/focus, native select, preview download, start, filtered recording download, stop"
                )
                page.locator(".legacy > summary").click()
                page.get_by_text("Noch kein Diagnosefall gespeichert.", exact=False).wait_for()
                report["checks"].append("empty state and base prefix without trailing slash")
                with patch.object(collector, "fetch", return_value=["INFO ready", "[rct] ERROR connection timeout"]):
                    collector.poll()
                page.get_by_role("button", name="Aktualisieren").click()
                page.get_by_role("heading", name="RCT Power", exact=True).wait_for()
                with page.expect_download() as download:
                    page.locator("#list").get_by_role("link", name="Text herunterladen").click()
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
                assert page.locator(".case details").first.get_attribute("open") is not None
                page.keyboard.press("Tab")
                focused = page.evaluate("document.activeElement.tagName")
                assert focused in ("A", "BUTTON", "SUMMARY")
                assert page.evaluate("getComputedStyle(document.documentElement).scrollbarColor") != "auto"
                report["checks"].append("details keyboard navigation and scrollbar baseline")
                page.locator(".legacy > summary").click()
                page.screenshot(path=str(ROOT / "reports" / "desktop.png"), full_page=True)
                page.locator(".legacy > summary").click()
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
                page.wait_for_function("() => document.querySelectorAll('#list .case').length === 20")
                page.locator("#next").click()
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
                prepare_context(mobile)
                narrow = mobile.new_page()
                narrow.goto(browser_url)
                narrow.locator("#recordings-list").get_by_role("link", name="Text herunterladen").first.wait_for()
                narrow.locator("#record-app").select_option("addon:local_zigbee2mqtt")
                narrow.locator("#record-source").select_option("addon:local_zigbee2mqtt")
                narrow.locator("#record-level").focus()
                narrow.keyboard.press("ArrowDown")
                narrow.keyboard.press("Escape")
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
            hub.close()
            for server in (proxy, backend):
                server.shutdown()
                server.server_close()
        (ROOT / "reports" / ("browser-legacy.json" if compatibility else "browser.json")).write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
