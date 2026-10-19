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
from recordings import Recordings
from sources import Sources, filtered, readable_error
from version import __version__

STATIC = Path(__file__).parent / "static"


def handler_for(collector, development=False, hub=None):
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

        def do_POST(self):
            if (not development and self.client_address[0] != "172.30.32.2") or self.headers.get(
                "X-Diagnostic-Hub"
            ) != "1":
                self.reply(b"Zugriff abgewiesen.", "text/plain", 403)
                return
            if hub is None:
                self.reply(b"Aufnahmen nicht verfuegbar.", "text/plain", 503)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON-Anfrage mit maximal 4 KiB erforderlich.")
                data = json.loads(self.rfile.read(size))
                path = urllib.parse.urlsplit(self.path).path
                if path == "/api/recordings":
                    result = hub.create(data)
                elif re.fullmatch(r"/api/recordings/[a-f0-9]{32}/stop", path):
                    result = hub.finish(path.split("/")[3])
                else:
                    self.reply(b"Route nicht gefunden.", "text/plain", 404)
                    return
                self.reply(json.dumps(result).encode(), "application/json")
            except (ValueError, TypeError) as exc:
                message = str(exc) if isinstance(exc, ValueError) else "Ungueltige Aufnahmeparameter."
                self.reply(json.dumps({"error": message}).encode(), "application/json", 422)
            except KeyError:
                self.reply(b'{"error":"Aufnahme nicht gefunden."}', "application/json", 404)
            except Exception:
                self.reply(
                    b'{"error":"Aufnahme konnte nicht gespeichert werden. Status vor erneutem Start pruefen."}',
                    "application/json",
                    503,
                )

        def dispatch(self):
            url = urllib.parse.urlsplit(self.path)
            path = url.path
            if hub is not None and path == "/api/hub":
                self.reply(json.dumps(dict(hub.summary(), version=__version__)).encode(), "application/json")
            elif hub is not None and path == "/api/diagnostics":
                hub.sources.discover(force=True)
                data = dict(hub.sources.diagnostics(), version=__version__)
                self.reply(
                    json.dumps(data, ensure_ascii=False, indent=2).encode(),
                    "application/json",
                    attachment="diagnostic-hub-status.json",
                )
            elif hub is not None and path == "/api/sources":
                self.reply(
                    json.dumps(
                        hub.sources.discover(force=urllib.parse.parse_qs(url.query).get("refresh") == ["1"])
                    ).encode(),
                    "application/json",
                )
            elif hub is not None and path == "/api/recordings":
                query = urllib.parse.parse_qs(url.query)
                try:
                    page = int(query.get("page", ["1"])[0])
                except ValueError:
                    page = 1
                self.reply(json.dumps(hub.page(page)).encode(), "application/json")
            elif hub is not None and re.fullmatch(r"/api/recordings/[a-f0-9]{32}/download", path):
                try:
                    content = hub.export(path.split("/")[3])
                except KeyError:
                    self.reply(b"Aufnahme nicht gefunden.", "text/plain", 404)
                    return
                name = "aufnahme-" + path.split("/")[3] + ".txt"
                if urllib.parse.parse_qs(url.query).get("gzip") == ["1"]:
                    content = gzip.compress(content, mtime=0)
                    name += ".gz"
                self.reply(
                    content, "application/gzip" if name.endswith(".gz") else "application/octet-stream", attachment=name
                )
            elif hub is not None and path == "/api/snapshot":
                query = urllib.parse.parse_qs(url.query)
                try:
                    source = query.get("source", [""])[0]
                    level = query.get("level", ["TRACE"])[0]
                    content = (
                        "Diagnostic Hub · Aktuell verfuegbarer Puffer · "
                        + level
                        + "\n"
                        + "\n".join(filtered(hub.sources.fetch(source), level))
                        + "\n"
                    ).encode()
                except Exception as exc:
                    self.reply(json.dumps({"error": readable_error(exc)}).encode(), "application/json", 502)
                    return
                self.reply(content, "application/octet-stream", attachment="aktueller-logpuffer.txt")
            elif path == "/api/status":
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
                page = (STATIC / "index.html").read_text().replace("__BASE__", base).replace("__VERSION__", __version__)
                self.reply(page.encode(), "text/html; charset=utf-8")
            elif path in ("/static/app.js", "/static/hub.js", "/static/runtime.js", "/static/style.css"):
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
    hub = Recordings(collector.config, collector, Sources(collector.config))
    if collector.config.get("automatic_evcc_enabled", False):
        threading.Thread(target=collector.run, daemon=True).start()
    threading.Thread(target=hub.run, daemon=True).start()
    development = os.environ.get("DIAGNOSTIC_HUB_DEV") == "1"
    server = ThreadingHTTPServer(
        ("127.0.0.1" if development else "0.0.0.0", 8099), handler_for(collector, development, hub=hub)
    )
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        collector.stop.set()
        hub.stop.set()
        server.server_close()
