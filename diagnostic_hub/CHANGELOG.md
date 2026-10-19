# Änderungen

## 0.3.0

- Installierte Supervisor-Apps und Core als Logquellen automatisch erkennen. Feste GET-Allowlist, manager-Rolle erforderlich.
- Neue Hierarchie App → Logquelle → Stufenfilter → Zeitfenster, mit Puffer-Vorschau und direktem Download.
- Manuelle Aufnahmen als Standard: Start/Beenden, Dauer/Intervall, optionaler Ausgangspuffer, mehrere Quellen und Text/gzip-Exporte.
- Atomare SQLite-Speicherung von Logs und Cursor; ursprünglicher Endzeitpunkt bleibt über Neustarts erhalten.
- Gemeinsames Speicherbudget mit Journalreserve, erkennbare Unterbrechungen und Kapazitätsstopp statt stiller Überschreibung.
- Automatische evcc-Fehlersicherung nur noch bei ausdrücklicher Option aktiv; Altbestand bleibt gemäß Aufbewahrung verfügbar.
- Keine Änderung von DEBUG/TRACE oder Geräte-/App-Steuerung.

## 0.2.0

- Stable-API-Vertrag gegen evcc 0.317.1 geprüft; keine Nightly-Annahme.
- Bereits im Ausgangspuffer enthaltene Fehler werden mit Herkunftshinweis erfasst.
- Linearer Überlappungsvergleich, persistierter Hash-Cursor und explizite Datenlücken.
- Selbstbeschreibende JSON-/gzip-Fälle mit Wiederanlauf, laufend gesichertem Nachlauf und festen Zusammenfassungsfenstern.
- Logabruf-Ausfälle erhalten eigene Diagnoseblöcke; Häufungen begrenzen Schreibarbeit.
- Bereinigung berücksichtigt offene Fälle und atomaren Schreibplatz. Downloads überstehen gleichzeitige Entfernung/Ersetzung.
- Neue deutsche mobile Oberfläche mit Auslöser, Kategorie, Wiederholungen, Nachlaufzustand, Datenlücken und Seitennavigation.
- Ingress-Pfadkorrektur, direkte Textdownloads und optionales Datei-Sharing.
- Tests, reproduzierbar gepinnte Multiarch-Containerbasis, CI und dokumentierte Abnahmegrenzen.

## 0.1.0

Ursprünglicher ZIP-Entwurf mit evcc-Collector, einfacher Dateiübersicht und drei Unit-Tests. Noch nicht als Repository veröffentlicht oder in Home Assistant geprüft.
