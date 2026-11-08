# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach
[Semantic Versioning](https://semver.org/lang/de/): MAJOR bei inkompatiblen Änderungen (z.B. am Profil-Format),
MINOR bei neuen Funktionen, PATCH bei Fehlerbehebungen.

Neue Version: Nummer in `src/__init__.py` erhöhen, Abschnitt hier ergänzen, dann
`.venv\Scripts\python scripts\paket_bauen.py` – das ZIP liegt danach in `dist/`.

## [Unreleased]

## [0.6.0] - 2026-11-08

### Hinzugefügt
- «Stellen bei diesen Firmen»: liest die gefundenen Karriereseiten und erkennt die einzelnen Stellen
  (strukturierte Daten, typische Stellentitel, sonst KI für unter 0.1 Rappen pro Firma); unveränderte
  Seiten werden ohne KI übersprungen, dazu höchstens ein Link «Offene Stellen» weiter
- Anzeigentexte werden geladen (auch PDF), nach Ähnlichkeit mit den eigenen Aufgaben sortiert und auf
  Wunsch die ähnlichsten mit dem Profil bewertet; übernehmen in den Tracker oder «Interessiert mich nicht»
  (kommt nicht wieder)
- Stellen weiter als der Suchradius (+10 km) werden ausgeblendet, z.B. Konzernstellen im Ausland;
  Orte werden über OpenStreetMap nachgeschlagen und gespeichert (data/orte.json)

### Behoben
- Kosten für Embeddings wurden rund 50-mal zu hoch geschätzt; bisherige Einträge sind korrigiert

## [0.5.0] - 2026-11-04

### Hinzugefügt
- «Firmen in der Umgebung» in der Stellensuche: Firmen mit Webseite aus OpenStreetMap nach Ort, Umkreis
  und Branche; das Tool sucht ihre Karriereseiten (Links wie «Jobs», «Karriere», bekannte
  Bewerbungssysteme, übliche Adressen). Ohne KI und kostenlos; robots.txt wird beachtet.
- Liste pro Person gespeichert (data/profile/<name>/firmen.json); Firmen ausblenden, Karriereseiten
  von Hand korrigieren, fehlende Firmen von Hand ergänzen

## [0.4.0] - 2026-10-25

### Hinzugefügt
- Stellensuche nach Aufgaben (Modus «Aufgaben»): Die KI fasst die Aufgaben aus dem Profil zu
  Tätigkeitsfeldern zusammen und schlägt Suchbegriffe vor, die auch Stellen mit anderem Titel finden.
  Felder aus aktuellen Stellen sind vorausgewählt, Begriffe lassen sich streichen und ergänzen.
- Treffer werden nach Bedeutungs-Ähnlichkeit mit den eigenen Aufgaben vorsortiert (Embeddings von
  OpenAI bzw. Venice, sonst nach gemeinsamen Wörtern); pro Stelle «Aufgaben-Nähe» und die ähnlichsten
  eigenen Aufgaben. Die besten Anzeigen werden zuerst vollständig geladen.

### Geändert
- Dieselbe Stelle unter verschiedenen Links (gleicher Titel und Firma) wird zusammengeführt

## [0.3.2] - 2026-10-25

### Behoben
- Fotobearbeitung mit OpenAI-Zugang: bisher immer Venice-Adresse aufgerufen (Fehler 404); jetzt
  OpenAI-Bildbearbeitung mit gpt-image-2.5-flare, Venice wie bisher, sonst klarer Hinweis

## [0.3.1] - 2026-10-25

### Behoben
- Absturz beim Start, wenn ein alter Browser-Tab sich nach einem Neustart wieder verbindet
  (Schalter «Verwenden» bei den Unterlagen)
- start.bat/start.command öffnen nur den Browser, wenn das Tool schon läuft, statt mit
  «Port belegt» abzubrechen

### Geändert
- Ein Senior-Titel ist kein K.-o. mehr; entscheidend sind die geforderten Jahre, der Titel senkt nur
  den Senioritäts-Wert

## [0.3.0] - 2026-10-25

### Hinzugefügt
- Mehrere Personen in einer Installation: Auswahl «Wer nutzt das Tool gerade?» in der Seitenleiste,
  Personen anlegen, umbenennen und entfernen (landet in data/geloeschte_profile)
- Jede Person hat eigene Unterlagen, Profil, Zielprofil, Fotos, Suchen, Tracker und Einstellungen
  (data/profile/<name>/); API-Zugang und Kostenübersicht gelten für alle
- Tägliche automatische Suche prüft die gespeicherten Suchen aller Personen

### Geändert
- Bestehende Daten werden beim ersten Start automatisch in ein Profil mit dem eigenen Namen übernommen;
  das gilt auch für Sicherungen aus älteren Versionen

## [0.2.2] - 2026-10-24

### Behoben
- start.bat und start.command erkennen eine unvollständige oder kopierte Python-Umgebung (.venv)
  und legen sie automatisch neu an

## [0.2.1] - 2026-10-24

### Behoben
- Einrichtung auf Intel-Macs: pymupdf auf Version 1.x festgelegt, weil 2.0 dort kein fertiges Paket hat

## [0.2.0] - 2026-10-24

### Hinzugefügt
- Start auf dem Mac per start.command; tägliche automatische Suche bleibt Windows-only

### Geändert
- Schnellere Oberfläche: Fotos als zwischengespeicherte Vorschauen, Zeugnis-Auswertungen und PDF-Editor
  erst beim Aufklappen, Word-Export erst beim Herunterladen

## [0.1.0] - 2026-10-23

Erste versionierte Fassung.

### Hinzugefügt
- Unterlagen hochladen, Profil per KI erstellen, Analyse von Lebenslauf und Arbeitszeugnissen
- Lebenslauf-Baukasten mit sechs Vorlagen, Word-Export und englischer Fassung
- Bewerbungsschreiben, Faktencheck, Dossier und Vorbereitung auf das Vorstellungsgespräch
- Bewerbungsfoto mit KI bearbeiten und bewerten
- Stellen per Link, Text oder Übersichtsseite prüfen; gespeicherte Suchen mit täglicher Ausführung
- Strukturiertes Matching mit Zielprofil, K.-o.-Kriterien und gewichtetem Score
- Profilbasierte Suche (Adzuna, jobs.ch, LinkedIn, Job-Alert-E-Mails)
- Tracker mit Erinnerungen, Kostenübersicht, Sicherung, Modellwahl
- Versionsnummer in der App, ZIP-Paket zum Weitergeben, robustere Einrichtung per start.bat
