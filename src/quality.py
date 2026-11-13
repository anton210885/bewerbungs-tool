"""Qualität des Matchings messen: deine Einschätzungen gegen die Bewertung des Tools.

Du schätzt bewertete Stellen ein (passt / teilweise / passt nicht). Ein Prüflauf bewertet diese Stellen neu
und vergleicht. So lässt sich bei jeder Änderung am Matching sehen, ob es besser oder schlechter wird.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np

from src import config, discovery

RATINGS = {"passt": 1.0, "teilweise": 0.5, "passt_nicht": 0.0}
LABELS = {"passt": "👍 passt", "teilweise": "🤷 teilweise", "passt_nicht": "👎 passt nicht"}
MIN_TEXT = 150
MIN_FOR_METRICS = 10
TOP_K = 5
OUTLIER_GAP = 0.5  # z.B. «passt nicht» mit 50 % oder mehr, «passt» unter 50 %
MAX_RUNS = 20
WORKERS = 4


# ---------------------------------------------------------------- Speicherung

def labels_path():
    return config.data_dir() / "einschaetzungen.json"


def runs_path():
    return config.data_dir() / "qualitaet_laeufe.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def job_key(url: str, description: str) -> str:
    """Adresse, sonst Prüfsumme des Anzeigentexts (für eingefügte Texte ohne Link)."""
    if url:
        return discovery.canonical_url(url)
    return "text:" + hashlib.sha1((description or "")[:3000].encode("utf-8")).hexdigest()[:16]


def load_labels() -> dict:
    data = _read(labels_path(), {})
    return data if isinstance(data, dict) else {}


def get_label(url: str, description: str) -> dict | None:
    return load_labels().get(job_key(url, description))


def set_label(job: dict, analysis: dict | None, rating: str, source: str = "", automatic: bool = False) -> bool:
    """Speichert eine Einschätzung. Automatische (aus Übernehmen/Verwerfen) überschreiben nie eine eigene."""
    description = job.get("description") or ""
    if rating not in RATINGS or len(description) < MIN_TEXT:
        return False
    labels = load_labels()
    key = job_key(job.get("url", ""), description)
    if automatic and key in labels and not labels[key].get("automatisch"):
        return False
    analysis = analysis or {}
    labels[key] = {
        "url": job.get("url", ""), "title": job.get("title") or analysis.get("titel") or "",
        "company": job.get("company") or analysis.get("firma") or "", "description": description[:15000],
        "rating": rating, "automatisch": automatic, "quelle": source,
        "zeit": datetime.now().isoformat(timespec="minutes"),
        "score_damals": analysis.get("score"), "ko_damals": bool(analysis.get("ko")),
    }
    _write(labels_path(), labels)
    return True


def remove_label(key: str) -> None:
    labels = load_labels()
    if labels.pop(key, None) is not None:
        _write(labels_path(), labels)


def load_runs() -> list[dict]:
    data = _read(runs_path(), [])
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------- Kennzahlen

def _ranks(values) -> np.ndarray:
    """Ränge mit Mittelwert bei Gleichstand (wie bei Spearman üblich)."""
    values = np.asarray(values, dtype=float)
    order = values.argsort()
    ranks = np.empty(len(values))
    ranks[order] = np.arange(len(values), dtype=float)
    for value in np.unique(values):
        same = values == value
        ranks[same] = ranks[same].mean()
    return ranks


def spearman(a, b) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def pair_accuracy(rows: list[dict]) -> float | None:
    """Anteil der Paare mit unterschiedlicher Einschätzung, die das Tool richtig herum sortiert."""
    good = total = 0.0
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["rating"] == b["rating"]:
                continue
            better, worse = (a, b) if a["rating"] > b["rating"] else (b, a)
            total += 1
            good += 1 if better["score"] > worse["score"] else 0.5 if better["score"] == worse["score"] else 0
    return good / total if total else None


def metrics(rows: list[dict]) -> dict:
    """rows: [{rating (0/0.5/1), score (0-100), ko (bool), score_damals (int|None), ...}]"""
    result = {"n": len(rows), "genug": len(rows) >= MIN_FOR_METRICS and len({r["rating"] for r in rows}) > 1}
    by_class = {}
    for name, value in RATINGS.items():
        scores = [r["score"] for r in rows if r["rating"] == value]
        by_class[name] = {"anzahl": len(scores), "mittel": round(sum(scores) / len(scores)) if scores else None}
    result["nach_einschaetzung"] = by_class
    result["rangkorrelation"] = spearman([r["score"] for r in rows], [r["rating"] for r in rows])
    result["paar_treffer"] = pair_accuracy(rows)
    top = sorted(rows, key=lambda r: r["score"], reverse=True)[:TOP_K]
    result["top_passt"] = sum(1 for r in top if r["rating"] == 1.0) / len(top) if top else None
    result["top_brauchbar"] = sum(1 for r in top if r["rating"] >= 0.5) / len(top) if top else None
    result["falsche_ko"] = sum(1 for r in rows if r["ko"] and r["rating"] >= 0.5)
    drift = [abs(r["score"] - r["score_damals"]) for r in rows if isinstance(r.get("score_damals"), (int, float))]
    result["schwankung"] = round(sum(drift) / len(drift), 1) if drift else None
    outliers = [r for r in rows if abs(r["score"] / 100 - r["rating"]) >= OUTLIER_GAP or (r["ko"] and r["rating"] >= 0.5)]
    result["ausreisser"] = sorted(outliers, key=lambda r: abs(r["score"] / 100 - r["rating"]), reverse=True)
    return result


# ---------------------------------------------------------------- Prüflauf

def selected(include_automatic: bool = True) -> dict:
    return {k: v for k, v in load_labels().items() if include_automatic or not v.get("automatisch")}


def run_check(profile: dict, include_automatic: bool = True, on_progress=None, evaluate=None) -> dict:
    """Bewertet alle eingeschätzten Stellen neu (wie die Stellensuche, ohne Suchwünsche) und speichert den Lauf."""
    from src.llm import current_model
    evaluate = evaluate or (lambda job: discovery.evaluate(profile, job)["analysis"])
    labels = selected(include_automatic)
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(evaluate, {"description": v["description"], "url": v["url"], "title": v["title"]}):
                   (k, v) for k, v in labels.items()}
        for done, future in enumerate(as_completed(futures), 1):
            key, label = futures[future]
            try:
                analysis = future.result()
                rows.append({
                    "key": key, "title": label["title"], "company": label["company"], "url": label["url"],
                    "einschaetzung": label["rating"], "rating": RATINGS[label["rating"]],
                    "automatisch": label.get("automatisch", False), "score": int(analysis.get("score") or 0),
                    "ko": bool(analysis.get("ko")), "ko_gruende": analysis.get("ko") or [],
                    "score_damals": label.get("score_damals"), "fazit": analysis.get("fazit", ""),
                    "staerken": (analysis.get("staerken") or [])[:3], "luecken": (analysis.get("luecken") or [])[:3],
                })
            except Exception as error:  # einzelne Stelle darf den Lauf nicht abbrechen
                errors.append(f"{label['title'] or key}: {error}")
            if on_progress:
                on_progress(done, len(labels), label)
    run = {"zeit": datetime.now().isoformat(timespec="minutes"), "modell": current_model(),
           "mit_automatischen": include_automatic, "kennzahlen": metrics(rows), "fehler": errors}
    runs = (load_runs() + [run])[-MAX_RUNS:]
    _write(runs_path(), runs)
    return run
