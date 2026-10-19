# Diagnostic Hub 0.3.0

## Arbeitsweise und Erkennung

Diagnostic Hub ist ein Home-Assistant-Add-on für gezielte Diagnoseaufnahmen. **Im Standardmodus werden keine Logs dauerhaft gelesen oder gespeichert.** Die UI erkennt installierte Apps über die Supervisor-Liste; Aufnahmen starten erst durch deine Aktion. Die ebenfalls mögliche automatische evcc-Fehlersicherung muss separat aktiviert werden.

Die Hierarchie lautet **App → Logquelle → Stufenfilter → Zeitfenster**:

- Installierte Apps/Add-ons erhalten eine Containerlog-Quelle, unabhängig vom Produktnamen: evcc, Zigbee2MQTT, NIBE Control und andere.
- Home Assistant Core wird zusätzlich angeboten. Meldungen integrierter Geräte können dort stehen. Integrationen sind keine eigenständigen Supervisor-Apps und werden nicht als solche erfunden.
- Die optional konfigurierte evcc-Systemlog-API ist eine weitere Quelle für erreichbare evcc-Instanzen, auch außerhalb Home Assistant. Sie nutzt `GET /api/system/log?level=TRACE&count=10000`, geprüft gegen evcc 0.317.1 Stable.
- App-spezifische Dateien außerhalb des Containerlogs, externe MQTT-Topics oder beliebige Dienste werden nicht automatisch erschlossen. Dafür sind weitere Adapter nötig.

**Neu erkennen** aktualisiert die App-Liste; während geöffneter UI wird die Metadatenliste höchstens einmal je Minute nachgeladen. Das ist keine dauerhafte Logaufnahme. Nur explizite Vorschau/Downloads und aktive Aufnahmen lesen Logs. Ausgefallene App-Erkennung erhält bekannte Quellen mit unbekanntem Status; neue Quellen werden erst nach erfolgreicher Erkennung angeboten.

## Installation, Berechtigungen und Upgrade

Repository `https://github.com/Soul7495/-HA-Signalraum` im App-/Add-on-Store hinzufügen. Home Assistant OS/Supervisor erforderlich. Add-on 0.3.0 installieren/aktualisieren, neu starten und über Ingress öffnen. Raspberry Pi 5 benötigt `aarch64`; außerdem `amd64` unterstützt. Das Image wird lokal aus den Quellen gebaut.

Supervisor bietet keine passende reine Rolle zum Lesen aller App-Logs: `manager` ist die kleinste bestehende geeignete Rolle. Die Version setzt `hassio_api: true` / `hassio_role: manager`. Diese Rolle besitzt systemseitig weitere Rechte; der Adapter implementiert ausschließlich eine feste **GET-Allowlist**:

- `/addons` – installierte Apps, keine Optionen oder Zugangsdaten aus anderen Apps;
- `/addons/<validierter-slug>/logs` – Containerlog;
- `/core/logs` – Core-Log.

Keine Weiterleitung beliebiger URLs, keine App-Optionsänderungen, keine Start-/Stop-Befehle an andere Apps. Supervisor-Token wird aus der Laufzeit übernommen und nicht an die UI ausgegeben. Die bisherigen `/addons`-Routen werden in der aktuellen Supervisor-API aus Kompatibilitätsgründen weiterhin unterstützt.

