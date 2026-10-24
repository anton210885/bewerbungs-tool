"""Gespeicherte Suchen: Übersichtsseiten regelmässig auf neue, passende Stellen prüfen."""
import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta

from src import batch, db
from src.config import DATA_DIR, ROOT

SEARCHES_PATH = DATA_DIR / "suchen.json"
SEEN_PATH = DATA_DIR / "gesehene_stellen.json"
RESULTS_PATH = DATA_DIR / "suchergebnisse.json"
TASK_NAME = "Bewerbungs-Tool Stellensuche"
DUE_AFTER = timedelta(hours=24)


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path, data) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_searches() -> list[dict]:
    return _read(SEARCHES_PATH, [])


def add_search(name: str, url: str, top_n: int = 5, detail_n: int = 10) -> None:
    searches = list_searches()
    searches.append({"id": uuid.uuid4().hex[:8], "name": name.strip() or url, "url": url.strip(),
                     "top_n": top_n, "detail_n": detail_n, "letzte_suche": None})
    _write(SEARCHES_PATH, searches)


def delete_search(search_id: str) -> None:
    _write(SEARCHES_PATH, [s for s in list_searches() if s["id"] != search_id])
    results = load_results()
    results.pop(search_id, None)
    _write(RESULTS_PATH, results)


def is_due(search: dict) -> bool:
    last = search.get("letzte_suche")
    return not last or datetime.now() - datetime.fromisoformat(last) >= DUE_AFTER


def load_results() -> dict:
    """{search_id: {"zeit": ..., "ergebnisse": [...], "neu_gefunden": n, "fehler": [...]}}"""
    return _read(RESULTS_PATH, {})


def run_search(profile: dict, search: dict, on_progress=None) -> dict:
    """Sucht auf der Seite nur nach Stellen, die noch nie geprüft wurden, und bewertet die besten."""
    progress = on_progress or (lambda _msg: None)
    progress(f"{search['name']}: Seite wird gelesen ...")
    found = batch.extract_jobs(search["url"])
    seen = set(_read(SEEN_PATH, []))
    known = {a["url"] for a in db.list_applications() if a.get("url")}
    new = [j for j in found if j["url"] not in seen and j["url"] not in known]
    progress(f"{search['name']}: {len(found)} Stellen gefunden, davon {len(new)} neu.")
    results, errors = [], []
    if new:
        chosen = batch.preselect(profile, new, search.get("detail_n", 10))
        progress(f"{search['name']}: {len(chosen)} neue Stellen werden im Detail geprüft ...")
        results, errors = batch.evaluate(profile, chosen, on_progress=progress)
    # Nur erfolgreich bewertete Treffer abschliessen; übrige später erneut prüfen.
    _write(SEEN_PATH, sorted(seen | {j["url"] for j in results}))

    entry = {"zeit": datetime.now().isoformat(timespec="minutes"), "neu_gefunden": len(new),
             "ergebnisse": results[: search.get("top_n", 5)], "fehler": errors}
    all_results = load_results()
    all_results[search["id"]] = entry
    _write(RESULTS_PATH, all_results)
    searches = list_searches()
    for s in searches:
        if s["id"] == search["id"]:
            s["letzte_suche"] = datetime.now().isoformat(timespec="seconds")
    _write(SEARCHES_PATH, searches)
    return entry


def run_all(profile: dict, only_due: bool = False, on_progress=None) -> list[str]:
    errors = []
    for search in list_searches():
        if only_due and not is_due(search):
            continue
        try:
            run_search(profile, search, on_progress)
        except Exception as e:
            errors.append(f"{search['name']}: {e}")
    return errors


def remove_result(search_id: str, url: str) -> None:
    results = load_results()
    if search_id in results:
        results[search_id]["ergebnisse"] = [r for r in results[search_id]["ergebnisse"] if r["url"] != url]
        _write(RESULTS_PATH, results)


# ---------------------------------------------------------------- Windows-Aufgabenplanung
SCHEDULING_AVAILABLE = sys.platform == "win32"


def _task_command() -> str:
    python = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not python.exists():
        python = sys.executable
    return f'"{python}" "{ROOT / "suche_taeglich.py"}"'


def schedule_daily(time_hhmm: str = "08:00") -> None:
    if not SCHEDULING_AVAILABLE:
        raise RuntimeError("Die tägliche automatische Suche gibt es nur unter Windows.")
    result = subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", time_hhmm, "/TN", TASK_NAME,
                             "/TR", _task_command()], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def unschedule() -> None:
    if not SCHEDULING_AVAILABLE:
        return
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], capture_output=True, text=True)


def scheduled_time() -> str | None:
    if not SCHEDULING_AVAILABLE:
        return None
    result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"],
                            capture_output=True, text=True, encoding="cp850", errors="ignore")
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.strip().lower().startswith(("start time", "startzeit")):
            return line.split(":", 1)[1].strip()
    return "eingerichtet"
