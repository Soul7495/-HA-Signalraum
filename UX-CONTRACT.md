# Oberflächenvertrag

Autoritative Produktregeln: PRODUCT.md; API-Vertrag: diagnostic_hub/DOCS.md.

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Scrollbar | static/style.css global baseline | DESIGN.md | forced-colors | scripts/browser_check.py |
| CRUD | static/app.js caseCard/update (read only) | PRODUCT.md | Text / Original / optional Teilen | tests/test_http.py + scripts/browser_check.py |

Eine gemeinsame Fallkarte für alle Fälle; dieselbe Downloadfunktion für alle Dateiformate. Keine Lösch- oder Steuerungsfunktionen. 20 Fälle pro Seite, Seite in URL. Ausgelieferte API-Antworten werden bei Fehlern als veraltet markiert. Native Details haben Standardtastaturverhalten. Keine Dialoge, Selects oder Formulare im aktuellen Produkt.

Laden → Fallliste oder Leerzustand; API-Fehler → sichtbarer Hinweis, vorhandene Fälle bleiben erhalten → Aktualisieren stellt Status wieder her. Hintergrundaktualisierung erhält aufgeklappte Details und fokussierte Aktionen. Downloads senden `attachment`, MIME-Typ, Länge und `no-store`, gzip wird nicht als Transportkomprimierung markiert. Ingress-Prefix kommt vom Supervisor; direkter Netzwerkzugriff ist abgewiesen. Datei-Sharing ist nur nach Browser-Capability-Prüfung sichtbar und verwendet einen zweiten bewussten Klick.

Geschäftliche Grenzen werden nie durch UI-Defaults ersetzt: Aufbewahrung, lesender Zugriff und Speichergrenze stammen aus PRODUCT.md.
