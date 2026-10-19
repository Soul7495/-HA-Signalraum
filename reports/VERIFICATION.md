# Prüfbericht – Diagnostic Hub 0.3.1

Stand 19.10.2026. Linux/amd64-Entwicklungsumgebung, synthetische Geräte-/App-Daten. Das vom Nutzer bereitgestellte Android-Video wurde angesehen: Es zeigt die 0.2.0-Oberfläche und einen fehlgeschlagenen evcc-API-Abruf, keinen bestätigten erfolgreichen Produktiv-Logzugriff. Das Video selbst wurde nicht veröffentlicht.

## Korrektur gegenüber 0.3.0

Ein reproduzierter Startfehler betraf `crypto.randomUUID()`: Diese Browserfunktion fehlt auf gewöhnlichen unverschlüsselten HTTP-Ursprüngen. Der JavaScript-Start brach dadurch vor App-Erkennung und Formularbedienung ab. Frühere Browserprüfungen auf localhost deckten das nicht ab. 0.3.1 verwendet `crypto.getRandomValues` und einen eigenen abbrechbaren Request-Zeitgeber ohne `AbortSignal.any/timeout`.

Zusätzlich: getrennte App-/Logquellenfelder, sichtbare Version, deutliche Erkennungsfehler und ein auf Tokens/URLs/Logs verzichtender JSON-Verbindungsstatus. Die tatsächliche Ursache auf der Nutzeranlage ist damit noch nicht bewiesen.

## Tatsächlich ausgeführt

| Prüfung | Ergebnis | Praktische Grenze |
|---|---|---|
| Unit-/HTTP-Tests | **52 bestanden**, `python -m unittest discover -s tests -v` | Testserver, temporäre Daten, simulierte Uhr |
| Supervisor-Vertrag | Echter HTTP-Test von GET `/addons`, App-/Core-Logs, Bearer-Header, explizit `lines=10000&no_colors=1`, Redaktion und fester Pfad-Allowlist | Kein echter Supervisor auf Nutzeranlage |
| App-Erkennung | evcc, Zigbee2MQTT, NIBE Control und Core anhand synthetischer installierter App-Liste; eigene/ungültige App ausgefiltert | Keine pauschale Erkennung externer Dienste/Integrationen |
| Manueller Standard | Ohne aktive Aufnahmen kein Logabruf | Metadatenliste und Aufbewahrung bleiben möglich |
| Zwölfstundenprofil | 43.200 Sekunden festes Zeitfenster, DEBUG-Filter, optionaler Ausgangspuffer, Stop und Endzeit geprüft | Uhr simuliert; kein zwölfstündiger Echtzeit-Lauf |
| Wiederanlauf | Daten, Cursor, Zähler und ursprüngliches Aufnahmeende erhalten; überfällige Aufnahme wird nicht neu gestartet | Kein Hardware-Stromausfalltest |
| Transaktionsfehler | Erzwungener Fehler beim Zählerupdate rollt zuvor geschriebenen Logblock und Cursor gemeinsam zurück | SQLite-Transaktion in lokaler Testumgebung |
| Gleichzeitige Quellen | Langsamer Logabruf blockiert gesunde Quelle nicht; ein Quellabruf pro Runde für gleiche Quelle; maximal vier Worker | Keine Langzeitlastmessung mit acht realen Apps |
| Stop während Abruf | Nachträglich eintreffende Daten werden nicht mehr gespeichert | Lokales Thread-/Netzwerkszenario |
| Speicher | Journalreserve, Kapazitätsstopp mit Erhalt vorheriger Blöcke, Aufbewahrung/Kaskadenlöschung geprüft | Aufnahmedaten können lange vor zwölf Stunden die Nutzkapazität erreichen |
| Zugriff | JSON-/Request-Header für Start/Stop, idempotenter Start, Source-Allowlist; bisherige Ingress-/Traversal-/Symlink-Tests weiterhin bestanden | HA-Berechtigungsmodell nicht real ausgeführt |
| Regression 0.2.0 | Alte 30 Collector-/Adapter-/Downloadtests weiterhin bestanden | Automatik nun bewusst nur bei expliziter Option aktiv |
| Browser | Chromium: App-Hierarchie, natives Select-Popup, Formfehler/Fokus, Profilstart, Vorschau, Debug-Filter, Textdownload, Stop; alte Fälle und Seitennavigation | Lokaler Ingress-Testproxy |
| HTTP-Startregression | Browser meldet `isSecureContext=false`; randomUUID, AbortSignal.any und timeout fehlen; Erkennung, App-Auswahl, Validierung, DEBUG-Start/Stop ohne JS-Fehler | HTTP-Testorigin per Request-Interception. Attachment-Downloads brechen in diesem Testaufbau ab und werden hier nicht bestätigt; Downloadnachweis nur aus separatem Standardbrowser-Test |
| Mobil | 390px Touch-Viewport, kein horizontaler Überlauf, native Auswahl und Textdownload, Aktionen ≥44px | Kein echter Android Companion / WebView / Dateiteilen |
| Docker amd64 | Build und tatsächlicher App-Lebenszyklus erfolgreich: optionale Automatik, manueller Leerlauf ohne GETs, Zwölfstundenprofil, Aufnahme, Neustart, Endzeit/Cursor, Stop/gzip-Export | Simulierter evcc im Container |
| Docker aarch64 | **Build erfolgreich**, `--platform linux/arm64` | Keine native Ausführung auf dem Raspberry Pi 5 in dieser Umgebung; CI kann QEMU verwenden |
| Statisch | Ruff Check/Format, Python-/JS-Syntax, Metadaten, Übersetzungen und Token-Drift bestanden | Keine zusätzliche Typchecker-Konfiguration |
| Design | DESIGN.md-Lint 0 Fehler/0 Warnungen, Premium-Audit strict 0 Befunde, reale Browser-Screenshots | Keine vollständige WCAG-Zertifizierung |

