import gzip
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "diagnostic_hub"))
from app import handler_for
from collector import Collector, DEFAULTS
from recordings import Recordings
from sources import Sources, Supervisor, filtered, readable_error


class FakeSupervisor:
    def __init__(self):
        self.lines = ["INFO baseline"]
        self.calls = []
        self.failure = None

    def addons(self):
        return [
            {"slug": "local_evcc", "name": "evcc", "state": "started"},
            {"slug": "local_zigbee2mqtt", "name": "Zigbee2MQTT", "state": "started"},
            {"slug": "local_nibe", "name": "NIBE Control", "state": "started"},
            {"slug": "local_diagnostic_hub", "name": "Diagnostic Hub", "state": "started"},
            {"slug": "../../bad", "name": "Invalid", "state": "started"},
        ]

    def logs(self, source):
        self.calls.append(source)
        if self.failure:
            raise self.failure
        return list(self.lines)


class RecordingFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stamp = time.time()
        self.config = dict(DEFAULTS)
        self.legacy = Collector(self.config, Path(self.temp.name), clock=lambda: self.stamp)
        self.supervisor = FakeSupervisor()
        self.sources = Sources(self.config, self.supervisor, clock=lambda: self.stamp)
        self.hub = Recordings(self.config, self.legacy, self.sources, clock=lambda: self.stamp)
        self.addCleanup(lambda: self.hub.close())

    def data(self, **extra):
        return dict(
            request_id=str(uuid.uuid4()),
            source="addon:local_evcc",
            level="DEBUG",
            duration_minutes=720,
            poll_seconds=15,
            include_history=False,
            **extra,
        )

    def create(self, **extra):
        data = self.data()
        data.update(extra)
        return self.hub.create(data)

    def row(self, key):
        return self.hub.page()["items"][next(i for i, x in enumerate(self.hub.page()["items"]) if x["id"] == key)]


