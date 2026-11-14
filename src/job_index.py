"""Stellen-Datenbank: alle Stellen, die das Tool kennt, in einem Index mit Bedeutungssuche.

Quellen: Tracker, Firmenseiten, gespeicherte Suchen und (solange die Sitzung läuft) die Jobportale.
Pro Stelle gibt es einen Vektor für die ganze Anzeige und je einen pro Abschnitt (Aufzählungspunkt/Satz).
- Freitextsuche: Ähnlichkeit der Anfrage mit der Anzeige und mit ihrem besten Abschnitt (zeigt, was passt)
- Ähnliche Stellen: Ähnlichkeit der ganzen Anzeigen
- Doppelte: fast gleicher Anzeigentext und ähnlicher Titel, z.B. dieselbe Stelle bei jobs.ch und auf der Firmenseite
Die Vektoren liegen dauerhaft in src.vectors; eine schon gesehene Anzeige kostet nichts mehr.
"""
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from src import company_jobs, db, quality, searches, task_search

JOB_TEXT = 4000            # Zeichen pro Anzeige für den Gesamtvektor
MIN_TEXT = 150             # darunter gilt eine Stelle als «nur Titel»
# Kosinus-Ähnlichkeit (text-embedding-3-small) → Anzeige in Prozent
SEARCH_MIN, SEARCH_MAX = 0.20, 0.60
SEARCH_CUTOFF = 0.33       # darunter kaum verwandt
DUPLICATE_TEXT = 0.92      # Gesamtvektoren fast gleich und derselbe Titel (title_norm): Firmen nutzen für
                           # alle Stellen dieselbe Vorlage, darum reicht der Text allein nicht
# Ähnliche Stellen: Abdeckung der eigenen Abschnitte (ohne Vorlagentext), bei kurzen Anzeigen die ganze Anzeige
CONTENT_MIN, CONTENT_MAX = 0.38, 0.60
WHOLE_MIN, WHOLE_MAX = 0.50, 0.80
MIN_OWN_CHUNKS = 3
BOILERPLATE_MIN = 3        # derselbe Abschnitt in so vielen Anzeigen = Vorlagentext
HIDDEN = {"verworfen", "ausgeschlossen", "zu_weit"}
SOURCE_ORDER = ["Tracker", "Firmenseite", "Gespeicherte Suche", "Jobportale"]


# ---------------------------------------------------------------- Stellen sammeln

def _record(job: dict, source: str, status: str = "", score=None, **extra) -> dict | None:
    url, description = job.get("url") or "", job.get("description") or ""
    title = (job.get("title") or "").strip()
    if not title and len(description) < MIN_TEXT:
        return None
    return {"key": quality.job_key(url, description), "url": url, "title": title,
            "company": (job.get("company") or "").strip(), "location": (job.get("location") or "").strip(),
            "description": description, "quelle": source, "quellen": [source], "status": status,
            "score": score, "nur_titel": len(description) < MIN_TEXT, **extra}


def collect(portal_items: list[dict] | None = None) -> list[dict]:
    """Alle bekannten Stellen, gleiche Adresse nur einmal (Quellen werden zusammengefasst)."""
    found = []
    for app in db.list_applications():
        found.append(_record(app, "Tracker", app.get("status") or "", app.get("score"), app_id=app["id"]))
    for job in company_jobs.load().get("stellen", {}).values():
        found.append(_record(job, "Firmenseite", job.get("status", ""), (job.get("analysis") or {}).get("score"),
                             distanz_km=job.get("distanz_km")))
    for entry in searches.load_results().values():
        for job in entry.get("ergebnisse", []):
            found.append(_record(job, "Gespeicherte Suche", "", (job.get("analysis") or {}).get("score")))
    for job in portal_items or []:
        found.append(_record(job, "Jobportale", "", (job.get("analysis") or {}).get("score")))

    merged: dict[str, dict] = {}
    for record in filter(None, found):
        known = merged.get(record["key"])
        if not known:
            merged[record["key"]] = record
            continue
        known["quellen"] = list(dict.fromkeys(known["quellen"] + record["quellen"]))
        for name in ("title", "company", "location", "description"):
            if len(record[name]) > len(known[name]):
                known[name] = record[name]
        known["nur_titel"] = len(known["description"]) < MIN_TEXT
        if known["score"] is None:
            known["score"] = record["score"]
        known.update({k: v for k, v in record.items() if k in ("app_id", "distanz_km") and v is not None})
    records = list(merged.values())
    for record in records:
        record["quelle"] = min(record["quellen"], key=SOURCE_ORDER.index)
        record["ausgeblendet"] = record["status"] in HIDDEN and "Tracker" not in record["quellen"]
    return records