Die Browserprüfung umfasst auch leere Zustände, API-Fehler mit veralteten Daten, Wiederherstellung, URL-Seitenzustand, gzip-Inhalt und Downloads während paralleler Dateientfernung. JavaScript-Laufzeitfehler: keine. Die neue Supervisor-Logquelle wird zusätzlich zum bisherigen evcc-API-Adapter angeboten; sie löst die Notwendigkeit einer manuell erratenen evcc-URL für Containerlogs ab.

## Containerstand

Gepinnte Basis: `python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4`.

Lokal gebaute Images, keine Registry-Veröffentlichung:

- amd64: `sha256:8f06dd53154c84235dc8a9862ed71985d22c24a37933c7ed3e96e5fbe279e1c0`
- aarch64: `sha256:61ef5ad65e14c18f344e630393f9f461b943ee6728a44f5005799e74ab593666`

Quellcode wird im bestehenden öffentlichen Repository veröffentlicht. Home Assistant baut das Image für die Anlage aus diesen Quellen. GitHub-Actions-Prüfungen laufen separat nach Veröffentlichung; deren Ergebnis ist direkt im Actions-Run zu bewerten und wird nicht aus lokalen Ergebnissen abgeleitet.

## Noch auf der Anlage zu prüfen

1. Update/Neustart auf 0.3.1, Übernahme von Supervisor-API-Recht und manager-Rolle, tatsächliche App-Liste und Core-/App-Logs.
2. Die passenden evcc-/Zigbee2MQTT-/NIBE-Quellen wählen; bei NIBE als reiner Integration gegebenenfalls Core-Log. Bei Bedarf DEBUG/TRACE selbst in der jeweiligen App einstellen.
3. Echter zwölfstündiger Betrieb auf dem Pi: Lograte, CPU-/Speicherlast, Kapazität und Abdeckung. Bei hoher Lograte Filter oder MiB-Grenze anpassen.
4. Add-on-Neustart in einem echten laufenden Zeitfenster; ursprüngliches Ende und Datenlücken kontrollieren.
5. Text/gzip in Android Companion App und über den tatsächlichen Fernzugriff herunterladen und öffnen. Browser-Emulation ist dafür kein Nachweis.

Belege: `unit-tests.txt`, `browser.json`, `browser-legacy.json`, `desktop.png`, `mobile.png`, `build-amd64.txt`, `build-aarch64.txt`, `container-smoke.txt`, `design-lint.json`, `premium-audit.json`.
