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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class MockEvcc(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        assert self.path == "/api/system/log?level=TRACE&count=10000"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(["INFO ready\n", "[rct] ERROR connection timeout\n"]).encode())


with tempfile.TemporaryDirectory() as temp:
    evcc = ThreadingHTTPServer(("127.0.0.1", 0), MockEvcc)
    threading.Thread(target=evcc.serve_forever, daemon=True).start()
    options = Path(temp) / "options.json"
    options.write_text(json.dumps({"evcc_url": f"http://127.0.0.1:{evcc.server_port}"}))
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
        print("PASS: actual app startup, evcc GET, automatic capture, gzip download, durable restart")
    finally:
        process.terminate()
        process.wait(timeout=5)
        evcc.shutdown()
        evcc.server_close()
