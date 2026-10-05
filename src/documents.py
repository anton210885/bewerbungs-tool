import json
import re
from datetime import datetime
from pathlib import Path

import docx
import pymupdf

from src.config import DATA_DIR
from src.generate import L
from src.llm import chat_images, chat_json

DOCS_DIR = DATA_DIR / "dokumente"
KATEGORIEN = {
    "lebenslauf": "Lebenslauf",
    "zeugnisse": "Arbeitszeugnisse",
    "diplome": "Diplome & Zertifikate",
}
UPLOAD_TYPES = ["pdf", "docx", "txt", "png", "jpg", "jpeg"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
MAX_CHARS_PER_DOC = 15000
MAX_OCR_PAGES = 6

OCR_SYSTEM = (
    "Du transkribierst Dokumente. Gib den gesamten Text des Dokuments vollständig und originalgetreu "
    "wieder, ohne Kommentar und ohne Zusammenfassung."
)

PROFILE_SCHEMA = {
    "persoenlich": {
        "name": "", "titel": "", "strasse": "", "plz": "", "ort": "", "telefon": "", "email": "",
        "linkedin": "", "geburtsdatum": "", "nationalitaet": "", "bewilligung": "", "zivilstand": "",
        "fuehrerausweis": "",
    },
    "kurzprofil": "",
    "berufserfahrung": [
        {"position": "", "firma": "", "ort": "", "von": "MM/YYYY", "bis": "MM/YYYY oder leer",
         "aufgaben": [""], "erfolge": [""]}
    ],
    "ausbildung": [{"abschluss": "", "institution": "", "ort": "", "von": "", "bis": "", "details": [""]}],
    "skills": {"fachlich": [""], "software": [""]},
    "sprachen": [{"sprache": "", "niveau": ""}],
    "zertifikate": [{"name": "", "jahr": ""}],
    "projekte": [{"name": "", "von": "", "bis": "", "beschreibung": "", "technologien": [""]}],
    "bewertungen": [{"firma": "", "zitat": ""}],
    "interessen": [""],
    "referenzen": "",
    "wuensche": {"wunschberufe": [""], "pensum": "", "lohn": "", "region": "", "verfuegbarkeit": "", "sonstiges": ""},
    "weitere_infos": "",
}

ERGAENZUNGEN_PATH = DATA_DIR / "ergaenzungen.txt"
CV_ANALYSIS_PATH = DATA_DIR / "cv_analyse.json"
APPLIED_PATH = DATA_DIR / "uebernommene_verbesserungen.json"

IMPROVE_SYSTEM = f"""Du bist eine erfahrene Karriereberaterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Du erhältst ein Bewerberprofil (JSON) und Verbesserungen, die der Bewerber ausgewählt hat.
Setze diese Verbesserungen im Profil um. Strenge Regeln:
- Erfinde keine Fakten: keine neuen Tätigkeiten, Firmen, Daten, Zahlen, Tools oder Erfolge.
- Erlaubt: umformulieren, präzisieren, umsortieren, vereinheitlichen (z.B. Datumsformate), Aufgaben als
  Ergebnisse formulieren, wenn die Fakten dafür im Profil stehen, Kurzprofil verbessern.
- Braucht eine Verbesserung Informationen, die nicht im Profil stehen (z.B. fehlende Zahlen), dann ändere
  dort nichts und stelle stattdessen eine kurze Frage unter "offene_fragen".
- Ändere nur, was die Verbesserungen betreffen. Alle anderen Angaben bleiben unverändert erhalten.
- Behalte exakt dieselbe JSON-Struktur und dieselben Schlüssel wie im Eingabeprofil.
"""
IMPROVE_SYSTEM += """Gib folgendes JSON zurück:
{
  "profil": { <das vollständige, verbesserte Profil> },
  "aenderungen": ["<kurze Beschreibung jeder vorgenommenen Änderung>", ...],
  "offene_fragen": ["<Frage an den Bewerber für Punkte, die ohne weitere Infos nicht umsetzbar sind>", ...]
}"""

CV_REVIEW_SYSTEM = f"""Du bist eine erfahrene Karriereberaterin und Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Analysiere den Lebenslauf kritisch, ehrlich und konstruktiv. Achte auf:
- Aufbau, Übersichtlichkeit und Vollständigkeit
- zeitliche Lücken und fehlende Angaben
- Formulierungen: aktiv, konkret, mit messbaren Erfolgen statt reiner Aufgabenlisten
- landesübliche Konventionen (z.B. Personalien, Foto, Arbeitsbewilligung, Sprachniveaus nach GER, Referenzen)
- Tauglichkeit für automatische Bewerbermanagement-Systeme (ATS)
- Rechtschreibung und Einheitlichkeit (z.B. Datumsformate)
Beziehe die eigenen Ergänzungen und Wünsche des Bewerbers mit ein.
"""
CV_REVIEW_SYSTEM += """Gib folgendes JSON zurück:
{
  "note": <1-10, Gesamtqualität des Lebenslaufs>,
  "zusammenfassung": "<2-3 Sätze Gesamteindruck>",
  "staerken": ["...", ...],
  "schwaechen": ["...", ...],
  "verbesserungen": [{"bereich": "...", "vorschlag": "...", "beispiel": "<konkrete bessere Formulierung oder leer>"}, ...],
  "luecken": ["<zeitliche Lücken oder fehlende Angaben>", ...],
  "passende_berufe": ["<Berufe/Stellentitel, die zum Profil passen>", ...],
  "suchbegriffe": ["<gute Suchbegriffe für Jobportale>", ...]
}"""

PROFILE_SYSTEM = f"""Du erstellst aus Bewerbungsunterlagen (Lebenslauf, Arbeitszeugnisse, Diplome) ein strukturiertes Bewerberprofil.
{L["stil"]}
Regeln:
- Übernimm nur Informationen, die in den Unterlagen stehen. Erfinde nichts. Unbekanntes bleibt "" bzw. [].
- Datumsangaben als MM/YYYY (nur YYYY, wenn nur das Jahr bekannt ist). "bis" leer lassen, wenn die Stelle aktuell ist.
- Berufserfahrung und Ausbildung chronologisch absteigend (neueste zuerst).
- Ergänze Aufgaben und Erfolge pro Stelle mit Informationen aus den Arbeitszeugnissen.
- "erfolge": nur konkrete Ergebnisse, Verantwortung oder Auszeichnungen, die belegt sind.
- "bewertungen": kurze, wörtliche, positive Zitate aus den Arbeitszeugnissen (max. 2 pro Zeugnis).
- "kurzprofil": 2-3 sachliche Sätze, die das Profil zusammenfassen.
- Skills und Sprachen nur, wenn sie in den Unterlagen vorkommen.
- "Eigene Ergänzungen und Wünsche" stammen vom Bewerber selbst: Fakten daraus (Kenntnisse, Projekte,
  Weiterbildungen usw.) gehören in die passenden Abschnitte, Wünsche (Wunschberuf, Pensum, Lohn, Region,
  Verfügbarkeit) in "wuensche".
Gib JSON mit genau dieser Struktur zurück:
"""
PROFILE_SYSTEM += json.dumps(PROFILE_SCHEMA, ensure_ascii=False, indent=1)


def save_upload(kategorie: str, filename: str, data: bytes) -> Path:
    folder = DOCS_DIR / kategorie
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-. äöüÄÖÜ]+", "_", Path(filename).name)
    path = folder / safe
    path.write_bytes(data)
    _cache_path(path).unlink(missing_ok=True)
    return path


