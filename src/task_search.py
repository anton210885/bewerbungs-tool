"""Stellensuche nach Tätigkeiten statt Jobtiteln.

1. Die KI fasst die Aufgaben aus dem Profil zu Tätigkeitsfeldern zusammen und nennt pro Feld die Begriffe,
   die in Stellenanzeigen dafür stehen (Titel und Fachwörter). Diese gehen als Suchbegriffe an die Portale.
2. Gefundene Anzeigen werden nach Bedeutungs-Ähnlichkeit mit den eigenen Aufgaben vorsortiert (Embeddings);
   ohne Embedding-Anbieter nach gemeinsamen Wörtern.
"""
import math
import re
import unicodedata

import numpy as np
import requests

from src import config, cv_builder, vectors
from src.llm import chat_json

MAX_FIELDS = 8
MAX_TERMS_PER_FIELD = 6
MAX_SEARCH_TERMS = 8
# Kosinus-Ähnlichkeit (text-embedding-3-small): ab MATCH_THRESHOLD gilt ein Anzeigen-Abschnitt als abgedeckt;
# NAEHE_MIN..NAEHE_MAX wird auf 0-100 % «Aufgaben-Nähe» abgebildet (unter 0.40 ist praktisch unverwandt)
MATCH_THRESHOLD = 0.55
NAEHE_MIN, NAEHE_MAX = 0.40, 0.70
WORD_NAEHE_MAX = 0.6
TOP_K = 3
EMBEDDING_MODELS = {"openai": "text-embedding-3-small", "venice": "text-embedding-bge-m3"}

FIELDS_SYSTEM = """Du erhältst die nummerierten Aufgaben einer Person aus ihrem Lebenslauf.
Fasse sie zu 3 bis 8 Tätigkeitsfeldern zusammen. Nenne pro Feld 3 bis 6 kurze Suchbegriffe (1 bis 3 Wörter),
wie sie in Schweizer Stellenanzeigen für genau diese Tätigkeiten vorkommen: passende Jobtitel UND Fachbegriffe,
deutsch oder englisch, so wie Firmen sie schreiben.
Regeln:
- Nur Tätigkeiten, die durch die Aufgaben belegt sind. Erfinde keine Kenntnisse.
- Begriffe sollen auch Stellen mit anderem Titel finden (z.B. «Datenintegration» statt nur «Data Engineer»).
- Keine Füllwörter, keine ganzen Sätze, keine Firmennamen.
- Begriffe so spezifisch, dass sie Stellen auf dem Niveau der Person finden: keine allgemeinen Wörter wie
  «Kundendienst» oder «Support», wenn das nur eine Nebenaufgabe war, und keine Handwerksberufe für Bürotätigkeiten.
- Lange zurückliegende oder fachfremde Tätigkeiten in eigene Felder, damit man sie abwählen kann.
Gib JSON zurück:
{"felder": [{"name": "<kurzer Name des Tätigkeitsfelds>", "aufgaben": [<Nummern>],
             "suchbegriffe": ["...", "..."]}]}"""


# ---------------------------------------------------------------- Tätigkeitsfelder
def profile_tasks(profile: dict) -> list[str]:
    """Alle Aufgaben und Erfolge aus der Berufserfahrung, ohne Doppelte."""
    texts = [item["text"] for stelle in cv_builder.stellen_aufgaben(profile)
             for item in stelle["aufgaben"] + stelle["erfolge"]]
    return list(dict.fromkeys(t.strip() for t in texts if t and t.strip()))


