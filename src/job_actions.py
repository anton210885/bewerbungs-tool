"""Bewerten, übernehmen und verwerfen – gleich für jede Stelle der Stellen-Datenbank, egal woher sie stammt.

Eine Stelle (Datensatz aus job_index.collect) kann aus mehreren Quellen kommen; das Ergebnis wird überall
gespeichert, wo sie liegt: Firmenseiten (company_jobs), Jobportal-Treffer (discovery) und gespeicherte Suchen.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from src import company_jobs, db, discovery, quality, searches

EVAL_WORKERS = 4


def can_evaluate(record: dict) -> bool:
    return not record["nur_titel"] and len(record["description"]) >= company_jobs.MIN_TEXT


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _matches(record: dict, job: dict) -> bool:
    return quality.job_key(job.get("url") or "", job.get("description") or "") == record["key"]


def _update_sources(record: dict, analysis: dict | None = None, status: str | None = None) -> None:
    """Bewertung bzw. Status bei allen Quellen der Stelle ablegen."""
    if "Firmenseite" in record["quellen"]:
        store = company_jobs.load()
        for job in store["stellen"].values():
            if _matches(record, job):
                if analysis is not None:
                    job.update(analysis=analysis, bewertet=_now())
                    if job.get("status") == "neu":
                        job["status"] = "bewertet"
                if status:
                    job["status"] = status
        company_jobs.save(store)
    if "Jobportale" in record["quellen"]:
        items = discovery.load_portal_items()
        for item in items:
            if _matches(record, item):
                if analysis is not None:
                    item["analysis"] = analysis
                if status:
                    item["status"] = status
        discovery.save_portal_items(items)
    if status and "Gespeicherte Suche" in record["quellen"]:
        for search_id, entry in searches.load_results().items():
            for job in entry.get("ergebnisse", []):
                if _matches(record, job):
                    searches.remove_result(search_id, job["url"])


def evaluate(record: dict, profile: dict, wishes: str = "") -> dict:
    """Mit dem Profil bewerten (KI, ca. 3 Rappen) und speichern. -> analysis"""
    analysis = discovery.evaluate(profile, record, wishes)["analysis"]
    _update_sources(record, analysis=analysis)
    if record.get("app_id"):
        import json
        db.update_application(record["app_id"], score=analysis["score"],
                              analysis=json.dumps(analysis, ensure_ascii=False))
    record["analysis"], record["score"] = analysis, analysis.get("score")
    return analysis


def evaluate_many(records: list[dict], profile: dict, wishes: str = "", on_progress=None) -> list[str]:
    """Mehrere Stellen parallel bewerten. -> Fehlermeldungen"""
    errors = []
    with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as pool:
        futures = {pool.submit(discovery.evaluate, profile, r, wishes): r for r in records}
        results = []
        for done, future in enumerate(as_completed(futures), 1):
            record = futures[future]
            try:
                results.append((record, future.result()["analysis"]))
            except Exception as error:
                errors.append(f"{record['title']}: {error}")
            if on_progress:
                on_progress(done, len(records), record)
    for record, analysis in results:  # speichern nacheinander: dieselben Dateien
        _update_sources(record, analysis=analysis)
        record["analysis"], record["score"] = analysis, analysis.get("score")
    return errors


def take_over(record: dict, store_job) -> int:
    """In den Tracker übernehmen. store_job: ui.helpers.store_job (mit Bewertung). -> Tracker-ID"""
    if record.get("app_id"):
        return record["app_id"]
    meta = {"source": record["quelle"], "external_id": record["url"] or record["key"],
            "company": record["company"], "location": record["location"]}
    if record.get("analysis"):
        app_id = store_job(record["url"], record, record["analysis"], meta)
        quality.set_label(record, record["analysis"], "passt", record["quelle"], automatic=True)
    else:
        app_id = db.add_application({**meta, "title": record["title"], "url": record["url"],
                                     "description": record["description"]})
        if not app_id:
            found = db.find_application(meta["source"], meta["external_id"])
            app_id = found["id"] if found else None
    _update_sources(record, status="übernommen")
    return app_id


def dismiss(record: dict) -> None:
    """«Interessiert mich nicht»: verschwindet aus der Liste und kommt bei der nächsten Suche nicht wieder."""
    if record.get("analysis"):
        quality.set_label(record, record["analysis"], "passt_nicht", record["quelle"], automatic=True)
    _update_sources(record, status="verworfen")