class RecordingTests(RecordingFixture, unittest.TestCase):
    def test_atomic_failure_rolls_back_both_logs_and_cursor(self):
        item = self.create(include_history=True)
        self.hub.tick()
        before = self.hub.db.execute("SELECT payload FROM cursors WHERE session=?", (item["id"],)).fetchone()[0]
        self.hub.db.execute(
            "CREATE TRIGGER fail_counter BEFORE UPDATE ON sessions WHEN NEW.count > OLD.count BEGIN SELECT RAISE(FAIL, 'simulated write failure'); END"
        )
        self.stamp += 15
        self.supervisor.lines.append("DEBUG must roll back")
        self.hub.tick()
        after = self.hub.db.execute("SELECT payload FROM cursors WHERE session=?", (item["id"],)).fetchone()[0]
        self.assertEqual(before, after)
        self.assertNotIn("DEBUG must roll back", self.hub.export(item["id"]).decode())
        self.assertEqual(self.row(item["id"])["count"], 1)
        self.assertEqual(self.row(item["id"])["state"], "storage_error")

    def test_slow_source_does_not_delay_healthy_source(self):
        self.create(source="addon:local_evcc", include_history=True)
        fast = self.create(source="addon:local_zigbee2mqtt", include_history=True)
        entered, release = threading.Event(), threading.Event()

        def fetch(source):
            if source == "addon:local_evcc":
                entered.set()
                release.wait(5)
            return ["DEBUG available"]

        with patch.object(self.sources, "fetch", side_effect=fetch):
            worker = threading.Thread(target=self.hub.tick)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                until = time.monotonic() + 2
                while self.row(fast["id"])["count"] == 0 and time.monotonic() < until:
                    time.sleep(0.01)
                self.assertEqual(self.row(fast["id"])["count"], 1)
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())

    def test_discovery_apps_core_excludes_self_and_invalid(self):
        ids = {x["id"] for x in self.sources.discover()["items"]}
        self.assertEqual(ids, {"evcc-api", "addon:local_evcc", "addon:local_zigbee2mqtt", "addon:local_nibe", "core"})
        self.assertEqual(self.supervisor.calls, [])

    def test_idle_never_reads_logs(self):
        for _ in range(3):
            self.hub.tick()
        self.assertEqual(self.supervisor.calls, [])
        self.assertFalse(self.config["automatic_evcc_enabled"])

    def test_twelve_hour_window_and_threshold_without_history(self):
        item = self.create()
        self.assertEqual(item["deadline"] - item["started"], 43200)
        self.hub.tick()
        self.stamp += 15
        self.supervisor.lines += ["TRACE omit", "DEBUG wanted", "INFO wanted", "untyped stacktrace"]
        self.hub.tick()
        text = self.hub.export(item["id"]).decode()
        self.assertIn("DEBUG wanted", text)
        self.assertNotIn("TRACE omit", text)
        self.assertNotIn("INFO baseline", text)
        self.assertIn("untyped stacktrace", text)
        self.assertEqual(self.row(item["id"])["count"], 3)
        self.stamp = item["deadline"] + 1
        before = len(self.supervisor.calls)
        self.hub.tick()
        self.assertEqual(len(self.supervisor.calls), before)
        self.assertEqual(self.row(item["id"])["state"], "incomplete")

    def test_existing_buffer_is_opt_in(self):
        item = self.create(include_history=True)
        self.hub.tick()
        self.assertIn("INFO baseline", self.hub.export(item["id"]).decode())

    def test_restart_cursor_deadline_and_gap(self):
        item = self.create(include_history=True)
        self.hub.tick()
        self.hub.close()
        self.stamp += 120
        self.hub = Recordings(self.config, self.legacy, self.sources, clock=lambda: self.stamp)
        self.supervisor.lines += ["DEBUG after restart"]
        self.hub.tick()
        restored = self.row(item["id"])
        self.assertEqual(restored["deadline"], item["deadline"])
        self.assertEqual(restored["count"], 2)
        self.assertTrue(restored["gaps"])
        self.assertEqual(self.hub.export(item["id"]).decode().count("INFO baseline"), 1)

    def test_restart_after_deadline_does_not_resume(self):
        item = self.create()
        self.hub.close()
        self.stamp += 43201
        self.hub = Recordings(self.config, self.legacy, self.sources, clock=lambda: self.stamp)
        self.hub.tick()
        self.assertEqual(self.supervisor.calls, [])
        self.assertEqual(self.row(item["id"])["state"], "incomplete")

    def test_idempotent_start_and_stop(self):
        body = self.data()
        first = self.hub.create(body)
        second = self.hub.create(body)
        self.assertEqual(first["id"], second["id"])
        self.hub.finish(first["id"])
        self.hub.finish(first["id"])
        self.hub.tick()
        self.assertEqual(self.row(first["id"])["state"], "stopped")
        self.assertEqual(self.supervisor.calls, [])

    def test_stop_during_network_fetch_discards_late_result(self):
        item = self.create(include_history=True)
        entered, release = threading.Event(), threading.Event()

        def blocked(source):
            entered.set()
            release.wait(5)
            return ["DEBUG late"]

        with patch.object(self.sources, "fetch", side_effect=blocked):
            thread = threading.Thread(target=self.hub.tick)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.hub.finish(item["id"])
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.row(item["id"])["count"], 0)

    def test_unavailable_source_and_recovery(self):
        item = self.create()
        self.supervisor.failure = TimeoutError()
        self.hub.tick()
        self.assertIn("Zeitüberschreitung", self.row(item["id"])["error"])
        self.supervisor.failure = None
        self.stamp += 15
        self.hub.tick()
        self.assertFalse(self.row(item["id"])["error"])
        self.assertTrue(self.row(item["id"])["gaps"])

    def test_missing_supervisor_still_offers_configured_evcc(self):
        source = Sources(self.config, Supervisor(token=""))
        catalog = source.discover()
        self.assertEqual([x["id"] for x in catalog["items"]], ["evcc-api"])
        self.assertTrue(catalog["error"])
        self.assertIn("kein Laufzeittoken", catalog["error"])
        self.assertEqual(source.diagnostics()["error_code"], "supervisor_token_missing")

    def test_discovery_diagnostics_hide_tokens_and_urls(self):
        supervisor = Supervisor(token="private-supervisor-key")
        source = Sources(self.config, supervisor)
        with patch.object(
            supervisor,
            "addons",
            side_effect=urllib.error.HTTPError("http://private-host/?secret=private-supervisor-key", 403, "", {}, None),
        ):
            source.discover()
        report = source.diagnostics()
        self.assertEqual(report["error_code"], "http_403")
        self.assertEqual(report["discovery_status"], "failed")
        self.assertTrue(report["supervisor_token_present"])
        self.assertNotIn("private-supervisor-key", json.dumps(report))
        self.assertNotIn("private-host", json.dumps(report))

    def test_retention_cascades_logs(self):
        item = self.create(include_history=True)
        self.hub.tick()
        self.hub.finish(item["id"])
        self.stamp += 15 * 86400
        self.hub.tick()
        self.assertEqual(self.hub.page()["total"], 0)
        self.assertEqual(self.hub.db.execute("SELECT count(*) FROM chunks").fetchone()[0], 0)

    def test_storage_stops_without_overwriting_earlier_chunks(self):
        self.config["max_storage_mb"] = 1
        item = self.create(include_history=True)
        self.supervisor.lines = ["DEBUG " + os.urandom(100000).hex()]
        self.hub.tick()
        for _ in range(8):
            self.stamp += 15
            self.supervisor.lines.append("DEBUG " + os.urandom(100000).hex())
            self.hub.tick()
        row = self.row(item["id"])
        self.assertEqual(row["state"], "storage_full")
        self.assertGreaterEqual(row["count"], 1)
        self.assertLessEqual(self.hub.summary()["bytes"], self.hub.limit)
        self.assertIn(self.supervisor.lines[0], self.hub.export(item["id"]).decode())

    def test_invalid_profile_source_and_maximum_concurrency(self):
        for change in (
            {"level": "INVALID"},
            {"source": "addon:../../x"},
            {"duration_minutes": 0},
            {"poll_seconds": 1},
            {"duration_minutes": True},
            {"include_history": "yes"},
            {"request_id": "bad"},
        ):
            data = self.data()
            data.update(change)
            with self.assertRaises(ValueError):
                self.hub.create(data)
        for _ in range(8):
            self.create()
        with self.assertRaises(ValueError):
            self.create()

    def test_no_successful_sample_finishes_as_incomplete(self):
        item = self.create(duration_minutes=1)
        self.stamp += 61
        self.assertEqual(self.row(item["id"])["state"], "incomplete")
        self.assertTrue(self.row(item["id"])["gaps"])

    def test_filter_preserves_context_and_log_levels(self):
        lines = ["TRACE a", "DEBUG b", "INFO c", "WARNING d", "FATAL e", "stacktrace line"]
        self.assertEqual(filtered(lines, "WARN"), lines[3:])
        self.assertIn("HTTP 404", readable_error(urllib.error.HTTPError("http://secret", 404, "", {}, None)))
        self.assertNotIn("secret", readable_error(urllib.error.URLError("token=secret")))


