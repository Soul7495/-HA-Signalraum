"""Read-only source discovery: installed Supervisor apps, Core, optional evcc API."""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from evcc import EvccAdapter, MAX_LINES, MAX_RESPONSE, NoRedirect, redact

LEVELS = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARN": 3, "ERROR": 4}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SEVERITY = re.compile(r"\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL)\b", re.I)


def filtered(lines, minimum):
    if minimum not in LEVELS:
        raise ValueError("Unbekannte Logstufe")
    result = []
    for line in lines:
        match = SEVERITY.search(line)
        level = match[1].upper() if match else None
        level = {"WARNING": "WARN", "FATAL": "ERROR", "CRITICAL": "ERROR"}.get(level, level)
        # Untyped continuation/stacktrace lines remain useful at every threshold.
        if level is None or LEVELS[level] >= LEVELS[minimum]:
            result.append(line)
    return result


class Supervisor:
    def __init__(self, token=None, url="http://supervisor"):
        self.token = os.environ.get("SUPERVISOR_TOKEN", "") if token is None else token
        self.url = url.rstrip("/")
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, path):
        # Deliberately no generic URL/method input or options access.
        if not re.fullmatch(r"/addons(?:/[a-z0-9_-]+/logs)?|/core/logs", path):
            raise ValueError("Nicht zugelassener Supervisor-Lesezugriff")
        if not self.token:
            raise RuntimeError("Supervisor-Zugriff fehlt. Add-on aktualisieren und neu starten.")
        query = "?lines=10000&no_colors=1" if path.endswith("/logs") else ""
        headers = {"Authorization": "Bearer " + self.token, "Accept": "text/plain" if query else "application/json"}
        request = urllib.request.Request(self.url + path + query, headers=headers)
        with self.opener.open(request, timeout=12) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ValueError("Logantwort überschreitet 4 MiB; Quelle liefert zu viele Daten.")
            return data.decode("utf-8", errors="replace")

    def addons(self):
        obj = json.loads(self.get("/addons"))
        if obj.get("result") != "ok":
            raise RuntimeError("Supervisor hat die App-Liste abgewiesen.")
        addons = obj.get("data", {}).get("addons")
        if not isinstance(addons, list):
            raise ValueError("Unbekanntes Supervisor-Listenformat")
        return addons

    def logs(self, source_id):
        if source_id == "core":
            path = "/core/logs"
        elif source_id.startswith("addon:") and re.fullmatch(r"[a-z0-9_-]{1,128}", source_id[6:]):
            path = "/addons/" + source_id[6:] + "/logs"
        else:
            raise ValueError("Ungültige Logquelle")
        return [redact(ANSI.sub("", line), self.token) for line in self.get(path).splitlines()][-MAX_LINES:]


def readable_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return {
            401: "Authentifizierung fehlgeschlagen (HTTP 401).",
            403: "Keine Leseberechtigung (HTTP 403). Add-on mit Supervisor-Rolle manager neu starten.",
            404: "Log-Endpunkt nicht gefunden (HTTP 404). Quelle und evcc-Adresse prüfen.",
        }.get(exc.code, f"Logabruf fehlgeschlagen (HTTP {exc.code}).")
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "Quelle nicht erreichbar oder Zeitüberschreitung. Verbindung und Adresse prüfen."
    if isinstance(exc, (ValueError, RuntimeError)):
        # Only known, locally generated messages. Never return exception URLs/tokens.
        return "Logs oder App-Liste nicht lesbar. Konfiguration und Supervisor-Zugriff prüfen."
    return "Logabruf fehlgeschlagen. Quelle und Speicher prüfen."


class Sources:
    def __init__(self, config, supervisor=None, clock=time.time):
        self.config = config
        self.supervisor = supervisor or Supervisor()
        self.clock = clock
        self.lock = threading.RLock()
        self.items = {}
        self.error = ""
        self.checked_at = None
        self.direct = EvccAdapter(config)

    def discover(self, force=False):
        with self.lock:
            if not force and self.checked_at is not None and self.clock() - self.checked_at < 60:
                return self.catalog()
            items = {}
            if self.config.get("evcc_url"):
                items["evcc-api"] = dict(
                    id="evcc-api",
                    name="evcc · Systemlog-API",
                    kind="api",
                    state="configured",
                    stream="Systemlog",
                    description="Zusätzlicher Zugriff über die konfigurierte evcc-Adresse. TRACE wird nicht aktiviert.",
                )
            try:
                addons = self.supervisor.addons()
                for app in addons:
                    slug = app.get("slug", "")
                    if (
                        not isinstance(slug, str)
                        or not re.fullmatch(r"[a-z0-9_-]{1,128}", slug)
                        or slug.endswith("_diagnostic_hub")
                        or slug == "diagnostic_hub"
                    ):
                        continue
                    key = "addon:" + slug
                    items[key] = dict(
                        id=key,
                        name=str(app.get("name", slug))[:160],
                        kind="addon",
                        state=str(app.get("state", "unknown")),
                        stream="Containerlog",
                        description="Automatisch über Home Assistant erkannt. Verfügbare Logstufen hängen von der App ab.",
                    )
                items["core"] = dict(
                    id="core",
                    name="Home Assistant Core",
                    kind="core",
                    state="available",
                    stream="Systemlog",
                    description="Core-Log über den Supervisor; Integrationen protokollieren gegebenenfalls hier.",
                )
                self.error = ""
            except Exception as exc:
                self.error = readable_error(exc)
                # Keep known sources during a temporary discovery failure.
                items.update({k: dict(v, state="unknown") for k, v in self.items.items() if v["kind"] != "api"})
            self.items = items
            self.checked_at = self.clock()
            return self.catalog()

    def catalog(self):
        return dict(
            items=[
                dict(x, levels=list(LEVELS)) for x in sorted(self.items.values(), key=lambda x: x["name"].casefold())
            ],
            error=self.error,
            checked_at=self.checked_at,
        )

    def resolve(self, source_id):
        self.discover()
        with self.lock:
            if source_id not in self.items:
                raise ValueError("Quelle nicht erkannt. App-Liste aktualisieren oder evcc-Adresse konfigurieren.")
            return dict(self.items[source_id])

    def fetch(self, source_id):
        self.resolve(source_id)
        if source_id == "evcc-api":
            return self.direct.fetch()
        return self.supervisor.logs(source_id)
