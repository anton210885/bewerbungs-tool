# Änderungen

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach
[Semantic Versioning](https://semver.org/lang/de/): MAJOR bei inkompatiblen Änderungen (z.B. am Profil-Format),
MINOR bei neuen Funktionen, PATCH bei Fehlerbehebungen.

Neue Version: Nummer in `src/__init__.py` erhöhen, Abschnitt hier ergänzen, dann
`.venv\Scripts\python scripts\paket_bauen.py` – das ZIP liegt danach in `dist/`.

## [Unreleased]

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