class RecordingHTTPTests(RecordingFixture, unittest.TestCase):
    # Keep endpoint tests separate from the inherited lifecycle checks.
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.legacy, development=True, hub=self.hub))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, data=None, headers=None):
        defaults = {"Content-Type": "application/json", "X-Diagnostic-Hub": "1"}
        defaults.update(headers or {})
        return urllib.request.urlopen(
            urllib.request.Request(
                self.base + path, data=json.dumps(data).encode() if data is not None else None, headers=defaults
            )
        )

    def test_api_create_stop_snapshot_and_download(self):
        with self.request("/api/recordings", self.data()) as response:
            item = json.load(response)
        self.hub.tick()
        self.stamp += 15
        self.supervisor.lines.append("DEBUG recorded")
        self.hub.tick()
        with self.request(f"/api/recordings/{item['id']}/download?gzip=1") as response:
            self.assertNotIn("Content-Encoding", response.headers)
            self.assertIn("DEBUG recorded", gzip.decompress(response.read()).decode())
        with self.request("/api/snapshot?source=addon%3Alocal_evcc&level=TRACE") as response:
            self.assertIn("attachment", response.headers["Content-Disposition"])
        with self.request(f"/api/recordings/{item['id']}/stop", {}) as response:
            self.assertEqual(json.load(response)["state"], "stopped")

    def test_downloadable_diagnostics_show_version_and_safe_status(self):
        with self.request("/api/diagnostics") as response:
            self.assertIn("attachment", response.headers["Content-Disposition"])
            report = json.load(response)
        self.assertEqual(report["version"], "0.3.1")
        self.assertEqual(report["discovery_status"], "ok")
        self.assertEqual(report["installed_apps"], 3)
        self.assertNotIn("evcc_api_key", report)

    def test_api_rejects_csrf_and_unsafe_source(self):
        with self.assertRaises(urllib.error.HTTPError) as result:
            self.request("/api/recordings", self.data(), {"X-Diagnostic-Hub": "0"})
        self.assertEqual(result.exception.code, 403)
        body = self.data()
        body["source"] = "http://untrusted/"
        with self.assertRaises(urllib.error.HTTPError) as result:
            self.request("/api/recordings", body)
        self.assertEqual(result.exception.code, 422)


class SupervisorHTTPTests(unittest.TestCase):
    def test_real_http_auth_discovery_logs_and_allowlist(self):
        from http.server import BaseHTTPRequestHandler

        seen = []

        class Mock(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                self.send_response(200)
                self.end_headers()
                if self.path == "/addons":
                    self.wfile.write(
                        json.dumps(
                            {
                                "result": "ok",
                                "data": {"addons": [{"slug": "local_evcc", "name": "evcc", "state": "started"}]},
                            }
                        ).encode()
                    )
                else:
                    self.wfile.write(b"\x1b[31mDEBUG token=test-supervisor-key\x1b[0m\nINFO ready\n")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            supervisor = Supervisor(token="test-supervisor-key", url=f"http://127.0.0.1:{server.server_port}")
            self.assertEqual(supervisor.addons()[0]["slug"], "local_evcc")
            lines = supervisor.logs("addon:local_evcc")
            self.assertIn("[REDACTED]", lines[0])
            self.assertNotIn("\x1b", lines[0])
            supervisor.logs("core")
            for forbidden in (
                "/addons/local_evcc/stop",
                "/addons/local_evcc/options",
                "http://elsewhere",
                "/addons/../../logs",
            ):
                with self.assertRaises(ValueError):
                    supervisor.get(forbidden)
            self.assertEqual(
                [x[0] for x in seen],
                ["/addons", "/addons/local_evcc/logs?lines=10000&no_colors=1", "/core/logs?lines=10000&no_colors=1"],
            )
            self.assertTrue(all(x[1] == "Bearer test-supervisor-key" for x in seen))
        finally:
            server.shutdown()
            server.server_close()