def suggest_fields(profile: dict) -> list[dict]:
    tasks = profile_tasks(profile)
    if not tasks:
        raise ValueError("Im Profil stehen noch keine Aufgaben. Lade zuerst deinen Lebenslauf hoch.")
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(tasks))
    result = chat_json(FIELDS_SYSTEM, f"AUFGABEN:\n{listing}", temperature=0.2, max_tokens=3000)
    fields = []
    for entry in (result.get("felder") or [])[:MAX_FIELDS]:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            continue
        terms = _clean_terms(entry.get("suchbegriffe"))
        indices = [i for i in entry.get("aufgaben") or [] if isinstance(i, int) and 0 <= i < len(tasks)]
        if terms:
            fields.append({"name": str(entry["name"]).strip()[:60], "suchbegriffe": terms,
                           "aufgaben": [tasks[i] for i in dict.fromkeys(indices)]})
    if not fields:
        raise ValueError("Die KI hat keine Tätigkeitsfelder geliefert. Bitte nochmals versuchen.")
    return fields


def _clean_terms(values) -> list[str]:
    terms = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        term = " ".join(value.split()).strip("•-–,;. ")
        if term and len(term) <= 40 and term.casefold() not in {t.casefold() for t in terms}:
            terms.append(term)
    return terms[:MAX_TERMS_PER_FIELD]


def recent_fields(profile: dict, fields: list[dict], years: int = 6) -> list[str]:
    """Felder mit Aufgaben aus Stellen der letzten Jahre – als Vorauswahl (alte Berufe bleiben abgewählt)."""
    from datetime import date

    from src.matching import _month

    recent = set()
    for stelle in cv_builder.stellen_aufgaben(profile):
        end = _month(stelle["bis"], end=True) if stelle["bis"].strip() else float(date.today().year + 1)
        if end is not None and end >= date.today().year - years:
            recent |= {item["text"] for item in stelle["aufgaben"] + stelle["erfolge"]}
    chosen = [f["name"] for f in fields if any(t in recent for t in f.get("aufgaben") or [])]
    return chosen or [f["name"] for f in fields]


def search_terms(fields: list[dict], selected: list[str]) -> list[str]:
    """Suchbegriffe der gewählten Felder, abwechselnd pro Feld, damit jedes Feld vorkommt."""
    groups = [f["suchbegriffe"] for f in fields if f.get("name") in selected]
    ordered = [group[i] for i in range(max((len(g) for g in groups), default=0)) for group in groups if i < len(group)]
    seen, result = set(), []
    for term in ordered:
        if term.casefold() not in seen:
            seen.add(term.casefold())
            result.append(term)
    return result[:MAX_SEARCH_TERMS]


# ---------------------------------------------------------------- Ähnlichkeit
def _provider() -> str:
    url = config.LLM_BASE_URL.lower()
    return "venice" if "venice.ai" in url else "openai" if "api.openai.com" in url else ""


def embedding_model() -> str | None:
    return EMBEDDING_MODELS.get(_provider()) if config.LLM_API_KEY else None


