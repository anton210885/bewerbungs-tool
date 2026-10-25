"""Original-Lebenslauf (Word) verbessern, ohne das Layout neu zu bauen."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from src import documents
from src.llm import chat_json

PATCH_SYSTEM = """Du verbesserst einen bestehenden Lebenslauf in Word.
Du erhältst die Absätze des Dokuments (Nummer + Text) und ausgewählte Verbesserungen.
Strenge Regeln:
- Erfinde keine Fakten (keine neuen Firmen, Daten, Tools, Zahlen, Erfolge).
- Ändere nur Absätze, die von den Verbesserungen betroffen sind.
- Behalte die Sprache und den Stil des Dokuments.
- Stichpunkte bleiben Stichpunkte (kein Fliesstext daraus machen).
- Absätze die unverändert bleiben: nicht in "aenderungen" aufführen.
Gib JSON zurück:
{
  "aenderungen": [{"index": <Absatz-Nummer>, "neu": "<neuer Text>"}, ...],
  "zusammenfassung": ["<kurze Beschreibung jeder Änderung>", ...],
  "offene_fragen": ["<Frage, falls Infos fehlen>", ...]
}
"""


def original_cv_docx() -> Path | None:
    """Ersten aktiven Lebenslauf als .docx zurückgeben (falls vorhanden)."""
    for path in documents.active_documents("lebenslauf"):
        if path.suffix.lower() == ".docx":
            return path
    return None


def original_cv_pdf_only() -> bool:
    docs = documents.active_documents("lebenslauf")
    return bool(docs) and original_cv_docx() is None and any(p.suffix.lower() == ".pdf" for p in docs)


def extract_paragraphs(path: Path) -> list[dict]:
    doc = Document(str(path))
    out = []
    for i, p in enumerate(doc.paragraphs):
        text = (p.text or "").strip()
        if text:
            out.append({"index": i, "text": text})
    return out


def _set_paragraph_text(paragraph, text: str) -> None:
    """Ersetzt den Absatztext und behält Formatierung des ersten Runs soweit möglich."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    # Format des ersten Runs merken
    first = runs[0]
    bold, italic = first.bold, first.italic
    size = first.font.size
    color = first.font.color.rgb if first.font.color and first.font.color.rgb else None
    name = first.font.name
    # Alle Runs leeren, Text in den ersten schreiben
    first.text = text
    for run in runs[1:]:
        run.text = ""
    first.bold, first.italic = bold, italic
    if size:
        first.font.size = size
    if color is not None:
        first.font.color.rgb = color
    if name:
        first.font.name = name
        rpr = first._element.get_or_add_rPr()
        rfonts = rpr.get_or_add_rFonts()
        rfonts.set(qn("w:eastAsia"), name)


def apply_paragraph_updates(src: Path, updates: dict[int, str], dest: Path) -> Path:
    doc = Document(str(src))
    for idx, new_text in updates.items():
        if 0 <= idx < len(doc.paragraphs):
            _set_paragraph_text(doc.paragraphs[idx], new_text)
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dest))
    return dest


def improve_original_docx(path: Path, points: list[str], extra: str = "") -> dict:
    """KI schlägt Textänderungen vor und schreibt eine angepasste Word-Kopie."""
    paragraphs = extract_paragraphs(path)
    if not paragraphs:
        raise ValueError("Im Word-Lebenslauf wurden keine Textabsätze gefunden.")
    wishes = "\n".join(f"- {p}" for p in points)
    if extra.strip():
        wishes += f"\n- {extra.strip()}"
    listed = "\n".join(f"[{p['index']}] {p['text']}" for p in paragraphs)
    user = (
        f"ORIGINAL-ABSÄTZE:\n{listed}\n\n"
        f"AUSGEWÄHLTE VERBESSERUNGEN:\n{wishes}\n\n"
        "Ändere nur betroffene Absätze. Behalte Layout-Struktur (Absatzgrenzen)."
    )
    result = chat_json(PATCH_SYSTEM, user, temperature=0.2, max_tokens=12000)
    updates: dict[int, str] = {}
    for item in result.get("aenderungen") or []:
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        neu = str(item.get("neu") or "").strip()
        if not neu:
            continue
        # Zeilenumbrüche in Absätzen vermeiden (Word-Absatz = eine Zeile)
        neu = re.sub(r"\s*\n\s*", " ", neu)
        updates[idx] = neu
    if not updates:
        raise ValueError("Die KI hat keine konkreten Textänderungen vorgeschlagen. "
                         "Evtl. fehlen Infos – siehe offene Fragen.")
    from src import config
    dest = config.output_dir() / "basis" / f"{path.stem}_verbessert.docx"
    apply_paragraph_updates(path, updates, dest)
    return {
        "docx": str(dest),
        "updates": updates,
        "zusammenfassung": result.get("zusammenfassung") or [],
        "offene_fragen": result.get("offene_fragen") or [],
        "punkte": [*points, *([extra.strip()] if extra.strip() else [])],
        "quelle": str(path),
    }
