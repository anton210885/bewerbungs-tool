"""KI-Analyse von Arbeitszeugnissen: Zeugnissprache entschlüsseln, Gesamtbild, Berichtigungsantrag."""
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pymupdf

from src import documents
from src.config import DATA_DIR
from src.generate import L, _localize
from src.llm import chat_json

OVERVIEW_PATH = DATA_DIR / "zeugnis_gesamtbild.json"
URTEILE = ["sehr gut", "gut", "befriedigend", "genügend", "ungenügend"]

ANALYSE_SYSTEM = f"""Du bist eine erfahrene HR-Fachfrau und Expertin für Arbeitszeugnisse auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Analysiere die Arbeitszeugnisse ehrlich und genau – zugunsten der Person, aber ohne Schönfärberei.

Wichtig für die Schweiz:
- Das Zeugnis muss nach OR Art. 330a wahr, wohlwollend und vollständig sein. Es gibt Vollzeugnisse
  (Leistung und Verhalten), Zwischenzeugnisse und reine Arbeitsbestätigungen (nur Funktion und Dauer).
- Die Zeugnissprache ist in der Schweiz weniger streng codiert als in Deutschland. Interpretiere nur,
  was wirklich auffällt, und sage es, wenn eine Formulierung neutral oder unklar ist.
  Steht im Zeugnis ausdrücklich «uncodiert» oder «transparent», nimm den Text wörtlich.
- Typische Signale: Zufriedenheitsskala («stets zu unserer vollsten Zufriedenheit» = sehr gut,
  «zu unserer vollen Zufriedenheit» = gut, «zu unserer Zufriedenheit» = genügend), «stets/jederzeit»,
  «bemüht», «im Grossen und Ganzen», «weitgehend», Reihenfolge Vorgesetzte vor Mitarbeitenden,
  fehlende Bereiche (z.B. kein Verhalten gegenüber Vorgesetzten oder Kunden), Austrittsgrund
  («auf eigenen Wunsch», Kündigung, Umstrukturierung), Schlussformel mit Bedauern, Dank und Zukunftswünschen,
  Ausstellungsdatum deutlich nach dem Austritt, Länge im Verhältnis zur Dauer der Anstellung.
- Erfinde keine Zitate. Zitiere wörtlich aus dem Text.

Die Datei kann mehrere Zeugnisse enthalten – analysiere NUR das Zeugnis, das im Auftrag genannt wird.
Halte dich kurz: höchstens 8 Bereiche, 8 entschlüsselte Sätze, je 5 Warnsignale und Tipps.
Antworte mit JSON:
{{
    "aussteller": "<Firma>",
    "typ": "<Arbeitszeugnis | Zwischenzeugnis | Arbeitsbestätigung | Anderes>",
    "funktion": "<Funktion der Person>",
    "zeitraum": "<MM/YYYY – MM/YYYY>",
    "ausgestellt": "<Datum des Zeugnisses oder leer>",
    "urteil": "<{' | '.join(URTEILE)}>",
    "punkte": <1-10, 10 = hervorragend>,
    "zusammenfassung": "<2-3 Sätze: was ein Personaler beim Lesen denkt>",
    "bereiche": [{{"bereich": "<Fachwissen | Arbeitsweise | Leistung | Erfolge | Verhalten | Führung | Schlussformel | Austrittsgrund>",
                  "urteil": "<{' | '.join(URTEILE)} | fehlt>", "beleg": "<wörtliches Zitat oder leer>"}}],
    "entschluesselt": [{{"zitat": "<wörtlich>", "bedeutung": "<was es im Klartext heisst>",
                        "wertung": "<positiv | neutral | negativ>"}}],
    "warnsignale": [{{"punkt": "...", "erklaerung": "<warum das ein Personaler bemerken könnte>",
                     "schwere": "<gering | mittel | hoch>"}}],
    "fehlt": ["<übliche Bestandteile, die fehlen>"],
    "formales": ["<formale Mängel: Datum, Unterschrift, Tippfehler, Briefpapier – sonst leer>"],
    "beste_zitate": ["<1-3 wörtliche Sätze, die sich für Bewerbungsschreiben oder Gespräch eignen>"],
    "gespraechstipps": ["<wie man heikle Punkte im Vorstellungsgespräch souverän anspricht>"],
    "berichtigung_empfohlen": <true | false>,
    "berichtigung_grund": "<nur wenn empfohlen: was korrigiert werden sollte>"
}}"""

