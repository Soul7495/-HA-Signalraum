# Oberflächenvertrag

Autoritative Produktregeln: PRODUCT.md; API-Vertrag: diagnostic_hub/DOCS.md.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | native select in Aufnahmeform | PRODUCT.md | platform-owned popup | scripts/browser_check.py |
| Form | record-form in static/hub.js | PRODUCT.md | Aufnahme starten | tests/test_recordings.py |
| Scrollbar | static/style.css global baseline | DESIGN.md | forced-colors | scripts/browser_check.py |
| CRUD | static/app.js caseCard/update (read only) | PRODUCT.md | Text / Original / optional Teilen | tests/test_http.py + scripts/browser_check.py |

Eine gemeinsame Fallkarte für alle Fälle; dieselbe Downloadfunktion für alle Dateiformate. Keine Lösch- oder App-Steuerungsfunktionen. Lokale Aufnahmen lassen sich gezielt starten und beenden. 20 Fälle pro Seite, Seite in URL. Ausgelieferte API-Antworten werden bei Fehlern als veraltet markiert. Native Details haben Standardtastaturverhalten. Native Select-Popups sind bewusst plattformeigen (Android/Desktop). Die Aufnahmeform wird vom Produkt validiert; kein Browser-Validierungsdialog.

Laden → Fallliste oder Leerzustand; API-Fehler → sichtbarer Hinweis, vorhandene Fälle bleiben erhalten → Aktualisieren stellt Status wieder her. Hintergrundaktualisierung erhält aufgeklappte Details und fokussierte Aktionen. Downloads senden `attachment`, MIME-Typ, Länge und `no-store`, gzip wird nicht als Transportkomprimierung markiert. Ingress-Prefix kommt vom Supervisor; direkter Netzwerkzugriff ist abgewiesen. Datei-Sharing ist nur nach Browser-Capability-Prüfung sichtbar und verwendet einen zweiten bewussten Klick.

Geschäftliche Grenzen werden nie durch UI-Defaults ersetzt: Aufbewahrung, lesender Zugriff und Speichergrenze stammen aus PRODUCT.md.

## Aufnahmefluss 0.3.0

Nutzerentscheidung vom 19.10.2026: manuelle Aufnahme als Standard; optionale automatische evcc-Fehlersicherung; Logstufen niemals ändern. App → Logquelle → Stufenfilter → Zeitfenster. Start bleibt in derselben Ansicht und zeigt Bestätigung/Endzeit. Wiederholte Startanfragen derselben Anfrage-ID sind idempotent. Beenden stoppt weitere Sammlung und erhält alle Daten; dafür keine zusätzliche Bestätigung. Formwerte bleiben nach Fehlern erhalten, ungültiges Feld erhält Fokus und aria-invalid. Datenabdeckung beginnt ohne Ausgangspuffer beim ersten erfolgreichen Abruf. Hintergrundaktualisierung ersetzt keine fokussierten Aktionen oder offenen Selects.
