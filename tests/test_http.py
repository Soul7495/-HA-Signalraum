import gzip
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "diagnostic_hub"))
from app import handler_for
from collector import Collector, DEFAULTS
from evcc import EvccAdapter, MAX_RESPONSE


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.collector = Collector(dict(DEFAULTS), Path(self.temp.name))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.collector, development=True))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}))

    def capture(self):
        with patch.object(self.collector, "fetch", return_value=["before", "ERROR timeout"]):
            self.collector.poll()
        return self.collector.list_cases()["items"][0]["filename"]

    def test_ingress_base_without_trailing_slash(self):
        with self.get("/", {"X-Ingress-Path": "/api/hassio_ingress/test-token"}) as response:
            self.assertIn(b'<base href="/api/hassio_ingress/test-token/">', response.read())
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    def test_download_original_and_mobile_friendly_text(self):
        filename = self.capture()
        with self.get("/api/download/" + filename) as response:
            self.assertIn("attachment;", response.headers["Content-Disposition"])
            self.assertNotIn("Content-Encoding", response.headers)
            content = response.read()
            self.assertEqual(len(content), int(response.headers["Content-Length"]))
            self.assertEqual(json.loads(gzip.decompress(content))["trigger"], "ERROR timeout")
        with self.get("/api/download/" + filename + "?format=txt") as response:
            self.assertIn(".txt", response.headers["Content-Disposition"])
            self.assertIn("before", response.read().decode())

    def test_download_survives_concurrent_retention(self):
        filename = self.capture()
        response = self.get("/api/download/" + filename)
        with self.collector.lock:
            self.collector.remove(self.collector.root / filename)
        content = response.read()
        response.close()
        self.assertEqual(json.loads(gzip.decompress(content))["trigger"], "ERROR timeout")

    def test_traversal_symlink_and_missing_rejected(self):
        target = Path(self.temp.name) / "private.json"
        target.write_text("secret")
        (self.collector.root / "link.json").symlink_to(target)
        for path in ("/api/download/%2E%2E%2Fprivate.json", "/api/download/link.json", "/api/download/missing.json"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get(path)
            self.assertEqual(error.exception.code, 404)

    def test_ingress_authorization_rejects_direct_client_and_spoofed_headers(self):
        self.server.RequestHandlerClass = handler_for(self.collector)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get("/api/status", {"X-Forwarded-For": "172.30.32.2", "X-Ingress-Path": "/foo"})
        self.assertEqual(error.exception.code, 403)

    def test_api_status_and_page(self):
        self.capture()
        with self.get("/api/status") as response:
            self.assertEqual(json.load(response)["count"], 1)
        with self.get("/api/incidents?page=999") as response:
            item = json.load(response)
            self.assertEqual(item["page"], 1)
            self.assertEqual(item["items"][0]["repeats"], 1)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.payload = b"[]"
        self.status = 200
        self.content_type = "application/json"
        outer = self

        class EvccMock(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(outer.status)
                self.send_header("Content-Type", outer.content_type)
                if outer.status == 302:
                    self.send_header("Location", "/not-log")
                self.end_headers()
                self.wfile.write(outer.payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), EvccMock)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        config = dict(DEFAULTS, evcc_url=f"http://127.0.0.1:{self.server.server_port}", evcc_api_key="private-key")
        self.adapter = EvccAdapter(config)

    def test_stable_json_format_and_get_only(self):
        self.payload = json.dumps(["INFO ready\n", "ERROR token=private-key\n"]).encode()
        lines = self.adapter.fetch()
        self.assertEqual(lines[0], "INFO ready")
        self.assertNotIn("private-key", lines[1])
        self.assertEqual(self.requests, [("/api/system/log?level=TRACE&count=10000", "Bearer private-key")])

    def test_null_and_plain_text(self):
        self.payload = b"null"
        self.assertEqual(self.adapter.fetch(), [])
        self.payload = b"INFO ready\nERROR timeout\n"
        self.content_type = "text/plain"
        self.assertEqual(len(self.adapter.fetch()), 2)

    def test_oversize_html_invalid_json_and_auth(self):
        for content, kind in (
            (b"x" * (MAX_RESPONSE + 1), "text/plain"),
            (b"<html>login</html>", "text/html"),
            (b'{"bad":true}', "application/json"),
        ):
            self.payload, self.content_type = content, kind
            with self.assertRaises(ValueError):
                self.adapter.fetch()
        self.status = 401
        with self.assertRaises(urllib.error.HTTPError):
            self.adapter.fetch()

    def test_redirect_not_followed(self):
        self.status = 302
        with self.assertRaises(urllib.error.HTTPError):
            self.adapter.fetch()
        self.assertEqual(len(self.requests), 1)


if __name__ == "__main__":
    unittest.main()
