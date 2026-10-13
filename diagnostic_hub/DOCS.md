# Diagnostic Hub 0.2.0

## Voraussetzungen und Einrichtung

Home Assistant OS oder eine Installation mit Supervisor/Add-on-Unterstützung; Raspberry Pi 5 nutzt `aarch64`. `amd64` wird ebenfalls unterstützt. Home Assistant Container ohne Supervisor kann dieses Repository nicht als Add-on installieren.

Repository `https://github.com/Soul7495/-HA-Signalraum` im Add-on-/App-Store hinzufügen. Add-on installieren, erreichbare evcc-Basisadresse und bei aktivierter evcc-Authentifizierung einen API-Schlüssel einstellen. Die Adresse muss HTTP(S) verwenden und darf keine Zugangsdaten, Queryparameter oder URL-Fragmente enthalten. Der Schlüssel bleibt in den HA-Optionen und wird nur als Bearer-Header an evcc gesendet. Redirects werden nicht verfolgt. Geänderte Optionen erfordern einen Add-on-Neustart.

Alle Optionen sind deutsch übersetzt:

| Option | Standard | Bedeutung |
|---|---|---|
| `evcc_url` | `http://homeassistant.local:7070` | Beispieladresse; tatsächlichen evcc-Host/Port eintragen |
| `evcc_api_key` | leer | Bei geschütztem evcc erforderlich |
| `poll_seconds` | 15 | Prüfintervall, 10–300 Sekunden |
| `retention_days` | 14 | Alter seit Fallanlage, 1–365 Tage |
| `max_storage_mb` | 100 | MiB, 10–10.000; Dateien inklusive Cursor und Schreib-Staging |
| `gzip_enabled` | true | Komprimierung neuer Archive; alte Archive bleiben lesbar |

## API-Vertrag: evcc 0.317.1 Stable

Quellcode-Tag **`0.317.1`** (ohne `v`), Commit `259d5fd99774ccb3690eb0de8ebbf873089bd13d`:

