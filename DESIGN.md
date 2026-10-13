---
version: alpha
name: Diagnostic Hub
description: Ein ruhiger Diagnosearbeitsplatz mit einem sichtbar gesicherten Fehlerzeitpunkt.
colors:
  primary: '#244fd1'
  background: '#eef3fa'
  surface: '#ffffff'
  ink: '#172c49'
  muted: '#50617a'
  border: '#c4d0e3'
  warning: '#805000'
  warning-bg: '#fff1d2'
  success: '#176145'
  scroll-thumb: '#778bab'
  scroll-hover: '#50617a'
typography:
  sans:
    fontFamily: 'Segoe UI, system-ui, sans-serif'
  display:
    fontFamily: 'Trebuchet MS, Segoe UI, sans-serif'
  mono:
    fontFamily: 'ui-monospace, Cascadia Code, monospace'
rounded:
  DEFAULT: '0.75rem'
spacing:
  DEFAULT: '1.25rem'
components:
  case:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink}'
  action:
    backgroundColor: '{colors.primary}'
    textColor: '{colors.surface}'
  metric:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.muted}'
  warning:
    backgroundColor: '{colors.warning-bg}'
    textColor: '{colors.warning}'
  success:
    textColor: '{colors.success}'
  scrollbar:
    backgroundColor: '{colors.scroll-thumb}'
  scrollbar-track:
    backgroundColor: '{colors.background}'
  frame:
    backgroundColor: '{colors.border}'
  scrollbar-hover:
    backgroundColor: '{colors.scroll-hover}'
---

# Diagnostic Hub Design System

## Overview

Ein Diagnosearbeitsplatz für den Betreiber einer Home-Assistant-Anlage: Störung erkennen und einen vollständigen, verständlich beschrifteten Diagnoseblock sichern. Deutsche Oberfläche, Desktop und Android, kurze Besuche bei einem Geräteausfall. Grundlage: Nutzeranforderungen in PRODUCT.md. Produkt/Admin-Register.

Signatur ist die kleine vertikale Ereignisachse mit Vorgeschichte, Fehler und Nachlauf; auf Mobilgeräten wird sie horizontal. Ruhige blaue Arbeitsflächen statt Alarm-Dashboard oder Marketing-Versprechen. Eine einzelne lesende Datenquelle, keine Attrappen für kommende Adapter.

Runtime-Tokenbesitz: Model B. `diagnostic_hub/static/style.css :root` ist kanonisch. Farben bilden die gleichnamigen `--primary`, `--background`, etc. ab; Typografie liegt in `--font-body`, `--font-display`, `--font-mono`; Radius in `--radius`, Abstand in `--space`. Keine Framework-Adapter. `scripts/check_project.py` prüft Farb- und Token-Drift.

## Colors

Die konkreten Frontmatter-Farben entsprechen den CSS-Variablen. Primärblau kennzeichnet die Textdownload-Aktion und den gesicherten Fehlerzeitpunkt. Warnungen nutzen dunklen Ocker auf heller Warnfläche. Status hat zusätzlich immer eine Textbezeichnung. Nur heller Modus; Systemkontrastfarben bleiben bedienbar.

## Typography

Trebuchet MS für kompakte Überschriften, Segoe UI/Systemschrift für Bedienung, Monospace für Logzeilen und Metadaten. Keine extern geladenen Fonts. Daten werden mit de-DE formatiert; Zeitangaben im lokalen Browser-Zeitraum, gespeicherte Zeitstempel in UTC.

## Layout

Maximal 1160px inklusive Innenabstand. Normales Dokument-Scrolling, keine festen Viewport-Höhen. Unter 650px einspaltige Fallliste, zweispaltige kleine Kennzahlen und volle Verbindungszeile. Lange Auslöser umbrechen. Safe-Area unten. 20 Fälle pro Seite, natürliche Höhe. Die Fallliste und Kennzahlen behalten stabile Mindesthöhen beim Laden.

## Elevation & Depth

Weiße Flächen und dünne blaugraue Konturen; keine dekorativen Schatten oder Overlays.

## Shapes

12px Flächenradius, 8px Aktionsradius, ruhige Statuspillen. Ein 4px blauer Rand markiert Diagnosefälle.

## Components

Fallkarte, Kennzahl und Download-Aktion sind die gemeinsamen Besitzer. Klickziele sind native Buttons, Links und Details. 44px Mindesthöhe für Aktionen, Hover-Kontur, 3px Fokusring, dezenter gedrückter Zustand. Beschäftigte Buttons bleiben breit und deaktiviert. Laden, leer, Fehler, Wiederherstellung und Datenlücke haben deutsche Textzustände. Verbindungsfehler verschwinden bei erfolgreichem Abruf; Speicherwarnungen bleiben für die laufende Sitzung sichtbar.

Keine Editierformulare oder Löschaktionen. Native Details für Sicherungsinformationen. Pagination mit URL-Seite. Global sichtbare Scrollbars über Standards und WebKit-Fallback. Keine automatischen Animationen; reduzierte Bewegung unterdrückt den gedrückten Versatz. Keine Icon-only-Bedienung. Download- und Share-Funktionen liegen in derselben Fallkarte.

## Do's and Don'ts

- Zeige Ursprung, Auslöser und Datenlücken ohne sie als Geräteursache zu behaupten.
- Erhalte offene Sicherungsdetails und Tastaturfokus bei Hintergrundaktualisierung.
- Verwende keine künstlichen Alarmzahlen oder grafischen Ersatz für reale Vorfälle.
- Behaupte keine Android- oder Fernzugriffskompatibilität ohne Test auf der Anlage.
