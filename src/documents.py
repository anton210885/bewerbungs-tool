import io
import json
import re
from datetime import datetime
from pathlib import Path

import docx
import pymupdf
from PIL import Image, ImageOps

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
MAX_CHARS_PER_DOC = 60000
MAX_OCR_PAGES = 30
OCR_BATCH = 4
ANALYSIS_SUFFIX = ".zeugnisanalyse.json"
PAGE_MARK = "=== Seite {n} ==="
PAGE_RE = re.compile(r"^[«*#\s]*=== Seite (\d+) ===[»*\s]*?$", re.M)

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


EXCLUDED_PATH = DOCS_DIR / "ausgeschlossen.json"
CV_COMPARE_PATH = DATA_DIR / "cv_vergleich.json"
_HELPER_SUFFIXES = (".extrahiert.txt", ".steckbrief.json", ANALYSIS_SUFFIX)

SUMMARY_SYSTEM = f"""Du erstellst einen kurzen Steckbrief zu einem Bewerbungsdokument.
{L["stil"]}
Antworte mit JSON:
{{"typ": "<Lebenslauf | Arbeitszeugnis | Zwischenzeugnis | Arbeitsbestätigung | Diplom | Zertifikat | Anderes>",
  "titel": "<kurzer Titel, z.B. «Arbeitszeugnis Odlo International AG» oder «Lebenslauf Anton Balandin»>",
  "aussteller": "<Firma, Schule oder Person – sonst leer>",
  "zeitraum": "<betroffener Zeitraum, z.B. «06/2022 – 07/2023», oder Jahr – sonst leer>",
  "stand": "<jüngstes Datum im Dokument als MM/YYYY – sonst leer>",
  "bewertung": "<nur bei Zeugnissen: «sehr gut», «gut», «genügend» oder «kritisch» mit kurzer Begründung – sonst leer>",
  "kernaussagen": ["<2-4 wichtigste Inhalte>"],
  "hinweise": ["<Auffälligkeiten, z.B. veraltet, unvollständig, schlecht lesbar, fehlendes Datum – sonst leer lassen>"]}}"""

CV_COMPARE_SYSTEM = f"""Du bist eine erfahrene Karriereberaterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Du erhältst mehrere Lebensläufe derselben Person. Vergleiche sie, damit die Person den Überblick behält:
welcher ist aktueller, was steht nur in einem davon, wo widersprechen sie sich (Daten, Titel, Firmen),
und welcher eignet sich besser als Grundlage. Erfinde nichts.
Antworte mit JSON:
{{"zusammenfassung": "<2-3 Sätze>",
  "dokumente": [{{"datei": "<Dateiname>", "stand": "<MM/YYYY>", "staerken": ["..."], "schwaechen": ["..."]}}],
  "nur_in": [{{"datei": "<Dateiname>", "inhalte": ["<was nur in diesem Lebenslauf steht>"]}}],
  "widersprueche": [{{"thema": "...", "details": "<was steht wo>"}}],
  "empfehlung": "<welchen als Grundlage verwenden bzw. ob beide zusammen sinnvoll sind, und warum>"}}"""


def save_upload(kategorie: str, filename: str, data: bytes) -> Path:
    folder = DOCS_DIR / kategorie
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-. äöüÄÖÜ]+", "_", Path(filename).name)
    path = folder / safe
    path.write_bytes(data)
    _remove_helpers(path)
    return path


def list_documents(kategorie: str) -> list[Path]:
    folder = DOCS_DIR / kategorie
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.endswith(_HELPER_SUFFIXES))


def active_documents(kategorie: str) -> list[Path]:
    """Dokumente, die für Profil, Analyse und Dossier verwendet werden (nicht ausgeschlossen)."""
    excluded = _load_excluded()
    return [p for p in list_documents(kategorie) if _doc_key(p) not in excluded]


def delete_document(path: Path) -> None:
    path.unlink(missing_ok=True)
    _remove_helpers(path)
    set_excluded(path, False)


def has_documents() -> bool:
    return any(active_documents(k) for k in KATEGORIEN)


def _remove_helpers(path: Path) -> None:
    _cache_path(path).unlink(missing_ok=True)
    _summary_path(path).unlink(missing_ok=True)
    path.with_name(path.name + ANALYSIS_SUFFIX).unlink(missing_ok=True)


def _doc_key(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _load_excluded() -> set[str]:
    return set(json.loads(EXCLUDED_PATH.read_text(encoding="utf-8"))) if EXCLUDED_PATH.exists() else set()


def is_excluded(path: Path) -> bool:
    return _doc_key(path) in _load_excluded()


def set_excluded(path: Path, excluded: bool) -> None:
    keys = _load_excluded()
    (keys.add if excluded else keys.discard)(_doc_key(path))
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    EXCLUDED_PATH.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2), encoding="utf-8")


def _summary_path(path: Path) -> Path:
    return path.with_name(path.name + ".steckbrief.json")


def load_summary(path: Path) -> dict | None:
    cache = _summary_path(path)
    return json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None