- [Systemlog-Handler](https://github.com/evcc-io/evcc/blob/0.317.1/server/http_site_handler.go): GET `/api/system/log`, `level`, `count`, optional `format=txt`; standardmäßig JSON-Array von Strings.
- [Ringpuffer](https://github.com/evcc-io/evcc/blob/0.317.1/util/logstash/log.go): separate TRACE-/übrige Puffer; chronologische Zusammenführung; `count=10000` begrenzt das Ergebnis.
- [Authentifizierung](https://github.com/evcc-io/evcc/blob/0.317.1/server/http_auth.go): `Authorization: Bearer <API-Schlüssel>`.

TRACE filtert nur tatsächlich gespeicherte Zeilen. Das Add-on aktiviert keine Logstufe und kann nie erzeugte oder bereits verdrängte Zeilen nicht nachliefern. Ein API-Vertragsabgleich ersetzt keinen Abruf deiner produktiven Instanz.

Antworten sind auf 4 MiB begrenzt; zu große oder unlesbare Antworten werden als Fehler angezeigt. JSON-Null/leer und reiner Logtext werden verarbeitet; eine Login-HTML-Seite wird nicht als Log gespeichert. Es gibt keine Schreib-, Steuerungs- oder Registerzugriffe.

## Fallaufnahme und Wiederholungen

Der erste erfolgreiche Abruf wird ebenfalls auf Fehler geprüft. Solche Fälle tragen `origin=initial`: Die Fehler können älter sein und der Erkennungszeitpunkt ist nicht ihr tatsächlicher Entstehungszeitpunkt. `origin=new` bedeutet durch Überlappung als neu beobachtete Einträge; `resync` kennzeichnet einen neu eingelesenen Puffer ohne bestätigte Kontinuität; `collector` bedeutet fehlgeschlagener Logabruf.

Der größte exakte Suffix-/Prefix-Überlapp wird in linearer Zeit ermittelt. Der persistierte Cursor enthält nur Zeilen-Hashes, keine Klartextlogs. Anhängen wiederholter identischer Zeilen wird erkannt, solange die Pufferlänge/Überlappung es unterscheidbar macht. Zeitstempel werden für Fehlerfingerprints entfernt; Gerätenummern, Fehlercodes und Messwerte bleiben erhalten.

**API-Grenze:** Ohne Sequenznummern ist ein voller Puffer mit identischen Zeilen vor und nach Rotation nicht unterscheidbar. Ohne Überlappung können Neustart, schnelle Rotation und größere Unterbrechung ebenfalls nicht sicher getrennt werden. Die Oberfläche und offene Fälle kennzeichnen diese Ungewissheit. Nach Resynchronisierung können alte Fehler erneut als Fälle erscheinen. Die Anzahl zählt beobachtete passende Zeilen, keine unabhängig verifizierten Geräteausfälle.

Ein Fall sichert unmittelbar den zuletzt abgerufenen Puffer (maximal 10.000 Zeilen), anschließend neue beobachtete Zeilen bis zum festen Zeitpunkt etwa 120 Sekunden nach Erkennung. Wiederholungen verlängern dieses Fenster nicht. Die nächste Prüfung schließt den Fall ab; verspätete Prüfungen werden zeitlich dokumentiert. Nachlauf ebenfalls maximal 10.000 Zeilen/4 MiB. Bei über 32 unterschiedlichen Fehlerfingerprints in einem Abruf werden 31 einzeln und der Rest in einem ausdrücklich bezeichneten Häufungsfall erfasst; dessen Vorgeschichte enthält weiterhin den gesamten verfügbaren Snapshot.

Fällt der Logabruf aus, wird die letzte verfügbare Vorgeschichte dieser laufenden Sitzung in einem Zugriffsfalldiagnoseblock gesichert. Unmittelbar nach einem Neustart vor dem ersten erfolgreichen Abruf kann diese leer sein. Bestehende offene Fälle behalten ihre bereits gesicherte Vorgeschichte.

## Neustart, Aufbewahrung und Speichergrenze

Jeder Diagnoseblock enthält Metadaten, Vorgeschichte und bereits gesammelten Nachlauf. Dateischreiben erfolgt atomar mit fsync und Rename. Offene Fälle werden beim Start aus den Archiven wiederhergestellt; ein abgelaufener Nachlauf wird auch bei weiterem Abruffehler abgeschlossen und als unvollständig gekennzeichnet. Beobachtete längere Abrufpausen sowie fehlende Überlappung erzeugen Datenlücken. Während das Add-on ausgeschaltet ist, kann es keine Logs sammeln.

Archive und Cursor sind einzeln atomar, **keine gemeinsame Datenbanktransaktion**. Ein harter Stromverlust genau zwischen Fall- und Cursor-Schreiben kann dazu führen, dass derselbe Eintrag beim Wiederanlauf erneut gezählt wird. Bereits veröffentlichte Dateien bleiben als gültiger alter oder neuer Stand erhalten; nicht bestätigte Daten können bei einem Hardware-/Dateisystemfehler verloren gehen. Der Cursor wird bei veränderten Puffern geschrieben; unveränderte Antworten erzeugen keine unnötigen Cursor-Schreibvorgänge.

Bereinigung läuft bei erfolgreichen und fehlgeschlagenen Prüfungen. Alter wird ab Fallanlage gerechnet. Danach wird die Speichergrenze durch Entfernen ältester abgeschlossener, bei Bedarf auch offener Fälle eingehalten. Speichergrenze hat Vorrang: Die Oberfläche zeigt einen Verlust offener Nachläufe an, ohne später auf gelöschte Dateien zuzugreifen. Die Warnung gilt für die laufende Sitzung. Platz für die atomare neue Datei wird vor dem Schreiben reserviert, einschließlich vorhandener Zielversion. Wenn der vollständige Nachlauf nicht in den atomaren Schreibplatz passt, wird nur der Nachlauf gekürzt und die Lücke markiert; die Vorgeschichte bleibt erhalten. Ein generell zu großer Einzelblock schlägt sichtbar fehl, ohne andere Fälle unnötig zu löschen. Die Grenze umfasst alle regulären Dateien im verwalteten evcc-Ordner, einschließlich gzip-Cursor und Staging; Dateisystem-Block-/Metadaten-Overhead und Home-Assistant-eigene Containerlogs sind nicht enthalten. Manuell eingefügte fremde Dateien sollten hier nicht liegen, da sie ebenfalls zur Bereinigung gehören.

Speicherort: `/share/error_logger/evcc/`. Neue Diagnoseblöcke sind `.json.gz` oder `.json`. Alte `.log.gz`/`.log`-Dateien der 0.1.0-Version bleiben als Altbestand sichtbar und herunterladbar.

## Oberfläche und Downloads

Status, letzter erfolgreicher Abruf, offene Nachläufe, konfigurierte Grenzen, Quelle/Kategorie, Auslöser, Zeitpunkt, beobachtete Wiederholungen, Zeilenzahlen und Datenlücken. 20 Fälle pro Seite, mobile Karten, native aufklappbare Details und Tastaturfokus.

- **Text herunterladen**: entpackter `.txt`-Block mit Metadaten, Vorgeschichte und Nachlauf.
- **Original**: gespeichertes JSON-/gzip-Archiv, ohne doppelte HTTP-gzip-Komprimierung.
- **Teilen vorbereiten / Teilen öffnen**: nur bei Browser-Unterstützung für Datei-Sharing; zwei bewusste Klicks halten die notwendige Benutzeraktivierung ein.

API-, Asset- und Downloadlinks nutzen den Supervisor-Header `X-Ingress-Path`; kein von einem fehlenden abschließenden Slash abhängiger Pfad. Download wird unter derselben Sperre wie Bereinigung/Ersetzung in Speicher übernommen. Danach kann die Datei entfernt oder aktualisiert werden, ohne den laufenden Download zu beschädigen. Ein zwischen Listenanzeige und Klick abgelaufener Block liefert 404 und kann nicht mehr geladen werden.

Kein freigegebener Host-Port. Produktionszugriff ist auf die Supervisor-Ingress-IP `172.30.32.2` beschränkt; Admin-Panel entsprechend konfiguriert. Passwort-/Tokenmuster und der konfigurierte API-Schlüssel werden vor Speicherung entfernt; automatische Redaktion garantiert keine vollständige Entfernung privater Geräte-/Netzwerkdaten. Diagnoseblöcke vor Weitergabe prüfen.

Chromium am Desktop und in schmaler Touch-Ansicht wurde hinter einem lokalen Ingress-Testproxy praktisch geprüft. **Noch nicht praktisch bestätigt:** echte Supervisor-Installation, Android Companion App, natives Dateiteilen und Download über den tatsächlichen Fernzugriff. Falls eine WebView Downloads nicht übernimmt, dieselbe HA-Oberfläche im Browser öffnen; auf deiner Anlage beide Downloadvarianten und Dateiinhalte prüfen.

## Abnahme auf deiner Anlage

1. Repository hinzufügen, Installation/Start auf dem Pi 5 prüfen; Status „Verbunden“ bei evcc 0.317.1 kontrollieren.
2. Bei einem natürlich auftretenden RCT-Fehler Auslöser, Vorgeschichte und Nachlauf prüfen. Keine absichtlichen Registeränderungen nötig.
3. Während eines offenen Falls Add-on neu starten; Fall und Vorgeschichte müssen erhalten bleiben. Eine längere Ausschaltpause muss als Lücke sichtbar werden.
4. Text und Original am Desktop, in der Android-App und über Fernzugriff laden, öffnen und inhaltlich vergleichen. Dateiteilen separat prüfen, falls angeboten.
5. Speicherverbrauch und Dateialter über mehrere Tage beobachten. Vor kleinen Testgrenzen benötigte Diagnoseblöcke sichern: Aufbewahrung kann Dateien entfernen.

Ergebnisse und offene Punkte unter `reports/VERIFICATION.md`. Zigbee2MQTT und NIBE Control sind noch nicht implementiert. Eine automatische KI-Auswertung ist nicht enthalten; der Download dient späterer Analyse.
