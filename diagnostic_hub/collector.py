"""Durable diagnosis cases, bounded atomic storage, and restart-safe polling."""

import copy
import gzip
import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from evcc import EvccAdapter, FAULT, MAX_LINES, classify, fingerprint

LOG = logging.getLogger("diagnostic-hub")
DATA = Path(os.environ.get("DIAGNOSTIC_HUB_DATA", "/share/error_logger"))
OPTIONS = Path(os.environ.get("DIAGNOSTIC_HUB_OPTIONS", "/data/options.json"))
DEFAULTS = dict(
    evcc_url="http://homeassistant.local:7070",
    evcc_api_key="",
    poll_seconds=15,
    retention_days=14,
    max_storage_mb=100,
    gzip_enabled=True,
    automatic_evcc_enabled=False,
)
POST_SECONDS = 120


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def settings():
    from urllib.parse import urlsplit

    config = dict(DEFAULTS)
    if OPTIONS.exists():
        config.update(json.loads(OPTIONS.read_text()))
    url = urlsplit(config["evcc_url"])
    if config["automatic_evcc_enabled"] and not config["evcc_url"]:
        raise ValueError("Für automatische evcc-Fehlersicherung ist eine evcc-Adresse erforderlich")
    if config["evcc_url"] and (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("evcc-Adresse muss eine HTTP(S)-Basisadresse ohne Zugangsdaten oder URL-Parameter sein")
    for key, low, high in [("poll_seconds", 10, 300), ("retention_days", 1, 365), ("max_storage_mb", 10, 10000)]:
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError(f"Ungültige Option: {key}")
    if type(config["automatic_evcc_enabled"]) is not bool:
        raise ValueError("Ungültige Automatik-Option")
    if type(config["gzip_enabled"]) is not bool or not isinstance(config["evcc_api_key"], str):
        raise ValueError("Ungültige Komprimierung oder API-Schlüssel")
    return config


def overlap(previous, current):
    """Longest suffix/prefix in linear time (KMP), preserving duplicate counts."""
    if not current or not previous:
        return 0
    sequence = current + [None] + previous[-len(current) :]
    prefix = [0] * len(sequence)
    for i in range(1, len(sequence)):
        j = prefix[i - 1]
        while j and sequence[i] != sequence[j]:
            j = prefix[j - 1]
        if sequence[i] == sequence[j]:
            j += 1
        prefix[i] = j
    return prefix[-1]


class StorageFull(Exception):
    pass


class Collector:
    def __init__(self, config, root=DATA, clock=time.time):
        self.config = config
        self.clock = clock
        self.adapter = EvccAdapter(config)
        self.root = Path(root) / "evcc"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.incidents = {}  # summaries only; logs remain on disk
        self.cursor = []
        self.last_snapshot = []
        self.initialized = False
        self.health = "Warte auf evcc"
        self.last_success = None
        self.poll_failures = 0
        self.warning = ""
        self.continuity = "Erster Abruf steht aus"
        self.dropped = 0
        self.last_error = ""
        self.cursor_file = self.root / ".cursor.json.gz"
        with self.lock:
            for p in self.root.glob("*.tmp"):
                p.unlink()  # interrupted atomic writes, never exposed as downloads
            self.load()
            self.prune()

    @property
    def limit(self):
        return self.config.get("storage_limit_bytes", int(self.config["max_storage_mb"]) * 1024 * 1024)

    def files(self):
        return [p for p in self.root.iterdir() if p.is_file() and not p.is_symlink()]

    def usage(self):
        return sum(p.stat().st_size for p in self.files())

    def load(self):
        if self.cursor_file.exists():
            try:
                with gzip.open(self.cursor_file, "rt", encoding="utf-8") as stream:
                    state = json.load(stream)
                if state.get("version") != 1 or not isinstance(state["hashes"], list):
                    raise ValueError("Ungültiger Cursor")
                if not all(isinstance(x, str) and len(x) == 64 for x in state["hashes"]):
                    raise ValueError("Ungültige Cursor-Hashes")
                self.cursor = state["hashes"][-MAX_LINES:]
                self.initialized = True
                self.last_success = state.get("last_success")
            except (ValueError, KeyError, OSError):
                self.warning = "Leseposition beschädigt; nächster Abruf wird als Ausgangssnapshot gesichert."
        for path in self.files():
            if path.name.endswith((".json", ".json.gz")) and not path.name.startswith("."):
                try:
                    item = self.read_case(path)
                    self.incidents[path.name] = self.summary(item, path)
                except (OSError, ValueError, KeyError, EOFError):
                    self.warning = "Ein Diagnoseblock ist beschädigt; die Datei bleibt zum manuellen Prüfen erhalten."
            elif path.name.endswith((".log", ".log.gz")):
                self.incidents[path.name] = dict(
                    id=path.name,
                    filename=path.name,
                    source="evcc",
                    category="Altbestand",
                    trigger="Diagnoseblock aus Version 0.1.0",
                    status="legacy",
                    repeats=None,
                    time=iso(path.stat().st_mtime),
                    epoch=path.stat().st_mtime,
                    bytes=path.stat().st_size,
                    gaps=[],
                    deadline=None,
                )

    @staticmethod
    def read_case(path):
        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as stream:
            # Our own archives are bounded to two 4 MiB snapshots + metadata.
            text = stream.read(12 * 1024 * 1024 + 1)
            if len(text) > 12 * 1024 * 1024:
                raise ValueError("Diagnoseblock zu groß")
            item = json.loads(text)
        if not isinstance(item, dict) or item.get("version") != 1:
            raise ValueError("Ungültiger Diagnoseblock")
        for key in ("id", "source", "category", "trigger", "time", "origin"):
            if not isinstance(item.get(key), str):
                raise ValueError("Ungültige Fallmetadaten")
        if item.get("status") not in ("pending", "complete", "incomplete"):
            raise ValueError("Ungültiger Fallzustand")
        for key in ("epoch", "deadline"):
            if type(item.get(key)) not in (int, float) or not 0 <= item[key] < 1e12:
                raise ValueError("Ungültiger Fallzeitpunkt")
        if type(item.get("repeats")) is not int or item["repeats"] < 1:
            raise ValueError("Ungültige Wiederholungszahl")
        for key in ("pre_log", "post_log", "gaps"):
            if not isinstance(item.get(key), list) or not all(isinstance(x, str) for x in item[key]):
                raise ValueError("Ungültige Logdaten")
        return item

    @staticmethod
    def summary(item, path):
        keys = (
            "id",
            "source",
            "category",
            "trigger",
            "status",
            "repeats",
            "time",
            "epoch",
            "deadline",
            "gaps",
            "origin",
            "last_seen",
        )
        result = {k: item.get(k) for k in keys}
        result.update(
            filename=path.name,
            bytes=path.stat().st_size,
            pre_lines=len(item["pre_log"]),
            post_lines=len(item["post_log"]),
        )
        return result

    def prune(self, reserve=0, protect=None):
        cutoff = self.clock() - int(self.config["retention_days"]) * 86400
        candidates = sorted(
            (p for p in self.files() if not p.name.startswith(".") and p.name != protect),
            key=lambda p: self.incidents.get(p.name, {}).get("epoch", p.stat().st_mtime),
        )
        for path in candidates:
            epoch = self.incidents.get(path.name, {}).get("epoch", path.stat().st_mtime)
            if epoch < cutoff:
                self.remove(path)
        total = self.usage()
        # Prefer completed files, but the hard storage limit wins over active cases.
        candidates = sorted(
            (p for p in self.files() if not p.name.startswith(".") and p.name != protect),
            key=lambda p: (self.incidents.get(p.name, {}).get("status") == "pending", p.stat().st_mtime),
        )
        for path in candidates:
            if total + reserve <= self.limit:
                break
            total -= path.stat().st_size
            self.remove(path, pressure=True)
        if total + reserve > self.limit:
            raise StorageFull("Speichergrenze verhindert Sicherung; Grenze erhöhen oder Dateien extern sichern")

    def remove(self, path, pressure=False):
        item = self.incidents.pop(path.name, None)
        path.unlink(missing_ok=True)
        if pressure:
            self.dropped += 1
            self.warning = "Speichergrenze erreicht: älteste Fälle wurden entfernt."
            if item and item.get("status") == "pending":
                self.warning += " Darunter war ein noch offener Nachlauf."

    def staging_budget(self, path):
        existing = path.stat().st_size if path.exists() else 0
        hidden = sum(p.stat().st_size for p in self.files() if p.name.startswith(".") and p != path)
        return self.limit - existing - hidden

    def atomic(self, path, data):
        # Reserve staging bytes before writing, including the existing target.
        # Download handlers copy bytes under the same lock, so no unlinked disk leases.
        if len(data) > self.staging_budget(path):
            raise StorageFull("Einzelner Block überschreitet atomaren Schreibplatz; bestehende Fälle bleiben erhalten")
        self.prune(reserve=len(data), protect=path.name)
        temp = path.with_name(path.name + ".tmp")
        try:
            with open(temp, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            fd = os.open(self.root, os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            temp.unlink(missing_ok=True)

    def write_case(self, item, filename=None):
        filename = filename or item["id"] + (".json.gz" if self.config["gzip_enabled"] else ".json")
        path = self.root / filename
        while True:
            data = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode()
            if filename.endswith(".gz"):
                data = gzip.compress(data, compresslevel=6, mtime=0)
            if len(data) <= self.staging_budget(path) or not item["post_log"]:
                break
            # Preserve the original evidence; only reduce the subsequent tail.
            del item["post_log"][: max(1, len(item["post_log"]) // 10)]
            note = "Nachlauf für atomaren Schreibplatz gekürzt; Vorgeschichte bleibt erhalten."
            if note not in item["gaps"]:
                item["gaps"].append(note)
            if item["status"] == "complete":
                item["status"] = "incomplete"
        self.atomic(path, data)
        self.incidents[filename] = self.summary(item, path)

    def save_cursor(self):
        data = json.dumps(dict(version=1, hashes=self.cursor, last_success=self.last_success)).encode()
        self.atomic(self.cursor_file, gzip.compress(data, mtime=0))

    def fetch(self):
        return self.adapter.fetch()

    @staticmethod
    def new_lines(previous, current):
        return current[overlap(previous, current) :]

    def capture_batch(self, fresh, snapshot, origin):
        grouped = {}
        for line in fresh:
            if FAULT.search(line):
                key = fingerprint(line)
                grouped.setdefault(key, [line, 0])[1] += 1
        # Bound disk work during a fault storm; the burst archive still includes
        # the entire available snapshot, not only selected triggers.
        if len(grouped) > 32:
            entries = list(grouped.items())
            grouped = dict(entries[:31])
            remaining = entries[31:]
            grouped[fingerprint("diagnostic-hub fault burst")] = [
                f"Fehlerhäufung: {len(remaining)} weitere unterschiedliche Auslöser; siehe Vorgeschichte",
                sum(value[1] for _, value in remaining),
            ]
        for key, (line, count) in grouped.items():
            active = next(
                (x for x in self.incidents.values() if x["status"] == "pending" and x["id"].endswith(key)), None
            )
            if active:
                item = self.read_case(self.root / active["filename"])
                item["repeats"] += count
                item["last_seen"] = iso(self.clock())
                self.write_case(item, active["filename"])
            else:
                stamp = self.clock()
                item = dict(
                    version=1,
                    id=datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + key,
                    source=self.adapter.source,
                    category="evcc-Zugriff" if origin == "collector" else classify(line),
                    epoch=stamp,
                    time=iso(stamp),
                    deadline=stamp + POST_SECONDS,
                    trigger=line[:2000],
                    repeats=count,
                    status="pending",
                    origin=origin,
                    last_seen=iso(stamp),
                    gaps=[self.continuity] if origin in ("resync", "collector") else [],
                    pre_log=snapshot[-MAX_LINES:],
                    post_log=[],
                    notes=[
                        "TRACE-Anforderung filtert vorhandene evcc-Zeilen; sie aktiviert keine Logstufe.",
                        "Wiederholungen zählen beobachtete Logeinträge, nicht unabhängige Geräteausfälle.",
                    ],
                )
                self.write_case(item)

    def update_pending(self, fresh, gap=None, connected=True):
        for summary in list(self.incidents.values()):
            if summary["status"] != "pending" or summary["filename"] not in self.incidents:
                continue
            item = self.read_case(self.root / summary["filename"])
            original = copy.deepcopy(item)
            if gap and gap not in item["gaps"]:
                item["gaps"].append(gap)
                item["gaps"] = item["gaps"][-32:]
            if self.clock() >= item["deadline"]:
                # First post-deadline poll can be late. Include its data but label time.
                item["status"] = "complete" if connected and not item["gaps"] else "incomplete"
                item["finished_at"] = iso(self.clock())
            item["post_log"] = (item["post_log"] + fresh)[-MAX_LINES:]
            # Bound post-log bytes, not only line count.
            while len("\n".join(item["post_log"]).encode()) > 4 * 1024 * 1024:
                del item["post_log"][: max(1, len(item["post_log"]) // 10)]
                if "Nachlauf wegen Größenlimit gekürzt" not in item["gaps"]:
                    item["gaps"].append("Nachlauf wegen Größenlimit gekürzt")
            if item != original:
                self.write_case(item, summary["filename"])

    def poll(self):
        lines = self.fetch()
        self.last_snapshot = lines
        hashes = [hashlib.sha256(line.encode()).hexdigest() for line in lines]
        with self.lock:
            matching = overlap(self.cursor, hashes)
            gap = None
            origin = "new"
            if not self.initialized:
                fresh = lines
                origin = "initial"
                self.continuity = "Ausgangssnapshot: enthaltene Fehler können bereits älter sein."
            else:
                fresh = lines[matching:]
                if self.cursor and matching == 0:
                    gap = "Keine Log-Überlappung: evcc-Neustart oder Pufferrotation möglich."
                    self.continuity = gap
                    origin = "resync"
                elif hashes and matching == len(hashes) and len(hashes) == MAX_LINES:
                    self.continuity = (
                        "Puffer unverändert; identische Rotation ohne Sequenznummer ist nicht unterscheidbar."
                    )
                else:
                    self.continuity = "Log-Überlappung bestätigt" if matching else "Leerer Ausgangspuffer"
                if self.last_success and self.clock() - self.last_success > self.config["poll_seconds"] * 2 + 12:
                    gap = "Abrufpause oder Add-on-Neustart; Vollständigkeit des Nachlaufs nicht garantiert."
            # Finalize overdue old cases before grouping new faults, so a new
            # occurrence after the fixed window becomes a new case.
            self.update_pending(fresh, gap)
            self.capture_batch(fresh, lines, origin)
            cursor_changed = hashes != self.cursor or not self.initialized
            self.cursor = hashes
            self.initialized = True
            self.last_success = self.clock()
            self.health = "Verbunden"
            self.poll_failures = 0
            self.last_error = ""
            if cursor_changed:
                self.save_cursor()
            self.prune()

    def failed(self, exc):
        with self.lock:
            self.poll_failures += 1
            self.health = "Abruf oder Sicherung fehlgeschlagen"
            # Do not log URLs/exception messages which could include secrets.
            self.last_error = f"{type(exc).__name__}: evcc-Adresse, API-Schlüssel und Speicher prüfen."
            if isinstance(exc, StorageFull):
                self.warning = str(exc)
            try:
                self.update_pending(
                    [], "Abruf/Sicherung unterbrochen; Nachlauf enthält eine Datenlücke.", connected=False
                )
                if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
                    self.continuity = (
                        "evcc-Systemlog nicht abrufbar; die zuletzt verfügbare Vorgeschichte wird gesichert."
                    )
                    self.capture_batch(
                        [f"ERROR evcc-Systemlog nicht abrufbar ({type(exc).__name__})"], self.last_snapshot, "collector"
                    )
                self.prune()
            except (OSError, StorageFull, ValueError, EOFError):
                self.warning = "Diagnosespeicher nicht beschreibbar oder voll; Sicherung unvollständig."
        LOG.warning("Abruf/Sicherung fehlgeschlagen (%s)", type(exc).__name__)

    def run(self):
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                self.poll()
            except Exception as exc:
                self.failed(exc)
            self.stop.wait(max(0.1, self.config["poll_seconds"] - (time.monotonic() - started)))

    def status(self):
        with self.lock:
            return dict(
                health=self.health,
                last_success=iso(self.last_success) if self.last_success else None,
                count=len(self.incidents),
                pending=sum(x["status"] == "pending" for x in self.incidents.values()),
                bytes=self.usage(),
                failures=self.poll_failures,
                warning=self.warning,
                error=self.last_error,
                continuity=self.continuity,
                removed_for_space=self.dropped,
                retention_days=self.config["retention_days"],
                max_storage_mb=self.config["max_storage_mb"],
                gzip_enabled=self.config["gzip_enabled"],
                poll_seconds=self.config["poll_seconds"],
            )

    def list_cases(self, page=1):
        with self.lock:
            items = sorted(self.incidents.values(), key=lambda x: x["epoch"], reverse=True)
            pages = max(1, (len(items) + 19) // 20)
            page = min(max(1, page), pages)
            return dict(
                items=copy.deepcopy(items[(page - 1) * 20 : page * 20]), page=page, pages=pages, total=len(items)
            )
