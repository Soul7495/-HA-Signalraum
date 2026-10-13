# Änderungen

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