# ---------------------------------------------------------------- Index

def job_text(record: dict) -> str:
    head = " · ".join(x for x in (record["title"], record["company"]) if x)
    return f"{head}\n{record['description'][:JOB_TEXT]}".strip()


def job_chunks(record: dict) -> list[str]:
    # Gleiche Zerlegung wie die Aufgaben-Nähe: dieselben Abschnitte sind dann schon gespeichert
    return task_search.chunks(f"{record['title']}\n{record['description']}") or [record["title"]]


@dataclass
class Index:
    records: list[dict]
    jobs: np.ndarray                      # eine normierte Zeile pro Stelle
    chunks: np.ndarray                    # eine normierte Zeile pro Abschnitt
    owner: np.ndarray                     # zu welcher Stelle der Abschnitt gehört
    chunk_texts: list[str] = field(default_factory=list)
    boilerplate: np.ndarray | None = None  # Abschnitt steht wörtlich in mehreren Anzeigen (Firmenvorlage)
    groups: list | None = None            # Doppelte, einmal berechnet

    def position(self, key: str) -> int | None:
        return next((i for i, r in enumerate(self.records) if r["key"] == key), None)


def _normalized(rows) -> np.ndarray:
    matrix = np.asarray(rows, dtype=np.float32)
    return matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)


def build(records: list[dict]) -> Index | None:
    """Vektoren für alle Stellen holen (bekannte aus dem Speicher). None ohne Embedding-Anbieter."""
    if not records:
        return None
    texts = [job_text(r) for r in records]
    pieces = [job_chunks(r) for r in records]
    flat = [p for group in pieces for p in group]
    vectors = task_search.embed(list(dict.fromkeys(texts + flat)))
    if vectors is None:
        return None
    lookup = dict(zip(dict.fromkeys(texts + flat), vectors))
    owner = np.array([i for i, group in enumerate(pieces) for _ in group])
    frequency = Counter(p for group in pieces for p in set(group))
    boilerplate = np.array([frequency[p] >= BOILERPLATE_MIN for p in flat])
    return Index(records, _normalized([lookup[t] for t in texts]), _normalized([lookup[p] for p in flat]),
                 owner, flat, boilerplate)


def percent(similarity: float, low: float = SEARCH_MIN, high: float = SEARCH_MAX) -> int:
    return round(100 * min(1.0, max(0.0, (similarity - low) / (high - low))))