def summarize_document(path: Path) -> dict:
    result = chat_json(SUMMARY_SYSTEM, f"Dateiname: {path.name}\n\n{get_text(path)}", temperature=0.1,
                       max_tokens=1500)
    _summary_path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def document_info(path: Path) -> dict:
    stat = path.stat()
    pages = None
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as pdf:
            pages = pdf.page_count
    return {"groesse_kb": max(1, stat.st_size // 1024), "seiten": pages,
            "hochgeladen": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y")}


def document_thumbnail(path: Path, width: int = 220) -> bytes | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with pymupdf.open(path) as pdf:
            page = pdf[0]
            return page.get_pixmap(matrix=pymupdf.Matrix(width / page.rect.width, width / page.rect.width)).tobytes("png")
    if suffix in IMAGE_SUFFIXES:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        img.thumbnail((width, width * 2))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    return None


def extract_images(path: Path, min_side: int = 120) -> list[bytes]:
    """Holt eingebettete Bilder (z.B. das Bewerbungsfoto) aus PDF- und Word-Dateien.
    Kleine Bilder und Banner (Logos, Icons, Linien) werden weggelassen; grösste zuerst."""
    raw: list[bytes] = []
    suffix = path.suffix.lower()
    if suffix == ".docx":
        import zipfile

        with zipfile.ZipFile(path) as z:
            raw = [z.read(n) for n in z.namelist() if n.startswith("word/media/")]
    elif suffix == ".pdf":
        with pymupdf.open(path) as pdf:
            seen_xrefs = set()
            for page in pdf:
                for info in page.get_images(full=True):
                    xref = info[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        pix = pymupdf.Pixmap(pdf, xref)
                        if pix.n - pix.alpha >= 4 or pix.alpha:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        raw.append(pix.tobytes("png"))
                    except Exception:
                        continue
    elif suffix in IMAGE_SUFFIXES:
        raw = [path.read_bytes()]

    found: list[tuple[int, bytes]] = []
    seen = set()
    for data in raw:
        try:
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        except Exception:
            continue  # z.B. EMF/WMF-Grafiken
        w, h = img.size
        if min(w, h) < min_side or not 0.45 <= w / h <= 1.7:
            continue
        buf = io.BytesIO()
        img.save(buf, "PNG")
        png = buf.getvalue()
        if (digest := hash(png)) in seen:
            continue
        seen.add(digest)
        found.append((w * h, png))
    return [png for _, png in sorted(found, key=lambda x: -x[0])]


def cv_photo_candidates() -> list[tuple[str, bytes]]:
    """Mögliche Bewerbungsfotos aus allen hochgeladenen Lebensläufen: (Dateiname, Bild)."""
    return [(p.name, img) for p in list_documents("lebenslauf") for img in extract_images(p)]


def compare_cvs(paths: list[Path]) -> dict:
    sections = [f"=== Lebenslauf: {p.name} ===\n{get_text(p)}" for p in paths]
    result = chat_json(CV_COMPARE_SYSTEM, "\n\n".join(sections), temperature=0.2, max_tokens=6000)
    result["dateien"] = sorted(p.name for p in paths)
    result["erstellt"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    CV_COMPARE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_cv_comparison(paths: list[Path]) -> dict | None:
    """Gespeicherter Vergleich – nur, wenn er zu den aktuell hochgeladenen Lebensläufen passt."""
    if not CV_COMPARE_PATH.exists():
        return None
    result = json.loads(CV_COMPARE_PATH.read_text(encoding="utf-8"))
    return result if result.get("dateien") == sorted(p.name for p in paths) else None


def _cache_path(path: Path) -> Path:
    return path.with_name(path.name + ".extrahiert.txt")


def get_text(path: Path) -> str:
    cache = _cache_path(path)
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    text = _extract(path)[:MAX_CHARS_PER_DOC]
    cache.write_text(text, encoding="utf-8")
    return text


def _extract_pdf(path: Path) -> str:
    """Text-Seiten direkt lesen, gescannte Seiten in kleinen Paketen per KI erkennen (Reihenfolge bleibt)."""
    parts: list[str] = []
    scans: list[tuple[int, bytes]] = []

    def flush() -> None:
        if not scans:
            return
        numbers = [n for n, _ in scans]
        text = chat_images(
            OCR_SYSTEM,
            f"Transkribiere diese {len(scans)} Seiten in der gegebenen Reihenfolge. Es sind die Seiten "
            f"{', '.join(map(str, numbers))}. Beginne jede Seite mit einer eigenen Zeile «{PAGE_MARK.format(n='N')}» "
            f"(N = Seitennummer).",
            [img for _, img in scans],
        )
        if not PAGE_RE.search(text):
            text = f"{PAGE_MARK.format(n=numbers[0])}\n{text}"
        parts.append(text)
        scans.clear()

    with pymupdf.open(path) as pdf:
        for i, page in enumerate(pdf.pages(0, min(pdf.page_count, MAX_OCR_PAGES)), 1):
            text = page.get_text()
            if len(text.strip()) >= 80:
                flush()
                parts.append(f"{PAGE_MARK.format(n=i)}\n{text}")
            else:
                scans.append((i, page.get_pixmap(dpi=150).tobytes("png")))
                if len(scans) >= OCR_BATCH:
                    flush()
        flush()
    return "\n\n".join(parts)


def page_texts(path: Path) -> dict[int, str]:
    """Text je Seite (1-basiert) aus dem Zwischenspeicher – leer, wenn ohne Seitenmarken erkannt."""
    chunks = PAGE_RE.split(get_text(path))
    return {int(chunks[i]): chunks[i + 1].strip() for i in range(1, len(chunks) - 1, 2)}


def write_page_texts(path: Path, texts: list[str]) -> None:
    """Zwischenspeicher für eine neu zusammengestellte PDF schreiben (spart die erneute Texterkennung)."""
    _cache_path(path).write_text(
        "\n\n".join(f"{PAGE_MARK.format(n=i)}\n{t}" for i, t in enumerate(texts, 1)), encoding="utf-8")


def _extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
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
        for path in active_documents(kategorie):
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
    for path in active_documents("lebenslauf"):
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
        p for k in ("zeugnisse", "diplome") for p in active_documents(k)
        if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGE_SUFFIXES
    ]
