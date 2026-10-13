# Diagnostic Hub · Signalraum

Ein lesender Diagnose-Hub als Home-Assistant-Add-on. Er erkennt evcc-Störungen, sichert die verfügbare Vorgeschichte und ergänzt einen Nachlauf – auch über einen Add-on-Neustart hinweg. RCT Power ist der erste Diagnose-Schwerpunkt; Zigbee2MQTT und NIBE Control sind geplant.

**Version 0.2.0** · `aarch64` (Raspberry Pi 5) und `amd64` · Deutsche Ingress-Oberfläche

![Diagnoseübersicht mit synthetischem Testfall](reports/desktop.png)

## Installation

Voraussetzung: Home Assistant mit Supervisor/Add-on-Unterstützung, insbesondere Home Assistant OS. Home Assistant Container allein unterstützt keine Add-ons.

1. **Einstellungen → Add-ons/Apps → Store → ⋮ → Repositories** öffnen (Bezeichnungen können je nach HA-Version variieren).
2. Diese vollständige URL hinzufügen:
   ```text
   https://github.com/Soul7495/-HA-Signalraum
   ```
3. Store aktualisieren, **Diagnostic Hub** auswählen und installieren. Der Supervisor baut das Image für deine Architektur aus dem Dockerfile; ein GHCR-Image ist nicht erforderlich.
4. In der Konfiguration die **evcc-Adresse** deiner Anlage eintragen. Bei geschütztem evcc den dort erzeugten API-Schlüssel hinterlegen. Der voreingestellte Host ist ein Beispiel und muss auf deiner Anlage geprüft werden.
5. Add-on starten und **Weboberfläche öffnen** wählen. Zugriff erfolgt ausschließlich über Home Assistant Ingress; es wird kein Host-Port geöffnet.

[Einrichtung, Verhalten und Grenzen](diagnostic_hub/DOCS.md) · [Tatsächliche Prüfungen](reports/VERIFICATION.md)

## Was gesichert wird

- `GET /api/system/log?level=TRACE&count=10000`, standardmäßig alle 15 Sekunden; Vertrag anhand **evcc 0.317.1 Stable** geprüft.
- ERROR/FATAL und relevante WARN-, RCT-, Timeout-, Verbindungs- und Messwert-Ereignisse. Auch nicht erreichbarer evcc-Systemlog wird mit letzter verfügbarer Vorgeschichte dokumentiert.
- Sofort maximal 10.000 verfügbare Zeilen; danach beobachtete neue Zeilen über etwa zwei Minuten. Gleiche Fehler werden im festen Zweiminutenfenster zusammengefasst.
- 14 Tage Aufbewahrung, 100 MiB Speichergrenze (1 MiB = 1.048.576 Bytes), gzip standardmäßig aktiv.
- Selbstbeschreibende Diagnoseblöcke unter `/share/error_logger/evcc/`, inklusive Ursprung, Auslöser, Zeit, Wiederholungen, Zustand und Datenlücken. Entpackter Text und Original sind direkt herunterladbar.
- Keine Schreibzugriffe auf evcc, keine Änderungen an RCT-Registern und keine automatische Geräte- oder KI-Steuerung.

## Prüfstatus

Unit-/HTTP-Integrationstests, Chromium-Downloads hinter einem lokalen Ingress-Testproxy, schmale Touch-Ansicht und Container-Builds wurden ausgeführt. Das amd64-Image wurde mit der tatsächlichen App, simuliertem evcc und Neustart geprüft.

**Noch offen:** Installation auf deinem Home Assistant, Ausführung auf dem Raspberry Pi 5, reale evcc/RCT-Fehler und Downloads in deiner Android-App sowie über deinen Fernzugriff. Der Testproxy ist kein echter Supervisor. Details und Befehle stehen im Prüfbericht. GitHub-Actions-Läufe sind unabhängig vom hier ausgeführten lokalen Prüfstand zu bewerten.

## Entwicklung

Laufzeit ausschließlich Python-Standardbibliothek; keine pip-Installation im Add-on erforderlich.

```sh
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
python scripts/check_project.py
python -m unittest discover -s tests -v
python -m playwright install chromium
python scripts/browser_check.py
docker build --build-arg BUILD_ARCH=amd64 -t diagnostic-hub:0.2.0 diagnostic_hub
docker run --rm -i diagnostic-hub:0.2.0 python - < scripts/container_smoke.py
```

Für lokale UI-Entwicklung kann `DIAGNOSTIC_HUB_DEV=1` gesetzt werden; der Server bindet dann ausschließlich an Loopback und umgeht die Ingress-IP-Prüfung. Diese Einstellung ist keine Home-Assistant-Option und wird im Add-on nicht gesetzt. `DIAGNOSTIC_HUB_DATA` und `DIAGNOSTIC_HUB_OPTIONS` können für isolierte Testdaten angepasst werden.

Bei Erweiterungen den Adaptervertrag in `evcc.py` verwenden und Zustand, Datenlücken, Speichergrenze sowie Downloadverhalten beibehalten. Produkt- und Oberflächenentscheidungen stehen in [PRODUCT.md](PRODUCT.md), [DESIGN.md](DESIGN.md) und [UX-CONTRACT.md](UX-CONTRACT.md).