def _best_chunks(index: Index, query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pro Stelle: höchste Ähnlichkeit eines Abschnitts und dessen Nummer."""
    sims = index.chunks @ query
    best = np.full(len(index.records), -1.0)
    where = np.zeros(len(index.records), dtype=int)
    for c, (job, sim) in enumerate(zip(index.owner, sims)):
        if sim > best[job]:
            best[job], where[job] = sim, c
    return best, where


def _visible(record: dict, show_hidden: bool) -> bool:
    return show_hidden or not record["ausgeblendet"]


def search(index: Index, query: str, limit: int = 30, show_hidden: bool = False) -> list[dict]:
    """Freitextsuche nach Bedeutung. Treffer: {**stelle, aehnlichkeit, prozent, passender_abschnitt}."""
    vectors = task_search.embed([query.strip()])
    if not vectors:
        return []
    q = _normalized([vectors[0]])[0]
    whole = index.jobs @ q
    best, where = _best_chunks(index, q)
    # Abschnitt zählt mehr: kurze Anfragen treffen meist einen Teil der Anzeige, nicht das Ganze
    combined = 0.4 * whole + 0.6 * np.maximum(best, whole)

    def matching_part(i):  # nur zeigen, wenn es mehr sagt als der Titel
        text = index.chunk_texts[where[i]]
        return text if best[i] > whole[i] and text.strip() != index.records[i]["title"].strip() else ""

    return _results(index, combined, show_hidden, limit, matching_part)


def like_examples(index: Index, examples: list[str], limit: int = 30, show_hidden: bool = False,
                  exclude: set[str] | None = None) -> list[dict]:
    """Stellen, die einer Gruppe von Beispiel-Anzeigen (z.B. deinen 👍) am ähnlichsten sind."""
    vectors = task_search.embed(examples) if examples else None
    if not vectors:
        return []
    centre = _normalized([np.mean(_normalized(vectors), axis=0)])[0]
    sims = index.jobs @ centre
    exclude = exclude or set()
    for i, record in enumerate(index.records):
        if record["key"] in exclude:
            sims[i] = -1
    return _results(index, sims, show_hidden, limit)


def similar(index: Index, key: str, limit: int = 10, show_hidden: bool = True) -> list[dict]:
    """Ähnlichste andere Stellen zu einer Stelle (ohne ihre Doppelten)."""
    i = index.position(key)
    if i is None:
        return []
    content = _content_match(index, i)
    if content is None:  # kurze Anzeige: ganze Anzeigen vergleichen
        sims, low, high = index.jobs @ index.jobs[i], WHOLE_MIN, WHOLE_MAX
    else:
        sims, low, high = content, CONTENT_MIN, CONTENT_MAX
    for j in [i] + [index.position(r["key"]) for r in duplicates_of(index, key)]:
        sims[j] = -1
    return [{**r, "prozent": percent(r["aehnlichkeit"], low, high)}
            for r in _results(index, sims, show_hidden, limit, cutoff=low)]


def _content_match(index: Index, i: int) -> np.ndarray | None:
    """Pro Stelle: Mittel über die eigenen Abschnitte, wie gut die andere Anzeige sie jeweils abdeckt.

    Wörtlich wiederkehrende Abschnitte (Firmenvorstellung, Benefits) zählen nicht – sonst wären alle
    Stellen derselben Firma einander am ähnlichsten. None bei zu wenig eigenem Text."""
    mine = np.flatnonzero((index.owner == i) & ~index.boilerplate)
    if len(mine) < MIN_OWN_CHUNKS:
        return None
    sims = index.chunks[mine] @ index.chunks.T
    sims[:, index.boilerplate] = -1.0
    starts = np.r_[0, np.flatnonzero(np.diff(index.owner)) + 1]
    best = np.full((len(mine), len(index.records)), -1.0, dtype=np.float32)
    best[:, index.owner[starts]] = np.maximum.reduceat(sims, starts, axis=1)
    return best.mean(axis=0)


def _results(index: Index, sims: np.ndarray, show_hidden: bool, limit: int, chunk_for=None,
             cutoff: float = SEARCH_CUTOFF) -> list[dict]:
    results, shown_groups = [], set()
    group_of = {r["key"]: n for n, group in enumerate(duplicate_groups(index)) for r in group}
    for i in np.argsort(-sims):
        record = index.records[i]
        if sims[i] < cutoff or len(results) >= limit:
            break
        group = group_of.get(record["key"])
        if not _visible(record, show_hidden) or group in shown_groups:
            continue  # von Doppelten nur die ähnlichste zeigen («auch unter …» nennt die anderen)
        if group is not None:
            shown_groups.add(group)
        results.append({**record, "aehnlichkeit": round(float(sims[i]), 3), "prozent": percent(float(sims[i])),
                        "passender_abschnitt": chunk_for(i) if chunk_for else ""})
    return results


# ---------------------------------------------------------------- Doppelte

_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_GENDER = re.compile(r"\b[mwfdxa]\s*/\s*[mwfdxa](\s*/\s*[mwfdxa])?\b|\*in\b|:in\b|/in\b|\(alle\)|\balle\b")
_PENSUM = re.compile(r"\d+\s*(-|–|bis)?\s*\d*\s*%")


def title_norm(title: str) -> str:
    """Titel ohne Klammern, Geschlechtsangaben und Pensum: «Engineer (m/w/d) 80-100 %» = «Engineer»."""
    text = unicodedata.normalize("NFKC", title or "").casefold()
    text = _PENSUM.sub(" ", _GENDER.sub(" ", _BRACKETS.sub(" ", text)))
    return " ".join(re.sub(r"[^\w+#]+", " ", text).split())


def duplicate_groups(index: Index) -> list[list[dict]]:
    """Gruppen derselben Stelle aus verschiedenen Quellen bzw. unter verschiedenen Adressen."""
    if index.groups is None:
        index.groups = _find_groups(index)
    return index.groups


def _find_groups(index: Index) -> list[list[dict]]:
    with_text = [i for i, r in enumerate(index.records) if not r["nur_titel"]]
    if len(with_text) < 2:
        return []
    sims = index.jobs[with_text] @ index.jobs[with_text].T
    parent = list(range(len(index.records)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in zip(*np.where(np.triu(sims, 1) >= DUPLICATE_TEXT)):
        ra, rb = index.records[with_text[a]], index.records[with_text[b]]
        if title_norm(ra["title"]) == title_norm(rb["title"]):
            parent[root(with_text[a])] = root(with_text[b])
    groups: dict[int, list[dict]] = {}
    for i in with_text:
        groups.setdefault(root(i), []).append(index.records[i])
    return sorted((g for g in groups.values() if len(g) > 1), key=len, reverse=True)


def duplicates_of(index: Index, key: str) -> list[dict]:
    for group in duplicate_groups(index):
        if any(r["key"] == key for r in group):
            return [r for r in group if r["key"] != key]
    return []
