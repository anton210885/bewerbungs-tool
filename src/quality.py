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


def logic_version() -> str:
    """Prüfsumme der Bewertungslogik (Prompts, Regeln, Score-Berechnung): ändert sie sich, ist es eine neue Version."""
    import inspect

    from src import generate, matching
    parts = [inspect.getsource(matching), json.dumps(generate.L, ensure_ascii=False, sort_keys=True),
             inspect.getsource(generate._profile_for_llm)]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:8]


def _criteria_values(analysis: dict) -> dict:
    return {k: (v or {}).get("wert") for k, v in (analysis.get("kriterien") or {}).items()}


def _row(key: str, label: dict, analysis: dict) -> dict:
    return {
        "key": key, "title": label["title"], "company": label["company"], "url": label["url"],
        "einschaetzung": label["rating"], "rating": RATINGS[label["rating"]],
        "automatisch": label.get("automatisch", False), "score": int(analysis.get("score") or 0),
        "ko": bool(analysis.get("ko")), "ko_gruende": analysis.get("ko") or [],
        "score_damals": label.get("score_damals"), "fazit": analysis.get("fazit", ""),
        "staerken": (analysis.get("staerken") or [])[:3], "luecken": (analysis.get("luecken") or [])[:3],
        "kriterien": _criteria_values(analysis),
    }


def _compact(rows: list[dict]) -> list[dict]:
    """Das Nötigste pro Stelle, damit spätere Läufe Stelle für Stelle verglichen werden können."""
    return [{k: r[k] for k in ("key", "rating", "score", "ko", "kriterien")} for r in rows]


def evaluator(profile: dict, model: str | None = None):
    """Bewertungsfunktion wie in der Stellensuche (ohne Suchwünsche), auf Wunsch mit einem anderen Modell."""
    from src.models import use_model

    def evaluate(job: dict) -> dict:
        with use_model(model):
            return discovery.evaluate(profile, job)["analysis"]
    return evaluate


def _evaluate_all(labels: dict, evaluates: dict, on_progress=None) -> tuple[dict, dict]:
    """Jede Stelle mit jeder Variante bewerten (alles parallel). -> ({variante: rows}, {variante: fehler})."""
    rows = {name: [] for name in evaluates}
    errors = {name: [] for name in evaluates}
    total = len(labels) * len(evaluates)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fn, {"description": v["description"], "url": v["url"], "title": v["title"]}):
                   (name, k, v) for name, fn in evaluates.items() for k, v in labels.items()}
        for done, future in enumerate(as_completed(futures), 1):
            name, key, label = futures[future]
            try:
                rows[name].append(_row(key, label, future.result()))
            except Exception as error:  # einzelne Stelle darf den Lauf nicht abbrechen
                errors[name].append(f"{label['title'] or key}: {error}")
            if on_progress:
                on_progress(done, total, label)
    return rows, errors


def _save_run(run: dict) -> dict:
    runs = (load_runs() + [run])[-MAX_RUNS:]
    _write(runs_path(), runs)
    return run


def run_check(profile: dict, include_automatic: bool = True, on_progress=None, evaluate=None) -> dict:
    """Bewertet alle eingeschätzten Stellen neu (wie die Stellensuche, ohne Suchwünsche) und speichert den Lauf."""
    from src.llm import current_model
    model = current_model()
    rows, errors = _evaluate_all(selected(include_automatic), {"lauf": evaluate or evaluator(profile)}, on_progress)
    return _save_run(_make_run(profile, rows["lauf"], errors["lauf"], model, include_automatic))


def _make_run(profile: dict, rows: list[dict], errors: list[str], model: str, include_automatic: bool) -> dict:
    from src import matching
    return {"zeit": datetime.now().isoformat(timespec="minutes"), "modell": model, "logik": logic_version(),
            "gewichtung": matching.zielprofil(profile).get("gewichtung"),
            "mit_automatischen": include_automatic, "kennzahlen": metrics(rows), "fehler": errors,
            "zeilen": _compact(rows)}


