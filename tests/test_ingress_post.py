"""Regression tests for JSON POSTs forwarded through Home Assistant Ingress."""

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "diagnostic_hub"))
from app import handler_for


class IngressPostTests(unittest.TestCase):
    def setUp(self):
        self.hub = Mock()
        self.hub.create.return_value = {"id": "created"}
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            handler_for(None, development=True, hub=self.hub),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, body, *, chunked=False, content_type="application/json", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(conn.close)
        headers = dict(
            headers or {},
            **{
                "Content-Type": content_type,
                "X-Diagnostic-Hub": "1",
            },
        )
        data = [body[:19], body[19:]] if chunked else body
        conn.request(
            "POST",
            "/api/recordings",
            body=data,
            headers=headers,
            encode_chunked=chunked,
        )
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    def test_regular_content_length_post(self):
        request = {"source": "test"}
        status, result = self.post(json.dumps(request).encode())
        self.assertEqual(status, 200)
        self.assertEqual(result["id"], "created")
        self.hub.create.assert_called_once_with(request)

    def test_chunked_ingress_post_without_content_length(self):
        request = {"source": "test", "level": "TRACE"}
        status, result = self.post(json.dumps(request).encode(), chunked=True)
        self.assertEqual(status, 200)
        self.assertEqual(result["id"], "created")
        self.hub.create.assert_called_once_with(request)

    def test_chunked_body_over_limit_rejected(self):
        status, result = self.post(json.dumps({"payload": "a" * 4096}).encode(), chunked=True)
        self.assertEqual(status, 422)
        self.assertIn("4 KiB", result["error"])
        self.hub.create.assert_not_called()

    def test_content_type_validation_applies_to_chunked(self):
        status, result = self.post(b"{}", chunked=True, content_type="text/plain")
        self.assertEqual(status, 422)
        self.assertIn("application/json", result["error"])
        self.hub.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
