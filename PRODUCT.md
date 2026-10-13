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