# ---------------------------------------------------------------- A/B-Vergleich

BOOTSTRAP = 2000
CONFIDENT = 0.95  # so sicher muss der Bootstrap sein, um von «besser» oder «schlechter» zu sprechen
# Kennzahl: (Anzeigename, höher ist besser)
COMPARED = {"top_passt": (f"Top {TOP_K}: passt", True), "paar_treffer": ("Richtig sortiert", True),
            "rangkorrelation": ("Rangkorrelation", True), "falsche_ko": ("Falsche K.-o.", False)}


def ab_path():
    return config.data_dir() / "qualitaet_ab.json"


def load_ab() -> list[dict]:
    data = _read(ab_path(), [])
    return data if isinstance(data, list) else []


def _fast_ranks(values: np.ndarray) -> np.ndarray:
    order = values.argsort(kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(len(values), dtype=float)
    sorted_values = values[order]
    # Gleichstände: Mittelwert der Ränge
    boundaries = np.flatnonzero(np.diff(sorted_values)) + 1
    for group in np.split(np.arange(len(values)), boundaries):
        if len(group) > 1:
            ranks[order[group]] = ranks[order[group]].mean()
    return ranks


def _fast_metrics(score: np.ndarray, rating: np.ndarray, ko: np.ndarray) -> dict:
    """Die verglichenen Kennzahlen, schnell genug für tausende Bootstrap-Stichproben."""
    result = {}
    rs, rr = _fast_ranks(score), _fast_ranks(rating)
    result["rangkorrelation"] = (float(np.corrcoef(rs, rr)[0, 1]) if len(score) >= 3 and rs.std() and rr.std()
                                 else None)
    better = rating[:, None] > rating[None, :]
    pairs = better.sum()
    if pairs:
        diff = score[:, None] - score[None, :]
        result["paar_treffer"] = float(((diff > 0) & better).sum() + 0.5 * ((diff == 0) & better).sum()) / pairs
    else:
        result["paar_treffer"] = None
    top = np.argsort(-score, kind="mergesort")[:TOP_K]
    result["top_passt"] = float((rating[top] == 1.0).mean()) if len(top) else None
    result["falsche_ko"] = float((ko & (rating >= 0.5)).sum())
    return result


def _arrays(rows: list[dict]):
    return (np.array([r["score"] for r in rows], dtype=float), np.array([r["rating"] for r in rows], dtype=float),
            np.array([bool(r["ko"]) for r in rows]))


def compare(rows_a: list[dict], rows_b: list[dict], samples: int = BOOTSTRAP, seed: int = 7) -> dict:
    """Gepaarter Vergleich auf den Stellen, die beide Varianten bewertet haben.

    Bootstrap: die Stellen werden tausendfach neu gezogen (mit Zurücklegen); wie oft B besser ist, zeigt, ob der
    Unterschied an den Stellen hängt (Zufall) oder durchgehend besteht."""
    by_key = {r["key"]: r for r in rows_b}
    pairs = [(a, by_key[a["key"]]) for a in rows_a if a["key"] in by_key]
    a_rows, b_rows = [p[0] for p in pairs], [p[1] for p in pairs]
    result = {"gemeinsam": len(pairs), "genug": len(pairs) >= MIN_FOR_METRICS and len({r["rating"] for r in a_rows}) > 1,
              "kennzahlen": {}}
    if not pairs:
        return result
    sa, ra, ka = _arrays(a_rows)
    sb, rb, kb = _arrays(b_rows)
    base_a, base_b = _fast_metrics(sa, ra, ka), _fast_metrics(sb, rb, kb)
    rng = np.random.default_rng(seed)
    diffs = {name: [] for name in COMPARED}
    for _ in range(samples):
        pick = rng.integers(0, len(pairs), len(pairs))
        ma, mb = _fast_metrics(sa[pick], ra[pick], ka[pick]), _fast_metrics(sb[pick], rb[pick], kb[pick])
        for name in COMPARED:
            if ma[name] is not None and mb[name] is not None:
                diffs[name].append(mb[name] - ma[name])
    for name, (label, higher_better) in COMPARED.items():
        values = np.array(diffs[name])
        entry = {"name": label, "a": base_a[name], "b": base_b[name], "hoeher_besser": higher_better,
                 "diff": None if base_a[name] is None or base_b[name] is None else base_b[name] - base_a[name]}
        entry["urteil"] = None if result["genug"] else "zu wenig Stellen"
        if len(values) and entry["diff"] is not None:
            signed = values if higher_better else -values
            entry["p_besser"] = float((signed > 0).mean() + 0.5 * (signed == 0).mean())
            entry["bereich"] = [float(np.percentile(values, 5)), float(np.percentile(values, 95))]
            if result["genug"]:
                entry["urteil"] = ("B besser" if entry["p_besser"] >= CONFIDENT
                                   else "B schlechter" if entry["p_besser"] <= 1 - CONFIDENT
                                   else "kein klarer Unterschied")
        result["kennzahlen"][name] = entry
    return result


def _variant_name(variant: dict) -> str:
    return variant.get("name") or variant.get("modell") or "aktuell"


def run_ab(profile: dict, variant_a: dict, variant_b: dict, include_automatic: bool = True, on_progress=None,
           evaluators: dict | None = None) -> dict:
    """Beide Varianten bewerten dieselben Stellen im selben Lauf; Ergebnis und Vergleich werden gespeichert.

    variant: {"name": ..., "modell": <Modell-ID oder leer = eingestelltes>}. Gleiche Variante zweimal misst,
    wie stark die KI von sich aus schwankt (der Massstab für «echte» Unterschiede)."""
    from src.llm import current_model
    evaluators = evaluators or {"a": evaluator(profile, variant_a.get("modell")),
                                "b": evaluator(profile, variant_b.get("modell"))}
    from src import matching
    rows, errors = _evaluate_all(selected(include_automatic), evaluators, on_progress)
    result = {
        "zeit": datetime.now().isoformat(timespec="minutes"), "logik": logic_version(),
        "gewichtung": matching.zielprofil(profile).get("gewichtung"),
        "mit_automatischen": include_automatic,
        "a": {**variant_a, "name": _variant_name(variant_a), "modell": variant_a.get("modell") or current_model(),
              "kennzahlen": metrics(rows["a"]), "fehler": errors["a"], "zeilen": _compact(rows["a"])},
        "b": {**variant_b, "name": _variant_name(variant_b), "modell": variant_b.get("modell") or current_model(),
              "kennzahlen": metrics(rows["b"]), "fehler": errors["b"], "zeilen": _compact(rows["b"])},
        "vergleich": compare(rows["a"], rows["b"]),
    }
    _write(ab_path(), (load_ab() + [result])[-MAX_RUNS:])
    return result


def compare_runs(run_a: dict, run_b: dict) -> dict:
    """Zwei gespeicherte Prüfläufe Stelle für Stelle vergleichen (nur Läufe mit gespeicherten Zeilen)."""
    return compare(run_a.get("zeilen") or [], run_b.get("zeilen") or [])


def rescore(rows: list[dict], gewichtung: dict) -> list[dict]:
    """Scores mit anderen Gewichten neu rechnen – aus den gespeicherten Einzelwerten, ohne KI und ohne Kosten."""
    from src import matching
    result = []
    for row in rows:
        values = row.get("kriterien") or {}
        if not values:  # K.-o. ohne zweiten KI-Aufruf: kein Einzelwert, Score bleibt
            result.append(dict(row))
            continue
        criteria = {k: {"wert": values.get(k), "gewicht": float(gewichtung.get(k, 0))} for k in matching.GEWICHTUNG}
        score = matching.gesamtscore(criteria)
        if row["ko"]:
            score = min(score, matching.KO_MAX_SCORE)
        result.append({**row, "score": score})
    return result