SPLIT_SYSTEM = """Die Datei enthält ein oder mehrere Arbeitszeugnisse, Arbeitsbestätigungen oder ähnliche Dokumente.
Liste jedes einzelne Dokument auf, neuestes zuerst. Erfinde nichts. Identische Kopien nur einmal aufführen;
Zwischen- und Schlusszeugnis derselben Firma sind aber zwei Dokumente.
Die Seiten sind mit «=== Seite N ===» markiert. Ordne jede Seite genau einem Dokument zu (auch Rückseiten,
Beilagen oder Seiten mit Firmenporträt); leere oder fremde Seiten darfst du weglassen.
Antworte mit JSON: {"dokumente": [{"aussteller": "<Firma>", "typ": "<Arbeitszeugnis | Zwischenzeugnis | Arbeitsbestätigung | Anderes>",
  "funktion": "<Funktion>", "zeitraum": "<MM/YYYY – MM/YYYY>", "ausgestellt": "<Datum oder leer>",
  "seiten": [<Seitennummern>]}]}"""

OVERVIEW_SYSTEM = f"""Du bist eine erfahrene Karriereberaterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Du erhältst die Einzelanalysen aller Arbeitszeugnisse einer Person. Erstelle das Gesamtbild, wie es ein
Personaler beim Durchblättern des Dossiers wahrnimmt. Erfinde nichts.
Antworte mit JSON:
{{"gesamturteil": "<{' | '.join(URTEILE)}>",
  "punkte": <1-10>,
  "zusammenfassung": "<3-4 Sätze>",
  "roter_faden": ["<Eigenschaften, die in mehreren Zeugnissen wiederkehren>"],
  "entwicklung": "<wie sich die Beurteilungen über die Zeit entwickeln>",
  "staerken": ["..."],
  "schwachpunkte": ["..."],
  "top_zitate": [{{"zitat": "<wörtlich>", "quelle": "<Firma>"}}],
  "dossier": [{{"aussteller": "<Firma>", "empfehlung": "<unbedingt beilegen | beilegen | weglassen prüfen>",
               "grund": "..."}}],
  "naechste_schritte": ["<konkrete Empfehlungen, z.B. Berichtigung verlangen, Zwischenzeugnis anfordern>"]}}"""

CORRECTION_SYSTEM = f"""Du schreibst für eine Person auf dem {L["markt"]} Arbeitsmarkt eine höfliche, sachliche
Bitte an einen ehemaligen Arbeitgeber, das Arbeitszeugnis zu berichtigen. {L["stil"]}
Ton: freundlich, konstruktiv, nicht fordernd. Nenne konkret die Stellen und schlage Ersatzformulierungen vor,
die wahr bleiben (nichts erfinden, was die Analyse nicht stützt). Ein Hinweis auf OR Art. 330a nur dezent,
wenn überhaupt. Grussformel: «{L["gruss"]}».
Antworte mit JSON:
{{"betreff": "...",
  "text": "<vollständiger Brief bzw. E-Mail mit Anrede und Gruss>",
  "ersatz": [{{"bisher": "<wörtlich aus dem Zeugnis>", "vorschlag": "<neue Formulierung>"}}]}}"""


def _analysis_path(path: Path) -> Path:
    return path.with_name(path.name + documents.ANALYSIS_SUFFIX)


def load_analysis(path: Path) -> dict | None:
    cache = _analysis_path(path)
    return json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None