def list_documents(kategorie: str) -> list[Path]:
    folder = DOCS_DIR / kategorie
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() != ".txt")


def delete_document(path: Path) -> None:
    path.unlink(missing_ok=True)
    _cache_path(path).unlink(missing_ok=True)


def has_documents() -> bool:
    return any(list_documents(k) for k in KATEGORIEN)


def _cache_path(path: Path) -> Path:
    return path.with_name(path.name + ".extrahiert.txt")


def get_text(path: Path) -> str:
    cache = _cache_path(path)
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    text = _extract(path)[:MAX_CHARS_PER_DOC]
    cache.write_text(text, encoding="utf-8")
    return text


def _extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with pymupdf.open(path) as pdf:
            text = "\n".join(page.get_text() for page in pdf)
            if len(text.strip()) >= 80 * pdf.page_count:
                return text
            images = [page.get_pixmap(dpi=150).tobytes("png") for page in pdf.pages(0, min(pdf.page_count, MAX_OCR_PAGES))]
        return chat_images(OCR_SYSTEM, "Transkribiere dieses Dokument.", images)
    if suffix == ".docx":
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if suffix in IMAGE_SUFFIXES:
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        return chat_images(OCR_SYSTEM, "Transkribiere dieses Dokument.", [path.read_bytes()], mime)
    return path.read_text(encoding="utf-8", errors="ignore")


