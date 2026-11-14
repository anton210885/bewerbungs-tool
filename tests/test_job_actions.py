"""Bewerten, übernehmen und verwerfen aus der einen Liste «Stellen ansehen» – für jede Quelle."""
from src import company_jobs, db, discovery, job_actions, job_index, quality, searches

TEXT = ("Du automatisierst Abläufe mit Python und PowerShell. Du betreust SQL-Server-Datenbanken und "
        "entwickelst Datenpipelines. Du arbeitest eng mit dem Betrieb zusammen und dokumentierst sauber.")
ANALYSIS = {"score": 81, "fazit": "passt gut"}


def _fake_evaluate(monkeypatch):
    monkeypatch.setattr(discovery, "evaluate", lambda profile, item, wishes="": {**item, "analysis": ANALYSIS})


def _seed():
    db.init_db()
    company_jobs.save({"zeit": None, "stellen": {
        "https://firma.ch/jobs/1": {"url": "https://firma.ch/jobs/1", "title": "Data Engineer", "company": "Firma",
                                    "description": TEXT, "status": "neu", "gefunden": "2026-11-10T08:00"},
    }})
    discovery.save_portal_items([
        {"url": "https://jobs.ch/42", "title": "Datenbank-Admin", "company": "Portal AG", "description": TEXT,
         "gefunden": "2026-11-12T09:00"},
    ])
    searches._write(searches._results_path(), {"s1": {"zeit": "2026-11-11T07:00", "neu_gefunden": 1, "ergebnisse": [
        {"url": "https://karriere.ch/7", "title": "Python Entwickler", "company": "Karriere AG",
         "description": TEXT, "analysis": ANALYSIS},
    ]}})
    return {r["url"]: r for r in job_index.collect()}


def test_collect_carries_analysis_and_date():
    records = _seed()
    assert records["https://karriere.ch/7"]["analysis"] == ANALYSIS
    assert records["https://jobs.ch/42"]["gefunden"] == "2026-11-12T09:00"
    assert records["https://firma.ch/jobs/1"]["score"] is None


def test_evaluate_is_stored_at_the_source(monkeypatch):
    _fake_evaluate(monkeypatch)
    records = _seed()
    job_actions.evaluate(records["https://firma.ch/jobs/1"], {}, "")
    job_actions.evaluate_many([records["https://jobs.ch/42"]], {}, "")
    assert company_jobs.load()["stellen"]["https://firma.ch/jobs/1"]["analysis"] == ANALYSIS
    assert company_jobs.load()["stellen"]["https://firma.ch/jobs/1"]["status"] == "bewertet"
    assert discovery.load_portal_items()[0]["analysis"] == ANALYSIS
    again = {r["url"]: r for r in job_index.collect()}
    assert again["https://firma.ch/jobs/1"]["score"] == 81 and again["https://jobs.ch/42"]["score"] == 81


def test_dismiss_hides_everywhere():
    records = _seed()
    for url in ("https://firma.ch/jobs/1", "https://jobs.ch/42", "https://karriere.ch/7"):
        job_actions.dismiss(records[url])
    again = {r["url"]: r for r in job_index.collect()}
    assert again["https://firma.ch/jobs/1"]["ausgeblendet"] and again["https://jobs.ch/42"]["ausgeblendet"]
    assert "https://karriere.ch/7" not in again, "aus der gespeicherten Suche entfernt"
    assert quality.load_labels()[quality.job_key("https://karriere.ch/7", TEXT)]["rating"] == "passt_nicht"


def test_take_over_puts_it_in_the_tracker():
    records = _seed()
    stored = []

    def store_job(url, job, analysis, meta):
        stored.append(url)
        return db.add_application({"source": meta["source"], "external_id": url, "title": job["title"],
                                   "url": url, "description": job["description"]})

    with_analysis = job_actions.take_over(records["https://karriere.ch/7"], store_job)
    without = job_actions.take_over(records["https://firma.ch/jobs/1"], store_job)
    assert with_analysis and without and stored == ["https://karriere.ch/7"]
    assert company_jobs.load()["stellen"]["https://firma.ch/jobs/1"]["status"] == "übernommen"
    again = {r["url"]: r for r in job_index.collect()}
    assert again["https://firma.ch/jobs/1"].get("app_id") == without
    assert not again["https://firma.ch/jobs/1"]["ausgeblendet"], "im Tracker bleibt sie sichtbar"