def analyze(path: Path, on_progress=None) -> dict:
    progress = on_progress or (lambda _msg: None)
    text = documents.get_text(path)
    found = chat_json(SPLIT_SYSTEM, f"Datei: {path.name}\n\n{text}", temperature=0.0, max_tokens=2000)
    entries = found.get("dokumente") or [{"aussteller": "", "funktion": "", "zeitraum": ""}]
    progress(f"{len(entries)} Zeugnis(se) gefunden: {', '.join(d.get('aussteller') or '?' for d in entries)}")

    def one(doc: dict) -> dict:
        auftrag = (f"Analysiere das {doc.get('typ') or 'Zeugnis'} von {doc.get('aussteller')} ({doc.get('funktion')}, "
                   f"{doc.get('zeitraum')}, ausgestellt {doc.get('ausgestellt') or 'unbekannt'})."
                   if doc.get("aussteller") else "Analysiere das Zeugnis.")
        result = _localize(chat_json(ANALYSE_SYSTEM, f"{auftrag}\n\nDatei: {path.name}\n\n{text}",
                                     temperature=0.1, max_tokens=6000))
        return {**result, "seiten": [int(s) for s in doc.get("seiten", []) if str(s).isdigit()]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(one, doc): i for i, doc in enumerate(entries)}
        done: dict[int, dict] = {}
        for future in as_completed(futures):
            done[futures[future]] = future.result()
            progress(f"{len(done)}/{len(entries)} analysiert: {done[futures[future]].get('aussteller', '')}")
    result = {"zeugnisse": [done[i] for i in range(len(entries))]}
    result["erstellt"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    _analysis_path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def all_analyses() -> list[dict]:
    """Alle einzelnen Zeugnisse aus allen analysierten Dateien, mit Dateiname."""
    return [{**z, "datei": p.name}
            for p in documents.active_documents("zeugnisse")
            if (a := load_analysis(p))
            for z in a.get("zeugnisse", [])]


def _overview_key() -> list[str]:
    return sorted(f"{p.name}|{(load_analysis(p) or {}).get('erstellt', '')}"
                  for p in documents.active_documents("zeugnisse"))


def overview() -> dict:
    items = [{k: v for k, v in z.items() if k not in ("gespraechstipps", "formales")} for z in all_analyses()]
    result = _localize(chat_json(OVERVIEW_SYSTEM, json.dumps(items, ensure_ascii=False), temperature=0.2,
                                 max_tokens=6000))
    result["schluessel"] = _overview_key()
    result["erstellt"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    OVERVIEW_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_overview() -> dict | None:
    """Gespeichertes Gesamtbild – nur, wenn es zu den aktuellen Einzelanalysen passt."""
    if not OVERVIEW_PATH.exists():
        return None
    result = json.loads(OVERVIEW_PATH.read_text(encoding="utf-8"))
    return result if result.get("schluessel") == _overview_key() else None


def correction_request(profile: dict, zeugnis: dict, path: Path) -> dict:
    name = (profile.get("persoenlich") or {}).get("name", "")
    user = (f"PERSON: {name}\n\nANALYSE DES ZEUGNISSES:\n{json.dumps(zeugnis, ensure_ascii=False)}\n\n"
            f"ZEUGNISTEXT (Datei enthält evtl. mehrere Zeugnisse – nur das von {zeugnis.get('aussteller')}):\n"
            f"{documents.get_text(path)}")
    return _localize(chat_json(CORRECTION_SYSTEM, user, temperature=0.3, max_tokens=4000))


# ---------------------------------------------------------------- PDF bearbeiten
def page_count(path: Path) -> int:
    with pymupdf.open(path) as pdf:
        return pdf.page_count


def page_groups(path: Path) -> list[dict]:
    """Zeugnisse der Datei mit ihren Seiten; Seiten ohne Zuordnung kommen in eine eigene Gruppe am Ende."""
    analysis = load_analysis(path) or {}
    groups = [{"index": i, "aussteller": z.get("aussteller", ""), "typ": z.get("typ", ""),
               "zeitraum": z.get("zeitraum", ""), "urteil": z.get("urteil", ""), "seiten": z.get("seiten", [])}
              for i, z in enumerate(analysis.get("zeugnisse", []))]
    used = {s for g in groups for s in g["seiten"]}
    if rest := [s for s in range(1, page_count(path) + 1) if s not in used]:
        groups.append({"index": None, "aussteller": "Weitere Seiten (keinem Zeugnis zugeordnet)", "typ": "",
                       "zeitraum": "", "urteil": "", "seiten": rest})
    return groups


def end_date(zeitraum: str) -> tuple[int, int]:
    """Sortierschlüssel: Enddatum aus «MM/YYYY – MM/YYYY» (unbekannt = ganz alt)."""
    found = re.findall(r"(\d{1,2})/(\d{4})", zeitraum or "")
    return (int(found[-1][1]), int(found[-1][0])) if found else (0, 0)


def parse_pages(text: str, maximum: int) -> list[int]:
    """«1-3, 5» → [1, 2, 3, 5]; ungültige Angaben werden ignoriert."""
    pages: list[int] = []
    for part in re.split(r"[,;\s]+", text or ""):
        if m := re.fullmatch(r"(\d+)(?:-(\d+))?", part):
            a, b = int(m[1]), int(m[2] or m[1])
            pages += [p for p in range(a, b + 1) if 1 <= p <= maximum]
    return pages


def format_pages(pages: list[int]) -> str:
    ranges, start = [], None
    for i, p in enumerate(pages):
        start = p if start is None else start
        if i + 1 == len(pages) or pages[i + 1] != p + 1:
            ranges.append(f"{start}-{p}" if p != start else str(p))
            start = None
    return ", ".join(ranges)


def _safe(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\-. äöüÄÖÜ]+", "", name)).strip()[:60] or "Zeugnis"


def _unique(path: Path) -> Path:
    n = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate


def _write(src: pymupdf.Document, path: Path, groups: list[dict], texts: dict[int, str], analysis: dict) -> Path:
    new = pymupdf.open()
    page_texts, entries = [], []
    for g in groups:
        first = len(page_texts) + 1
        for s in g["seiten"]:
            new.insert_pdf(src, from_page=s - 1, to_page=s - 1)
            page_texts.append(texts.get(s, ""))
        if g.get("index") is not None:
            entries.append({**analysis["zeugnisse"][g["index"]],
                            "seiten": list(range(first, len(page_texts) + 1))})
    data = new.tobytes(garbage=3, deflate=True)
    new.close()
    path.write_bytes(data)
    documents._remove_helpers(path)
    if texts:
        documents.write_page_texts(path, page_texts)
    if entries:
        _analysis_path(path).write_text(json.dumps(
            {"zeugnisse": entries, "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M")},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def backup_dir() -> Path:
    return documents.DOCS_DIR / "zeugnisse" / "_original"


def list_backups() -> list[Path]:
    folder = backup_dir()
    return sorted(folder.glob("*.pdf"), reverse=True) if folder.exists() else []


def restore_backup(backup: Path) -> Path:
    name = re.sub(r"_\d{8}-\d{6}$", "", backup.stem) + backup.suffix
    target = _unique(documents.DOCS_DIR / "zeugnisse" / name)
    shutil.copy2(backup, target)
    return target


def save_edited(path: Path, groups: list[dict], mode: str) -> list[Path]:
    """mode: «ersetzen» (Original wird gesichert), «neu» (Original bleibt, wird nicht mehr verwendet)
    oder «einzeln» (jedes Zeugnis als eigene PDF, Original wird gesichert)."""
    groups = [g for g in groups if g["seiten"]]
    if not groups:
        raise ValueError("Es ist kein Zeugnis mit Seiten ausgewählt.")
    analysis = load_analysis(path) or {"zeugnisse": []}
    texts = documents.page_texts(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    src = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
    if mode in ("ersetzen", "einzeln"):
        backup_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_dir() / f"{path.stem}_{stamp}{path.suffix}")

    if mode == "ersetzen":
        written = [_write(src, path, groups, texts, analysis)]
    elif mode == "neu":
        written = [_write(src, _unique(path.with_name(f"{path.stem}_bearbeitet.pdf")), groups, texts, analysis)]
        documents.set_excluded(path, True)
    elif mode == "einzeln":
        written = [
            _write(src, _unique(path.with_name(f"{n:02d}_{_safe(g['aussteller'])}.pdf")), [g], texts, analysis)
            for n, g in enumerate(groups, 1)
        ]
        path.unlink()
        documents._remove_helpers(path)
        documents.set_excluded(path, False)
    else:
        raise ValueError(f"Unbekannte Art: {mode}")
    src.close()
    return written


def interview_context() -> str:
    """Kurzfassung für die Gesprächsvorbereitung: heikle Punkte und gute Zitate aus den Zeugnissen."""
    lines = []
    for z in all_analyses():
        warn = [w["punkt"] for w in z.get("warnsignale", []) if w.get("schwere") in ("mittel", "hoch")]
        if warn or z.get("beste_zitate"):
            lines.append(f"- {z.get('aussteller')} ({z.get('urteil')}): heikel: {'; '.join(warn) or 'nichts'}; "
                         f"Zitate: {' / '.join(z.get('beste_zitate', [])[:2])}")
    return "\n".join(lines)
