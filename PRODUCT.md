# Diagnostic Hub – Produktvertrag

Quelle: ausdrückliche Anforderungen des Auftraggebers vom 13.10.2026.

- Home-Assistant-Add-on für Raspberry Pi 5 (aarch64), zusätzlicher amd64-Build für Entwicklung.
- Zentraler, später erweiterbarer Hub; evcc ist erster Adapter, Zigbee2MQTT und NIBE Control sind geplant.
- Nur GET auf evcc-Systemlog. Keine RCT-Registeränderungen, Steuerung oder automatische Logstufenänderung.
- 15 Sekunden Standardintervall, maximal 10.000 verfügbare Vorgeschichte-Zeilen; sofortige Sicherung und etwa 120 Sekunden Nachlauf. Beobachtete Wiederholungen zusammenfassen.
- 14 Tage und 100 MiB standardmäßig, gzip aktiv; Speicherung `/share/error_logger/evcc/`. Harte Grenze hat Vorrang vor Vollständigkeit, Speicherverlust ist sichtbar zu machen.
- Wiederanlauf muss offene Fälle und Vorgeschichte erhalten. Nicht verfügbare Logs oder identische Puffer sind ehrlich als Grenze zu dokumentieren.
- Deutsche mobile Admin-Oberfläche innerhalb Home Assistant Ingress mit Status und Fallmetadaten.
- Text- und Originaldownload; Android-App und Fernzugriff bedürfen separater realer Prüfung.
- Öffentliches Quellcode-Repository `Soul7495/-HA-Signalraum`; keine produktiven Logdaten oder Zugangsdaten veröffentlichen.

API-Evidenz und Testgrenzen stehen in `reports/VERIFICATION.md` und `diagnostic_hub/DOCS.md`.

## Erweiterung 19.10.2026 – ausdrückliche Nutzerentscheidungen

- Installierte Home-Assistant-Apps automatisch über Supervisor erkennen; allgemeine Containerlogs anbieten. Integrationen/externe Dienste sind nicht pauschal als eigenständige Apps erkennbar. Home Assistant Core und konfigurierte evcc-Systemlog-API ergänzen die Auswahl.
- App → Logquelle → vorhandene Stufen → Zeitfenster. Sofortiger Pufferdownload und manuell gestartete, begrenzte Aufnahmen, insbesondere zwölf Stunden DEBUG.
- Keine dauerhafte Sammlung als Standard. Automatische evcc-Fehlersicherung bleibt über Add-on-Option zusätzlich aktivierbar. Update auf 0.3.0 lässt sie ohne explizite Option ausgeschaltet.
- Der Nutzer ändert App-Logstufen selbst; Diagnostic Hub filtert und liest ausschließlich vorhandene Zeilen. Keine RCT-/evcc-Steuerung.
- Lokale Aufnahmen dürfen gestartet und beendet werden, behalten nach Beenden/Neustart bisherige Daten und enden am gespeicherten Endzeitpunkt. Abdeckung/Lücken werden transparent beschrieben.
- 14-Tage-Aufbewahrung und globale konfigurierte Speicherobergrenze bleiben bestehen; atomare SQLite-Transaktionen koppeln Logdaten und Cursor. Für Rollback-Journal wird Speicher reserviert; bei knapper Kapazität stoppt eine Aufnahme sichtbar statt still vorhandene Logs zu überschreiben.
- Supervisor manager ist die kleinste passende bestehende Rolle für appübergreifende Logs; Implementierung beschränkt sich auf GET /addons, /addons/<slug>/logs und /core/logs.