def embed(texts: list[str]) -> list[np.ndarray] | None:
    """Embeddings über den eingestellten Anbieter; None, wenn keiner verfügbar ist oder der Aufruf scheitert.

    Bekannte Texte kommen aus dem dauerhaften Speicher (src.vectors) und kosten nichts."""
    model = embedding_model()
    if not model:
        return None
    known = vectors.get(model, texts)
    missing = list(dict.fromkeys(t for t in texts if t not in known))
    fetched: dict[str, list[float]] = {}
    try:
        for start in range(0, len(missing), 100):
            batch = missing[start:start + 100]
            resp = requests.post(f"{config.LLM_BASE_URL}/embeddings",
                                 headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                                 json={"model": model, "input": batch}, timeout=60)
            resp.raise_for_status()
            for text, entry in zip(batch, sorted(resp.json()["data"], key=lambda d: d["index"])):
                fetched[text] = entry["embedding"]
    except (requests.RequestException, KeyError, ValueError):
        vectors.put(model, fetched)  # schon Bezahltes nicht verlieren
        return None
    if missing:
        vectors.put(model, fetched)
        _record_usage(model, sum(len(t) for t in missing) // 4)
        known = vectors.get(model, texts)
    return [np.asarray(known[t], dtype=float) for t in texts]


def _record_usage(model: str, tokens: int) -> None:
    try:
        from src.costs import record_usage
        record_usage(model, tokens, 0)
    except Exception:
        pass


def _cosine_matrix(rows: list[list[float]], cols: list[list[float]]) -> np.ndarray:
    a, b = np.asarray(rows, dtype=float), np.asarray(cols, dtype=float)
    a /= np.linalg.norm(a, axis=1, keepdims=True) + 1e-12
    b /= np.linalg.norm(b, axis=1, keepdims=True) + 1e-12
    return b @ a.T  # Zeile = Anzeigen-Abschnitt, Spalte = eigene Aufgabe


_WORD = re.compile(r"[a-zäöüß0-9+#.]{3,}")
_STOP = {"und", "der", "die", "das", "mit", "für", "von", "den", "dem", "des", "ein", "eine", "einer", "auf", "aus",
         "bei", "sowie", "oder", "the", "and", "for", "with", "you", "your", "wir", "sie", "ihre", "unsere"}


def _words(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    return {w.strip(".") for w in _WORD.findall(text)} - _STOP


def _word_similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / math.sqrt(len(wa) * len(wb)) if wa and wb else 0.0


def chunks(text: str) -> list[str]:
    """Anzeigentext in Aufzählungspunkte bzw. Sätze zerlegen (die eigentlichen Aufgaben und Anforderungen)."""
    parts = re.split(r"\n+|(?<=[.!?])\s+(?=[A-ZÄÖÜ])|\s+[-•·]\s+", text or "")
    result = [" ".join(p.split()).strip("-•· ") for p in parts]
    return [p[:300] for p in result if len(p) >= 25][:30]


def selected_tasks(fields: list[dict], selected: list[str]) -> list[str]:
    """Aufgaben der gewählten Tätigkeitsfelder: nur damit wird verglichen, nicht mit abgewählten (z.B. alten Berufen)."""
    return list(dict.fromkeys(t for f in fields if f.get("name") in selected for t in f.get("aufgaben") or []))


def rank(profile: dict, items: list[dict], tasks: list[str] | None = None) -> list[dict]:
    """Sortiert Anzeigen nach Abdeckung durch eigene Aufgaben und legt pro Anzeige «aufgaben_match» ab.

    tasks: Vergleichsaufgaben (z.B. selected_tasks); ohne Angabe alle Aufgaben aus dem Profil."""
    tasks = tasks or profile_tasks(profile)
    if not tasks or not items:
        return items
    pieces = [chunks(f"{i.get('title', '')}\n{i.get('description', '')}") or [i.get("title", "")] for i in items]
    flat = [p for group in pieces for p in group]
    vectors = embed(tasks + flat)
    if vectors:
        matrix = _cosine_matrix(vectors[:len(tasks)], vectors[len(tasks):])
        threshold, method, low, high = MATCH_THRESHOLD, "Bedeutung", NAEHE_MIN, NAEHE_MAX
    else:
        matrix = np.array([[_word_similarity(t, piece) for t in tasks] for piece in flat])
        threshold, method, low, high = 0.2, "Wörter", 0.0, WORD_NAEHE_MAX
    position = 0
    for item, group in zip(items, pieces):
        rows = matrix[position:position + len(group)]
        position += len(group)
        best = [(float(row.max()), int(row.argmax())) for row in rows]
        covered = [b for b in best if b[0] >= threshold]
        strongest = sorted(best, reverse=True)[:TOP_K]
        matched_tasks = list(dict.fromkeys(tasks[ti] for score, ti in sorted(covered, reverse=True)))[:3]
        # Stärke = Mittel der besten Übereinstimmungen: hängt nicht davon ab, wie lang der geladene Text ist
        staerke = sum(s for s, _ in strongest) / len(strongest) if strongest else 0.0
        item["aufgaben_match"] = {
            "naehe": round(100 * min(1.0, max(0.0, (staerke - low) / (high - low)))),
            "staerke": round(staerke, 3), "abgedeckt": len(covered), "abschnitte": len(best),
            "passende_aufgaben": matched_tasks, "methode": method,
        }
    return sorted(items, key=lambda i: i["aufgaben_match"]["staerke"], reverse=True)