Referenzen: [Supervisor App-Liste](https://github.com/home-assistant/supervisor/blob/main/supervisor/api/apps.py), [Routen](https://github.com/home-assistant/supervisor/blob/main/supervisor/api/__init__.py), [Rollen](https://github.com/home-assistant/supervisor/blob/main/supervisor/api/middleware/security.py). Gegen den am 19.10.2026 gelesenen Quellstand geprüft; kein Ersatz für einen Test deines Supervisors.

Beim Upgrade werden alte evcc-Diagnosefälle gelesen. Die automatische Fehlersicherung startet nur bei explizitem `automatic_evcc_enabled: true`. Ohne diese Option wird auf den gewünschten manuellen Standard gewechselt.

## Beispiel: zwölf Stunden evcc-DEBUG

1. Falls nötig DEBUG in **evcc selbst** einstellen. Diagnostic Hub verändert die Logstufe nicht und stellt sie auch nicht zurück.
2. **Neu erkennen** wählen. Unter evcc das **Containerlog** auswählen; alternativ die zusätzliche **evcc · Systemlog-API**, wenn URL/Schlüssel korrekt konfiguriert sind.
3. **DEBUG und höher**, **12 Stunden**, beispielsweise **15 Sekunden** einstellen.
4. Entscheiden, ob der bereits vorhandene Puffer eingeschlossen werden soll. Ohne Häkchen dient der erste erfolgreiche Abruf nur als Startbasis. Seine älteren Zeilen werden nicht gespeichert; dadurch beginnt die tatsächliche Datenabdeckung erst bei diesem Abruf.
5. **Aufnahme starten**. Der angezeigte Endzeitpunkt wird gespeichert. Zwischenstände können jederzeit heruntergeladen werden. **Aufnahme beenden** beendet nur die lokale Logsammlung und erhält bisherige Daten.
6. Nach Ende als Text oder gzip herunterladen. Jede Aufnahme hat ihre eigenen Daten und Metadaten.

UI: 0,25–168 Stunden; API: 1–10.080 Minuten. Prüfintervall 10–300 Sekunden. Bis zu acht gleichzeitige Aufnahmen; identische Quellen werden pro Pollrunde nur einmal gelesen, unterschiedliche Quellen mit maximal vier parallelen GETs. Endzeitpunkt ist fest, keine automatische Verlängerung. Nach Ablauf wird kein neuer Abruf mehr begonnen. Ein nach Ende eintreffender Abruf wird verworfen und als mögliche Lücke markiert. Ein manueller Stop während eines Abrufs verhindert dessen nachträgliche Speicherung.

## Logstufen und Datenqualität

TRACE zeigt alle vorhandenen erkannten Stufen; DEBUG enthält DEBUG/INFO/WARN/ERROR; entsprechend weiter bis ERROR/FATAL/CRITICAL. Ohne erkannte Stufe bleiben Zeilen als Kontext/Stacktrace erhalten. Die Erkennung orientiert sich an Stufenwörtern und ist bei frei formatierten Meldungen eine Heuristik. Sie ist keine Zusage, dass jede Quelle überhaupt TRACE/DEBUG liefert.

Beim Supervisor werden explizit `lines=10000&no_colors=1` angefordert, statt dessen kleineren Standardausschnitt zu verwenden. Logs werden bis 4 MiB pro Antwort und maximal 10.000 Pufferzeilen gelesen. Größere Antworten werden sichtbar abgewiesen. Neue Zeilen werden über linearen Text-/Hash-Überlappungsvergleich ermittelt. Ohne Überlappung kann ein Neustart oder Pufferverlust vorliegen; mögliche Duplikate/fehlende Zeilen werden markiert. Ein voller identischer Puffer ist ohne Sequenznummern nicht eindeutig von einer Rotation unterscheidbar. Downloads dokumentieren Beobachtungszeiten in UTC; die UI zeigt Zeiten im lokalen Browser-Zeitraum.

## Neustart und Speicherung

Manuelle Aufnahmen liegen in `/share/error_logger/recordings.sqlite3`. Die Datenbank enthält Profile, Zeitpunkte, Logblöcke, Lesepositionen und Lücken. **Logblock und Cursor werden in derselben SQLite-Transaktion** mit `synchronous=FULL` gespeichert. Unveränderte Cursor werden nicht erneut geschrieben. Das verringert Schreiblast bei unveränderten Puffern. Datenbankdateien nicht im laufenden Betrieb manuell bearbeiten.

Nach einem Add-on-Neustart werden aktive Aufnahmen bis zu ihrem ursprünglichen Endzeitpunkt fortgeführt. Eine längere Pause wird als Lücke markiert. Ist die Endzeit bereits abgelaufen, wird nicht neu gestartet. Ohne erfolgreichen Abruf bzw. bei größerer Lücke am Aufnahmeende lautet der Zustand unvollständig. Während das Add-on aus ist, kann es keine Logs sammeln. Hardware-/Dateisystemschäden können auch eine transaktionale Datenbank beeinträchtigen; dafür bleiben Home-Assistant-Backups relevant.

Downloads erzeugen einen konsistenten Text-/gzip-Zwischenstand aus gespeicherten Daten, ohne die Aufnahme zu beenden. Ein weiterer späterer Download kann zusätzliche Zeilen enthalten. Endedaten bleiben bis zur konfigurierten Aufbewahrung verfügbar. Seiten umfassen maximal 20 Aufnahmen; der UI-Seitenzustand steht in der URL.

## Gemeinsame Speichergrenze und Aufbewahrung

Standard: 14 Tage und 100 MiB. MiB bedeutet 1.048.576 Bytes. Die gemeinsame Obergrenze umfasst verwaltete reguläre Dateien unter `/share/error_logger/`, inklusive Datenbank, Cursor, Archive und zeitweisem Rollback-Journal. Dateisystem-Block-/Metadaten-Overhead und Home-Assistant-eigene Containerlogs zählen nicht dazu. Keine fremden Dateien in diesem verwalteten Verzeichnis ablegen.

Für SQLite wird konservativ zusätzlicher Journalplatz reserviert. Deshalb entspricht die maximale Nutzlogmenge nicht der gesamten eingestellten MiB-Zahl. Bei ausgeschalteter Automatik wird vorhandener evcc-Altbestand berücksichtigt; die übrige Kapazität wird auf Datenbank und Journalreserve verteilt. Bei eingeschalteter Automatik wird bis zur Hälfte der Grenze für deren Archivbereich reserviert; die andere Hälfte enthält Datenbank und Journalreserve. Alte automatische Fälle können gemäß bisherigen Speicherregeln entfernt werden, auch beim Upgrade oder bei einer kleineren Grenze.

Erreicht eine manuelle Aufnahme ihre Kapazität, endet sie **sichtbar mit Speichergrenze erreicht**. Bisherige Blöcke werden nicht still für neuere Zeilen überschrieben. Bei acht intensiven Aufnahmen oder TRACE kann eine 100-MiB-Grenze schon vor zwölf Stunden erreicht werden. Gegebenenfalls Limit vorher erhöhen, Filter enger wählen oder Zwischenstände extern sichern. Eine beendete Aufnahme setzt sich nach einer Limiterhöhung nicht automatisch fort; eine neue Aufnahme starten.

Abgeschlossene/manuell beendete Aufnahmen werden nach dem konfigurierten Alter seit Start entfernt; aktive Aufnahmen bleiben bis zum Ende oder Kapazitätsstopp bestehen. Freie Datenbankseiten werden wiederverwendet und schrittweise freigegeben. Alte automatische evcc-Fälle bleiben unter `/share/error_logger/evcc/` und behalten ihre [bisherigen Regeln](AUTOMATIC.md).

## Optionen

| Option | Standard | Wirkung |
|---|---|---|
| `automatic_evcc_enabled` | false | Nur bei true zusätzliche automatische evcc-Fehlersicherung |
| `evcc_url` | `http://homeassistant.local:7070` | Nur zusätzliche Systemlog-API; richtige Adresse eintragen oder leer lassen zum Ausblenden |
| `evcc_api_key` | leer | Bearer-Schlüssel bei geschützter evcc-API |
| `poll_seconds` | 15 | Prüfintervall der optionalen Automatik; manuelle Aufnahmen haben ihr eigenes Intervall |
| `retention_days` | 14 | Aufbewahrung seit Fall-/Aufnahmestart |
| `max_storage_mb` | 100 | Gemeinsame MiB-Obergrenze mit Transaktionsreserve |
| `gzip_enabled` | true | Komprimierung neuer Logblöcke/automatischer Archive; Text-/gzip-Export immer verfügbar |

Optionen ändern und Add-on neu starten. Eine leere evcc-Adresse ist nur bei ausgeschalteter evcc-Automatik zulässig. Containerlogs benötigen keine eigene evcc-URL/API-Schlüssel, sondern den Supervisor-Zugriff.

## Downloads, Zugriff und Abnahme

Text und gzip verwenden `Content-Disposition: attachment`, feste Dateinamen, Inhaltslänge und `no-store`; gzip ist keine zusätzliche HTTP-Transportkomprimierung. Sämtliche Pfade nutzen den Ingress-Prefix, auch ohne abschließenden Slash. Produktionszugriff bleibt auf Supervisor-Ingress-IP beschränkt und das Panel für Administratoren konfiguriert. Start/Stop erfordern JSON und einen eigenen Request-Header; es gibt keine CORS-Freigabe. Wiederholte Startanfragen derselben Anfrage-ID erzeugen keine doppelten Aufnahmen.

Token-/Passwortmuster und bekannte API-/Supervisor-Schlüssel werden vor Speicherung redigiert. Geräte-/Netzwerkdetails können weiterhin privat sein; Daten vor Weitergabe prüfen. Es werden keine Logs/URLs automatisch an eine KI geschickt.

**Vor Ort noch prüfen:** Rollenübernahme und App-Liste nach Update, realer Supervisor-/Core-Logabruf, tatsächliche evcc-Logstufen, zwölf Stunden Betrieb auf dem Pi, Android Companion App und tatsächlicher Fernzugriff. Chromium-Touchsimulation ist kein Android-App-Test. Bei WebView-Downloadproblemen dieselbe Oberfläche im Browser öffnen und Text/gzip vergleichen. Der Prüfbericht nennt genau die ausgeführten Tests.
