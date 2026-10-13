"""Read-only evcc adapter. Contract checked against evcc 0.317.1."""

import json
import hashlib
import re
import urllib.parse
import urllib.request

MAX_RESPONSE = 4 * 1024 * 1024
MAX_LINES = 10000
FAULT = re.compile(
    r"\b(?:ERROR|FATAL)\b|\bWARN\b.*(?:rct|timeout|timed out|connection|connect:|unavailable|missing|meter|battery|solar|no such host|refused|EOF|measurement)|"
    r"(?:rct|meter|measurement).*(?:timeout|timed out|connection|unavailable|missing|no data|not available|NaN)|"
    r"(?:timeout|timed out|connection refused|connection reset|no route to host|no such host)",
    re.I,
)
SENSITIVE = re.compile(
    r'(?i)((?:authorization|api[_-]?key|password|token|secret)\s*["\x27]?\s*[:=]\s*["\x27]?)(?:bearer\s+)?[^\s,"\x27;&}]+'
)


def redact(value, api_key=""):
    if api_key:
        value = value.replace(api_key, "[REDACTED]")
    value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    return SENSITIVE.sub(lambda m: m[1] + "[REDACTED]", value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer key to a redirect destination.
        return None


class EvccAdapter:
    source = "evcc"

    def __init__(self, config):
        self.config = config
        self.opener = urllib.request.build_opener(NoRedirect())

    def fetch(self):
        url = (
            self.config["evcc_url"].rstrip("/")
            + "/api/system/log?"
            + urllib.parse.urlencode({"level": "TRACE", "count": MAX_LINES})
        )
        key = self.config.get("evcc_api_key", "")
        headers = {"Accept": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        with self.opener.open(urllib.request.Request(url, headers=headers), timeout=12) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("evcc-Antwort überschreitet 4 MiB")
            content = raw.decode("utf-8", errors="replace")
            if "json" in response.headers.get("Content-Type", "") or content.lstrip().startswith(("[", "{")):
                obj = json.loads(content)
                if obj is None:  # evcc can serialize an empty slice as null
                    obj = []
                if isinstance(obj, dict):
                    obj = next((obj[k] for k in ("log", "logs", "lines") if k in obj), obj)
                if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
                    # evcc entries include trailing newlines. Normalize before overlap.
                    return [redact(x.rstrip("\r\n"), key) for x in obj][-MAX_LINES:]
                if not isinstance(obj, str):
                    raise ValueError("Unbekanntes evcc-Logformat")
                content = obj
            elif "html" in response.headers.get("Content-Type", "") or content.lstrip().startswith("<"):
                raise ValueError("evcc liefert eine HTML-Seite statt Systemlog; Adresse/Authentifizierung prüfen")
            return [redact(x, key) for x in content.splitlines()][-MAX_LINES:]


def fingerprint(line):
    # Remove only the timestamp; device IDs, error codes and measurements stay distinct.
    line = re.sub(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*", "", line)
    return hashlib.sha256(line.encode()).hexdigest()[:20]


def classify(line):
    return "RCT Power" if "rct" in line.lower() else "evcc"