def profile_from_documents(on_progress=None) -> dict:
    sections = []
    for kategorie, label in KATEGORIEN.items():
        for path in list_documents(kategorie):
            if on_progress:
                on_progress(f"Lese {path.name} ...")
            sections.append(f"=== {label}: {path.name} ===\n{get_text(path)}")
    if not sections:
        raise ValueError("Keine Unterlagen hochgeladen.")
    if ergaenzungen := load_ergaenzungen().strip():
        sections.append(f"=== Eigene Ergänzungen und Wünsche ===\n{ergaenzungen}")
    if applied := load_applied_improvements():
        sections.append(
            "=== Vom Bewerber früher gewünschte Verbesserungen (bitte wieder anwenden, ohne Fakten zu erfinden) ===\n"
            + "\n".join(f"- {p}" for p in applied)
        )
    if on_progress:
        on_progress("KI erstellt dein Profil ...")
    return chat_json(PROFILE_SYSTEM, "\n\n".join(sections), temperature=0.1, max_tokens=12000)


def load_ergaenzungen() -> str:
    return ERGAENZUNGEN_PATH.read_text(encoding="utf-8") if ERGAENZUNGEN_PATH.exists() else ""


def save_ergaenzungen(text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ERGAENZUNGEN_PATH.write_text(text, encoding="utf-8")


def analyze_cv(profile: dict, on_progress=None) -> dict:
    sections = []
    for path in list_documents("lebenslauf"):
        if on_progress:
            on_progress(f"Lese {path.name} ...")
        sections.append(f"=== Lebenslauf (Originaldokument): {path.name} ===\n{get_text(path)}")
    sections.append(
        "=== Strukturiertes Profil (aus allen Unterlagen) ===\n"
        + json.dumps(profile, ensure_ascii=False, indent=1, default=str)
    )
    if ergaenzungen := load_ergaenzungen().strip():
        sections.append(f"=== Eigene Ergänzungen und Wünsche ===\n{ergaenzungen}")
    if on_progress:
        on_progress("KI analysiert deinen Lebenslauf ...")
    result = chat_json(CV_REVIEW_SYSTEM, "\n\n".join(sections), temperature=0.3, max_tokens=10000)
    try:
        result["note"] = max(1, min(10, round(float(result.get("note", 0)))))
    except (TypeError, ValueError):
        result["note"] = 0
    result["erstellt"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    CV_ANALYSIS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def improve_profile(profile: dict, points: list[str], extra: str = "") -> dict:
    wishes = "\n".join(f"- {p}" for p in points)
    if extra.strip():
        wishes += f"\n- {extra.strip()}"
    user = (
        f"PROFIL:\n{json.dumps(profile, ensure_ascii=False, indent=1, default=str)}\n\n"
        f"AUSGEWÄHLTE VERBESSERUNGEN:\n{wishes}"
    )
    result = chat_json(IMPROVE_SYSTEM, user, temperature=0.2, max_tokens=16000)
    if not isinstance(result.get("profil"), dict) or not result["profil"].get("persoenlich"):
        raise ValueError("Die KI hat kein vollständiges Profil zurückgegeben. Bitte nochmals versuchen.")
    result["punkte"] = [*points, *([extra.strip()] if extra.strip() else [])]
    return result


def load_applied_improvements() -> list[str]:
    if not APPLIED_PATH.exists():
        return []
    return json.loads(APPLIED_PATH.read_text(encoding="utf-8"))


def add_applied_improvements(points: list[str]) -> None:
    merged = list(dict.fromkeys([*load_applied_improvements(), *points]))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APPLIED_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cv_analysis() -> dict | None:
    if not CV_ANALYSIS_PATH.exists():
        return None
    return json.loads(CV_ANALYSIS_PATH.read_text(encoding="utf-8"))


def pdf_to_images(path: Path, dpi: int = 80) -> list[bytes]:
    with pymupdf.open(path) as pdf:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in pdf]


def build_dossier(parts: list[Path], out_path: Path) -> Path:
    """Fügt PDFs und Bilder zu einem einzigen PDF zusammen (Bilder auf A4-Seiten)."""
    dossier = pymupdf.open()
    for path in parts:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            with pymupdf.open(path) as src:
                dossier.insert_pdf(src)
        elif suffix in IMAGE_SUFFIXES:
            page = dossier.new_page(width=595, height=842)
            page.insert_image(page.rect + (28, 28, -28, -28), filename=str(path), keep_proportion=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dossier.save(out_path)
    dossier.close()
    return out_path


def dossier_attachments() -> list[Path]:
    """Zeugnisse und Diplome, die ins Dossier übernommen werden können (PDF und Bilder)."""
    return [
        p for k in ("zeugnisse", "diplome") for p in list_documents(k)
        if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGE_SUFFIXES
    ]
