"""Belegstellen (RAG) für die Bewertung: zu jeder Anforderung einer Anzeige die passendsten wörtlichen Auszüge
aus Lebenslauf, Arbeitszeugnissen und Diplomen.

Die Bewertung sieht sonst nur die Zusammenfassung im Profil; was allein in einem Zeugnis steht («hat die
ISO-9001-Zertifizierung geleitet»), fehlt ihr. Gesucht wird nach Bedeutung (Embeddings, dauerhaft gespeichert:
jeder Abschnitt kostet einmal unter 0.01 Rappen). Ohne Embedding-Anbieter gibt es keine Belegstellen und die
Bewertung läuft wie bisher.
"""
import re
import threading
from contextlib import contextmanager

import numpy as np

from src import documents, task_search

CHUNK_CHARS = 400          # ungefähr so lang wird ein Abschnitt (ganze Sätze)
MIN_CHUNK = 40             # kürzere Bruchstücke (Seitenzahlen, Adresszeilen) zählen nicht
PER_REQUIREMENT = 2        # so viele Auszüge pro Anforderung
MAX_EVIDENCE = 15          # höchstens so viele Auszüge pro Bewertung (ca. 6000 Zeichen)
MIN_SIMILARITY = 0.35      # darunter hat ein Auszug mit der Anforderung kaum etwas zu tun
SOURCES = {"lebenslauf": "Lebenslauf", "zeugnisse": "Arbeitszeugnis", "diplome": "Diplom/Zertifikat"}

_local = threading.local()


@contextmanager
def use_evidence(enabled: bool):
    """Für diesen Thread Belegstellen ein- oder ausschalten (A/B-Vergleich unter Matching-Qualität)."""
    previous = getattr(_local, "enabled", None)
    _local.enabled = enabled
    try:
        yield
    finally:
        _local.enabled = previous


def enabled() -> bool:
    value = getattr(_local, "enabled", None)
    return True if value is None else value


def split(text: str) -> list[str]:
    """Text in Abschnitte aus ganzen Sätzen von etwa CHUNK_CHARS Zeichen (ohne Seitenmarken)."""
    text = documents.PAGE_RE.sub("\n", text or "")
    sentences = [" ".join(s.split()) for s in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9«\"])|\n(?=\s*[-•·])", text)]
    result, current = [], ""
    for sentence in (s for s in sentences if s):
        if current and len(current) + len(sentence) > CHUNK_CHARS:
            result.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        result.append(current)
    return [c[:CHUNK_CHARS * 2] for c in result if len(c) >= MIN_CHUNK]


def document_chunks() -> list[dict]:
    """Abschnitte aller verwendeten Unterlagen. Nur schon ausgelesene Texte (kein neues Auslesen, keine Kosten)."""
    chunks = []
    for kategorie, label in SOURCES.items():
        for path in documents.active_documents(kategorie):
            cache = documents._cache_path(path)
            if not cache.exists():
                continue
            source = f"{label} {path.stem}"
            chunks += [{"text": text, "quelle": source} for text in split(cache.read_text(encoding="utf-8"))]
    return list({c["text"]: c for c in chunks}.values())


def _normalized(rows) -> np.ndarray:
    matrix = np.asarray(rows, dtype=float)
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)


def find(requirements: list[str], chunks: list[dict] | None = None) -> list[dict]:
    """Zu den Anforderungen die passendsten Auszüge. -> [{"text", "quelle", "zu": [Anforderungen]}], die
    ähnlichsten zuerst; leer ohne Unterlagen oder Embedding-Anbieter."""
    requirements = list(dict.fromkeys(r.strip() for r in requirements if isinstance(r, str) and r.strip()))
    chunks = document_chunks() if chunks is None else chunks
    if not requirements or not chunks:
        return []
    vectors = task_search.embed(requirements + [c["text"] for c in chunks])
    if not vectors:
        return []
    sims = _normalized(vectors[:len(requirements)]) @ _normalized(vectors[len(requirements):]).T
    picked: dict[int, dict] = {}
    for r, row in enumerate(sims):
        for c in np.argsort(-row)[:PER_REQUIREMENT]:
            if row[c] < MIN_SIMILARITY:
                break
            entry = picked.setdefault(int(c), {**chunks[c], "zu": [], "aehnlichkeit": 0.0})
            entry["zu"].append(requirements[r])
            entry["aehnlichkeit"] = max(entry["aehnlichkeit"], float(row[c]))
    ordered = sorted(picked.values(), key=lambda e: e["aehnlichkeit"], reverse=True)[:MAX_EVIDENCE]
    return [{"text": e["text"], "quelle": e["quelle"], "zu": e["zu"]} for e in ordered]


def for_requirements(anforderungen: dict) -> list[dict]:
    """Belegstellen zu Muss-, Kann-Anforderungen und Aufgaben einer Anzeige (wenn eingeschaltet)."""
    if not enabled():
        return []
    wanted = [*(anforderungen.get("muss") or []), *(anforderungen.get("kann") or []),
              *(anforderungen.get("aufgaben") or [])]
    try:
        return find(wanted)
    except Exception:  # Belegstellen sind eine Hilfe; die Bewertung darf daran nicht scheitern
        return []


def prompt_section(evidence: list[dict]) -> str:
    lines = [f"- [{e['quelle']}] «{e['text']}» (zu: {'; '.join(e['zu'][:3])})" for e in evidence]
    return ("BELEGSTELLEN AUS DEN UNTERLAGEN (wörtliche Auszüge, nach Bedeutung zu den Anforderungen "
            "herausgesucht; nicht jeder Auszug passt wirklich):\n" + "\n".join(lines))


RULE = ("- BELEGSTELLEN sind wörtliche Auszüge aus Lebenslauf, Arbeitszeugnissen und Diplomen. Ein Auszug, der eine "
        "Anforderung wirklich belegt, zählt als Beleg wie eine Profilangabe: im Feld «beleg» kurz zitieren mit "
        "Quelle in eckigen Klammern. Passt ein Auszug nur dem Wort nach, ist er kein Beleg.")
