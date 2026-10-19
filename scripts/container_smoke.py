"""Feed synthetic evcc logs to the actual app process inside the image."""

import gzip
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class MockEvcc(BaseHTTPRequestHandler):
    requests = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).requests += 1
        assert self.path == "/api/system/log?level=TRACE&count=10000"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(["INFO ready\n", "[rct] ERROR connection timeout\n"]).encode())


with tempfile.TemporaryDirectory() as temp:
    evcc = ThreadingHTTPServer(("127.0.0.1", 0), MockEvcc)
    threading.Thread(target=evcc.serve_forever, daemon=True).start()
    options = Path(temp) / "options.json"
    options.write_text(json.dumps({"evcc_url": f"http://127.0.0.1:{evcc.server_port}", "automatic_evcc_enabled": True}))
    env = dict(os.environ, DIAGNOSTIC_HUB_OPTIONS=str(options), DIAGNOSTIC_HUB_DATA=temp, DIAGNOSTIC_HUB_DEV="1")
    process = subprocess.Popen([sys.executable, "/app/app.py"], env=env)
    try:
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8099/api/status") as response:
                    status = json.load(response)
                if status["count"] == 1 and status["health"] == "Verbunden":
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Container application did not start and capture fault")
        with urllib.request.urlopen("http://127.0.0.1:8099/api/incidents") as response:
            filename = json.load(response)["items"][0]["filename"]
        with urllib.request.urlopen("http://127.0.0.1:8099/api/download/" + filename) as response:
            assert json.loads(gzip.decompress(response.read()))["trigger"] == "[rct] ERROR connection timeout"
        process.terminate()
        process.wait(timeout=5)
        process = subprocess.Popen([sys.executable, "/app/app.py"], env=env)
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8099/api/incidents") as response:
                    cases = json.load(response)
                assert cases["total"] == 1
                assert cases["items"][0]["repeats"] == 1
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Container restart failed")
        print("PASS: actual app startup, evcc GET, optional automatic capture, gzip download, durable restart")
        process.terminate()
        process.wait(timeout=5)
        options.write_text(
            json.dumps({"evcc_url": f"http://127.0.0.1:{evcc.server_port}", "automatic_evcc_enabled": False})
        )
        process = subprocess.Popen([sys.executable, "/app/app.py"], env=env)
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8099/api/hub") as response:
                    assert json.load(response)["active"] == 0
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Manual mode did not start")
        idle_requests = MockEvcc.requests
        time.sleep(1.2)
        assert MockEvcc.requests == idle_requests, "Idle manual mode fetched logs"

        def post(path, data):
            request = urllib.request.Request(
                "http://127.0.0.1:8099" + path,
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json", "X-Diagnostic-Hub": "1"},
            )
            with urllib.request.urlopen(request) as response:
                return json.load(response)

        profile = dict(
            request_id=str(uuid.uuid4()),
            source="evcc-api",
            level="DEBUG",
            duration_minutes=720,
            poll_seconds=15,
            include_history=True,
        )
        recording = post("/api/recordings", profile)
        for _ in range(30):
            with urllib.request.urlopen("http://127.0.0.1:8099/api/recordings") as response:
                saved = json.load(response)["items"][0]
            if saved["count"] == 2:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Manual recording failed")
        assert saved["deadline"] - saved["started"] == 43200
        process.terminate()
        process.wait(timeout=5)
        process = subprocess.Popen([sys.executable, "/app/app.py"], env=env)
        for _ in range(30):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8099/api/recordings") as response:
                    restored = json.load(response)["items"][0]
                assert restored["id"] == recording["id"] and restored["count"] == 2
                assert restored["deadline"] == saved["deadline"] and restored["state"] == "running"
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("Manual recording restart failed")
        post("/api/recordings/" + recording["id"] + "/stop", {})
        with urllib.request.urlopen(
            "http://127.0.0.1:8099/api/recordings/" + recording["id"] + "/download?gzip=1"
        ) as response:
            assert "connection timeout" in gzip.decompress(response.read()).decode()
        print(
            "PASS: manual idle without log requests, 12-hour DEBUG profile, recording, restart/cursor/deadline, stop, gzip export"
        )
    finally:
        process.terminate()
        process.wait(timeout=5)
        evcc.shutdown()
        evcc.server_close()
