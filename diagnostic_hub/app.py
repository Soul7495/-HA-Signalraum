"""Home Assistant Ingress server for Diagnostic Hub."""

import gzip
import json
import logging
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from collector import Collector, settings

STATIC = Path(__file__).parent / "static"


def handler_for(collector, development=False):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, format, *args):
            # Do not expose private filenames, ingress tokens or query values.
            pass

        def do_GET(self):
            if not development and self.client_address[0] != "172.30.32.2":
                self.reply(b"Nur Home Assistant Ingress ist zugelassen.", "text/plain; charset=utf-8", 403)
                return
            try:
                self.dispatch()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except (OSError, ValueError, EOFError):
                self.reply(b"Diagnoseblock nicht lesbar. Bitte erneut versuchen.", "text/plain; charset=utf-8", 503)

        def dispatch(self):
            url = urllib.parse.urlsplit(self.path)
            path = url.path
            if path == "/api/status":
                self.reply(json.dumps(collector.status()).encode(), "application/json")
            elif path == "/api/incidents":
                try:
                    page = int(urllib.parse.parse_qs(url.query).get("page", ["1"])[0])
                except ValueError:
                    page = 1
                self.reply(json.dumps(collector.list_cases(page)).encode(), "application/json")
            elif path.startswith("/api/download/"):
                name = urllib.parse.unquote(path[len("/api/download/") :])
                if not re.fullmatch(r"[A-Za-z0-9_-]+\.(?:json|log)(?:\.gz)?", name):
                    self.reply(b"Datei nicht gefunden.", "text/plain", 404)
                    return
                # Existence, read and prune share one lock. The copied response
                # survives atomic replacement/deletion without pinning disk files.
                with collector.lock:
                    target = collector.root / name
                    if not target.is_file() or target.is_symlink():
                        self.reply(b"Datei nicht gefunden.", "text/plain", 404)
                        return
                    if urllib.parse.parse_qs(url.query).get("format") == ["txt"]:
                        if ".json" in name:
                            item = collector.read_case(target)
                            metadata = {k: v for k, v in item.items() if k not in ("pre_log", "post_log")}
                            content = (
                                json.dumps(metadata, ensure_ascii=False, indent=2)
                                + "\n\n--- Vorgeschichte ---\n"
                                + "\n".join(item["pre_log"])
                                + "\n\n--- Nachlauf ---\n"
                                + "\n".join(item["post_log"])
                                + "\n"
                            ).encode()
                        else:
                            raw = target.read_bytes()
                            content = gzip.decompress(raw) if name.endswith(".gz") else raw
                        download_name = name.split(".")[0] + ".txt"
                        content_type = "application/octet-stream"
                    else:
                        content = target.read_bytes()
                        download_name = name
                        content_type = "application/gzip" if name.endswith(".gz") else "application/octet-stream"
                self.reply(content, content_type, attachment=download_name)
            elif path in ("/", ""):
                # Supervisor supplies the complete Ingress prefix. Never derive it
                # by dropping the last URL segment (fails without trailing slash).
                base = self.headers.get("X-Ingress-Path", "").rstrip("/") + "/"
                if not re.fullmatch(r"/[A-Za-z0-9_/-]*", base):
                    base = "/"
                page = (STATIC / "index.html").read_text().replace("__BASE__", base)
                self.reply(page.encode(), "text/html; charset=utf-8")
            elif path in ("/static/app.js", "/static/style.css"):
                target = STATIC / path.split("/")[-1]
                self.reply(
                    target.read_bytes(),
                    "text/javascript; charset=utf-8" if target.suffix == ".js" else "text/css; charset=utf-8",
                )
            else:
                self.reply(b"Seite nicht gefunden.", "text/plain; charset=utf-8", 404)

        def reply(self, data, content_type, status=200, attachment=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'self'; object-src 'none'",
            )
            if attachment:
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{attachment}"; filename*=UTF-8\x27\x27{attachment}'
                )
            self.end_headers()
            self.wfile.write(data)

    return Handler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collector = Collector(settings())
    threading.Thread(target=collector.run, daemon=True).start()
    development = os.environ.get("DIAGNOSTIC_HUB_DEV") == "1"
    server = ThreadingHTTPServer(("127.0.0.1" if development else "0.0.0.0", 8099), handler_for(collector, development))
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        collector.stop.set()
        server.server_close()
