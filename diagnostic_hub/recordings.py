"""Explicit, bounded log recordings. SQLite atomically commits logs and cursor."""

import gzip
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from collector import iso, overlap
from sources import LEVELS, filtered, readable_error


class Recordings:
    def __init__(self, config, legacy, sources, clock=time.time):
        self.config, self.legacy, self.sources, self.clock = config, legacy, sources, clock
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.health = ""
        self.path = legacy.root.parent / "recordings.sqlite3"
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._budget()
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL, name TEXT NOT NULL, level TEXT NOT NULL,
                    started REAL NOT NULL, deadline REAL NOT NULL, interval INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'running', include_history INTEGER NOT NULL,
                    last_poll REAL, next_poll REAL NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                    gaps TEXT NOT NULL DEFAULT '[]', error TEXT NOT NULL DEFAULT '',
                    finished REAL
                );
                CREATE TABLE IF NOT EXISTS cursors (
                    session TEXT PRIMARY KEY, payload BLOB NOT NULL,
                    FOREIGN KEY(session) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    seq INTEGER PRIMARY KEY, session TEXT NOT NULL, observed REAL NOT NULL,
                    payload BLOB NOT NULL, compressed INTEGER NOT NULL,
                    FOREIGN KEY(session) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS chunks_session ON chunks(session,seq);
            """)
        self.db.execute("PRAGMA foreign_keys=ON")
        self._expire()

    def close(self):
        self.stop.set()
        with self.lock:
            self.db.close()

    @property
    def limit(self):
        return int(self.config["max_storage_mb"]) * 1024 * 1024

    def _budget(self):
        # Reserve rollback-journal headroom, not just steady-state DB bytes.
        allocated = max(128 * 1024, self.path.stat().st_size)
        legacy_limit = (
            self.limit // 2
            if self.config.get("automatic_evcc_enabled")
            else max(0, int(self.limit - allocated * 2.1 - 65536))
        )
        with self.legacy.lock:
            self.legacy.config["storage_limit_bytes"] = legacy_limit
            self.legacy.prune()
            legacy_bytes = self.legacy.usage()
        reserved_legacy = (
            max(legacy_bytes, self.limit // 2) if self.config.get("automatic_evcc_enabled") else legacy_bytes
        )
        pages = max(32, int((self.limit - reserved_legacy - 65536) / 2.1 / 4096))
        self.db.execute(f"PRAGMA max_page_count={pages}")

    def _expire(self):
        cutoff = self.clock() - self.config["retention_days"] * 86400
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE state!='running' AND started<?", (cutoff,))
        self.db.execute("PRAGMA incremental_vacuum(64)")

    def _row(self, session_id):
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError("Aufnahme nicht gefunden oder bereits abgelaufen.")
        return row

    def public(self, row):
        result = {
            k: row[k]
            for k in (
                "id",
                "source",
                "name",
                "level",
                "started",
                "deadline",
                "interval",
                "state",
                "include_history",
                "last_poll",
                "count",
                "error",
                "finished",
            )
        }
        result["gaps"] = json.loads(row["gaps"])
        return result

    def create(self, data):
        if not isinstance(data, dict):
            raise ValueError("Ungültige Aufnahmeparameter")
        request_id = data.get("request_id")
        try:
            uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Gültige Anfrage-ID erforderlich") from None
        with self.lock:
            existing = self.db.execute("SELECT * FROM sessions WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                return self.public(existing)
            if not isinstance(data.get("source"), str):
                raise ValueError("Logquelle auswählen.")
            source = self.sources.resolve(data.get("source"))
            minutes, interval, level = data.get("duration_minutes"), data.get("poll_seconds"), data.get("level")
            if type(minutes) is not int or not 1 <= minutes <= 10080:
                raise ValueError("Aufnahmedauer muss zwischen 1 Minute und 168 Stunden liegen.")
            if type(interval) is not int or not 10 <= interval <= 300:
                raise ValueError("Prüfintervall muss zwischen 10 und 300 Sekunden liegen.")
            if not isinstance(level, str) or level not in LEVELS or type(data.get("include_history")) is not bool:
                raise ValueError("Logstufe oder Ausgangspuffer-Auswahl ungültig.")
            if self.db.execute("SELECT count(*) FROM sessions WHERE state='running'").fetchone()[0] >= 8:
                raise ValueError("Maximal acht gleichzeitige Aufnahmen. Laufende Aufnahme zuerst beenden.")
            self._expire()
            self._budget()
            stamp, key = self.clock(), uuid.uuid4().hex
            # First successful poll defines the baseline. Existing entries are
            # retained only when explicitly requested by include_history.
            with self.db:
                self.db.execute(
                    """INSERT INTO sessions(id,request_id,source,name,level,started,deadline,interval,include_history,next_poll)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        key,
                        request_id,
                        source["id"],
                        source["name"],
                        level,
                        stamp,
                        stamp + minutes * 60,
                        interval,
                        int(data["include_history"]),
                        stamp,
                    ),
                )
            return self.public(self._row(key))

    def finish(self, session_id, reason="stopped"):
        with self.lock, self.db:
            self._row(session_id)
            self.db.execute(
                "UPDATE sessions SET state=?,finished=? WHERE id=? AND state='running'",
                (reason, self.clock(), session_id),
            )
            return self.public(self._row(session_id))

    def page(self, page=1):
        with self.lock:
            self._finish_due()
            total = self.db.execute("SELECT count(*) FROM sessions").fetchone()[0]
            pages = max(1, math.ceil(total / 20))
            page = min(max(page, 1), pages)
            rows = self.db.execute(
                "SELECT * FROM sessions ORDER BY started DESC,id LIMIT 20 OFFSET ?", ((page - 1) * 20,)
            ).fetchall()
            return dict(items=[self.public(row) for row in rows], page=page, pages=pages, total=total)

    def _finish_due(self):
        rows = self.db.execute(
            "SELECT * FROM sessions WHERE state='running' AND deadline<=?", (self.clock(),)
        ).fetchall()
        with self.db:
            for row in rows:
                gaps = row["gaps"]
                if row["last_poll"] is None:
                    gaps = self._gap(row, "Kein erfolgreicher Logabruf im Aufnahmezeitfenster.")
                elif row["deadline"] - row["last_poll"] > row["interval"] * 2 + 12:
                    gaps = self._gap(row, "Aufnahmeende während einer Abrufpause; Abdeckung unvollständig.")
                state = "complete" if gaps == "[]" and not row["error"] else "incomplete"
                self.db.execute(
                    "UPDATE sessions SET state=?,gaps=?,finished=? WHERE id=?", (state, gaps, self.clock(), row["id"])
                )

    def _gap(self, row, message):
        gaps = json.loads(row["gaps"])
        if message not in gaps:
            gaps = (gaps + [message])[-32:]
        return json.dumps(gaps, ensure_ascii=False)

    def tick(self):
        with self.lock:
            self._finish_due()
            self._expire()
            rows = self.db.execute(
                "SELECT * FROM sessions WHERE state='running' AND next_poll<=? ORDER BY next_poll", (self.clock(),)
            ).fetchall()
        # Network is outside the DB lock: stop and downloads remain responsive.
        by_source = {}
        for row in rows:
            by_source.setdefault(row["source"], []).append(row)
        with ThreadPoolExecutor(max_workers=4) as pool:
            requests = {pool.submit(self.sources.fetch, source): source for source in by_source}
            for future in as_completed(requests):
                try:
                    lines, error = future.result(), None
                except Exception as exc:
                    lines, error = None, readable_error(exc)
                for row in by_source[requests[future]]:
                    self._record(row, lines, error)

    def _record(self, before, lines, error):
        with self.lock:
            row = self._row(before["id"])
            if row["state"] != "running":
                return
            if self.clock() >= row["deadline"]:
                with self.db:
                    self.db.execute(
                        "UPDATE sessions SET gaps=? WHERE id=?",
                        (
                            self._gap(
                                row,
                                "Letzter Abruf überschritt den Endzeitpunkt; verspätete Daten nicht aufgenommen.",
                            ),
                            row["id"],
                        ),
                    )
                self._finish_due()
                return
            gaps = row["gaps"]
            if error:
                with self.db:
                    self.db.execute(
                        "UPDATE sessions SET error=?,gaps=?,next_poll=? WHERE id=?",
                        (
                            error,
                            self._gap(row, "Logabruf unterbrochen; Daten können fehlen."),
                            self.clock() + row["interval"],
                            row["id"],
                        ),
                    )
                return
            hashes = [hashlib.sha256(x.encode()).hexdigest() for x in lines]
            saved = self.db.execute("SELECT payload FROM cursors WHERE session=?", (row["id"],)).fetchone()
            previous = json.loads(gzip.decompress(saved["payload"])) if saved is not None else None
            if previous is None:
                fresh = lines if row["include_history"] else []
            else:
                matching = overlap(previous, hashes)
                fresh = lines[matching:]
                if previous and not matching:
                    gaps = self._gap(
                        row, "Keine Überlappung: Neustart/Pufferrotation; Duplikate oder fehlende Zeilen möglich."
                    )
                elif previous == hashes and len(hashes) == 10000:
                    gaps = self._gap(
                        row, "Voller identischer Puffer; Rotation ohne Sequenznummer nicht eindeutig erkennbar."
                    )
                if row["last_poll"] and self.clock() - row["last_poll"] > row["interval"] * 2 + 12:
                    gaps = self._gap(
                        dict(row, gaps=gaps),
                        "Aufnahmepause oder Add-on-Neustart; vollständige Abdeckung nicht garantiert.",
                    )
            fresh = filtered(fresh, row["level"])
            payload = json.dumps(fresh, ensure_ascii=False).encode()
            compressed = self.config["gzip_enabled"]
            if compressed:
                payload = gzip.compress(payload, mtime=0)
            cursor = gzip.compress(json.dumps(hashes).encode(), mtime=0) if previous != hashes else None
            self._budget()
            free_pages = self.db.execute("PRAGMA freelist_count").fetchone()[0]
            pages = self.db.execute("PRAGMA page_count").fetchone()[0]
            maximum = self.db.execute("PRAGMA max_page_count").fetchone()[0]
            # Keep enough pages for a terminal state even when log storage fills.
            if (maximum - pages + free_pages) * 4096 < (len(payload) if fresh else 0) + (
                2 * len(cursor) if cursor else 0
            ) + 65536:
                self.finish(row["id"], "storage_full")
                self.health = "Speichergrenze erreicht. Aufnahme beendet; bisherige Daten bleiben erhalten."
                return
            try:
                with self.db:
                    if fresh:
                        self.db.execute(
                            "INSERT INTO chunks(session,observed,payload,compressed) VALUES(?,?,?,?)",
                            (row["id"], self.clock(), payload, int(compressed)),
                        )
                    if cursor is not None:
                        self.db.execute(
                            "INSERT INTO cursors(session,payload) VALUES(?,?) ON CONFLICT(session) DO UPDATE SET payload=excluded.payload",
                            (row["id"], cursor),
                        )
                    self.db.execute(
                        """UPDATE sessions SET count=count+?,last_poll=?,next_poll=?,gaps=?,error='' WHERE id=?""",
                        (len(fresh), self.clock(), self.clock() + row["interval"], gaps, row["id"]),
                    )
            except sqlite3.DatabaseError:
                self.health = "Speicher nicht beschreibbar. Aufnahme prüfen; Daten können fehlen."
                self.finish(row["id"], "storage_error")

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                self.health = "Aufnahmespeicher vorübergehend nicht verfügbar."
            self.stop.wait(1)

    def summary(self):
        with self.lock:
            return dict(
                active=self.db.execute("SELECT count(*) FROM sessions WHERE state='running'").fetchone()[0],
                bytes=sum(
                    p.stat().st_size for p in self.legacy.root.parent.rglob("*") if p.is_file() and not p.is_symlink()
                ),
                limit_bytes=self.limit,
                warning=self.health,
                automatic_evcc_enabled=self.config.get("automatic_evcc_enabled", False),
            )

    def export(self, session_id):
        with self.lock:
            row = self._row(session_id)
            metadata = self.public(row)
            parts = [
                "Diagnostic Hub · Aufnahme\n",
                json.dumps(metadata, ensure_ascii=False, indent=2),
                "\n\nStufen sind Filter vorhandener Logs. Logstufen wurden nicht verändert.\n",
                "Unbekannte Stufen/Stacktrace-Zeilen bleiben enthalten. Zeiten sind Beobachtungszeiten in UTC.\n",
                "Ohne Ausgangspuffer beginnt die Abdeckung beim ersten erfolgreichen Abruf.\n",
            ]
            for chunk in self.db.execute(
                "SELECT observed,payload,compressed FROM chunks WHERE session=? ORDER BY seq", (session_id,)
            ):
                payload = gzip.decompress(chunk["payload"]) if chunk["compressed"] else chunk["payload"]
                parts.extend(
                    ["\n--- Beobachtet: " + iso(chunk["observed"]) + " ---\n", "\n".join(json.loads(payload)) + "\n"]
                )
            return "".join(parts).encode()
