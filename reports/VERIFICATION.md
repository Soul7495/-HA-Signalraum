# Prüfbericht – Diagnostic Hub 0.2.0

Stand: 13.10.2026. Prüfungen in einer Linux/amd64-Entwicklungsumgebung, ohne Verbindung zur produktiven Home-Assistant-/evcc-/RCT-Anlage. Alle Geräteereignisse und Screenshots verwenden synthetische Testdaten.

| Prüfung | Tatsächliches Ergebnis | Grenze |
|---|---|---|
| Ursprüngliches ZIP | 3 bestehende Unit-Tests bestanden | Keine Container-/HA-Prüfung im Original |
| Endgültige Unit-/HTTP-Tests | **30 bestanden**, `python -m unittest discover -s tests -v` | Lokale Testserver und simulierte Zeit/Ereignisse |
| Überlappungsvergleich | Duplikate, Rotation, Resync, 1.500 zufällige Vergleichsfolgen | Keine Sequenznummern in evcc-API |
| Fallaufnahme | Ausgangsfehler, Wiederholungen, feste Fenster, Zugriffsausfall, Fehlerhäufung | Keine reale RCT-Instanz |
| Neustart und Nachlauf | Cursor/Fälle wiederhergestellt, Vorgeschichte/Nachlauf erhalten, Ausfall gekennzeichnet | Harter Stromverlust zwischen zwei unabhängigen Dateitransaktionen kann doppelte Beobachtungen verursachen |
| Speicherverwaltung | Alter, harte Grenze, Schreib-Staging, aktive Fallentfernung, unmöglicher Einzelblock, Nachlaufkürzung | Dateisystem-/HA-Logging-Overhead nicht enthalten |
| Downloads | Text/gzip und Inhalt geprüft; laufender Download nach gleichzeitiger Entfernung bestanden | Kein echter Supervisor oder Android Companion |
| Zugriff und Eingaben | Ingress-IP-Prüfung, direkte/spoofed Clients, Traversal, Symlink, fehlende Dateien, API-Auth, Redirect, HTML und Übergröße geprüft | HA-Berechtigungsmodell selbst nicht ausgeführt |
| Browser | **Chromium 151**, Desktop 1440px und Touch-Viewport 390px; leer, Erfolg, Details, Keyboard, Fehler/Recovery, Pagination, Downloads; keine JavaScript-Fehler | Chromium-Touchsimulation ist keine Android-App, Datei-Sharing nicht auf realem Gerät getestet |
| Metadaten | Repository-URL, Slug/Version, Architekturen, Ingress, Share-Mapping, Optionsschema/Übersetzung geprüft | Projektprüfung, keine vollständige Supervisor-Installation |
| Python-/JS-Prüfung | Ruff Check/Format, Python-AST, `node --check` bestanden | Keine zusätzliche Typchecker-Konfiguration vorhanden |
| Design | Offizieller `@google/design.md`-Lint: 0 Fehler/0 Warnungen; Token-Drift-Prüfung bestanden; Premium-Static-Audit strict: 0 Befunde | Keine vollständige WCAG-Zertifizierung; Tastatur/Fokus und Touchlayout praktisch geprüft |
| evcc-Vertrag | Quellcode von **0.317.1 Stable**, Commit `259d5fd99774ccb3690eb0de8ebbf873089bd13d` geprüft | Produktiver API-Abruf weiterhin offen |
| amd64-Docker-Build | **Bestanden** | Linux/amd64 |
| amd64-Container-Lebenszyklus | **Bestanden**: tatsächlicher App-Start, evcc-GET, automatische Aufnahme, gzip-Download, Wiederanlauf ohne Verdopplung | Simulierter evcc im selben isolierten Container |
| aarch64-Docker-Build | **Bestanden**, `--platform linux/arm64` | Keine Ausführung auf Pi 5 |
| aarch64-Container-Ausführung | **Nicht erfolgreich ausführbar:** `exec format error` | Entwicklungsmaschine hat keine ARM-/QEMU-Ausführung; nicht als bestandener Test gezählt |
| GitHub Actions | Workflow für Tests, Browser und beide Plattformen vorbereitet | Tatsächlichen Remote-Run separat prüfen; lokale Ergebnisse sind kein Nachweis eines erfolgreichen Actions-Laufs |

## Containeridentität

Gepinnte Multiarch-Basis: `python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4`.

Lokale fertige Image-IDs (keine veröffentlichten Registry-Images):

- amd64: `sha256:ac7b6ea9268d0add77737c1bd2754c27952e0cc2a3db6c28e25eb5ec85fc4fab`
- aarch64: `sha256:d2034a47d260378f805be649a69eeb2651bc84f1d12bbd6c6ad1cc0ea4b36e60`

Home Assistant baut das Add-on aus den veröffentlichten Quellen. Der Quellstand ist zur Installation strukturiert und die Images sind baubar; eine erfolgreiche Installation auf der Zielanlage wird noch nicht behauptet.

## Belege

- `unit-tests.txt`: vollständiger lokaler Testlauf.
- `build-amd64.txt`, `build-aarch64.txt`, `container-smoke.txt`: finaler Build und Lifecycle-Smoke-Test.
- `browser.json`, `desktop.png`, `mobile.png`: tatsächliche Browserprüfung und synthetische Screenshots.
- `design-lint.json`, `premium-audit.json`: statische Designprüfungen.

## Noch auf der Anlage erforderlich

1. Installation/Start auf Home Assistant OS und Raspberry Pi 5, Share-Persistenz und echter Ingress.
2. Erreichbarkeit/API-Authentifizierung deiner evcc-Version 0.317.1 und natürlich auftretende RCT-Power-Ereignisse.
3. Dateidownload und Öffnen auf Desktop, Android Companion App sowie tatsächlichem Fernzugriff; originales gzip und entpackten Text vergleichen. Natives Datei-Sharing separat prüfen.
4. Add-on-Neustart während eines offenen Nachlaufs auf der Anlage, anschließend Vorgeschichte/Zeitfenster/Lücken prüfen.
5. Betrieb über mehrere Tage: Speichergrenze, Dateialter, reale Lograte und Last auf dem Pi.

Die API kann keine rückwirkend nie vorhandenen TRACE-Zeilen erzeugen und identische voll rotierte Puffer nicht eindeutig unterscheiden. KI-Analyse, Zigbee2MQTT- und NIBE-Adapter sind weiterhin Folgearbeit.
