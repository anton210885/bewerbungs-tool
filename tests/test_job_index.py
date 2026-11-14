import json

import numpy as np
import pytest

from src import company_jobs, config, db, job_index, quality, task_search, vectors

TEXT = ("Du automatisierst Abläufe mit Python und PowerShell.\nDu betreust SQL-Server-Datenbanken und "
        "entwickelst Datenpipelines.\nDu arbeitest eng mit dem Betrieb zusammen und dokumentierst sauber.")
OTHER = ("Du pflegst Patientinnen und Patienten auf der Station.\nDu arbeitest im Schichtdienst im Team.\n"
         "Du unterstützt bei der Körperpflege und der Mobilisation der Bewohnenden.")
WORDS = ["python", "powershell", "sql", "datenbank", "pipeline", "automatis", "pflege", "patient", "schicht",
         "station", "betrieb", "team"]


def fake_vector(text: str) -> list[float]:
    """Bag of Words über wenige Stichworte: reicht, um Bedeutungsnähe nachzubilden."""
    low = text.lower()
    return [float(low.count(w)) for w in WORDS] + [0.1]


class FakeResponse:
    def __init__(self, texts):
        self.texts = texts

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [{"index": i, "embedding": fake_vector(t)} for i, t in enumerate(self.texts)]}


@pytest.fixture
def fake_api(monkeypatch):
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(list(json["input"]))
        return FakeResponse(json["input"])

    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "test")
    monkeypatch.setattr(task_search.requests, "post", post)
    monkeypatch.setattr(task_search, "_record_usage", lambda *a: None)
    return calls


def test_embeddings_are_stored_and_reused(fake_api):
    first = task_search.embed(["eins python", "zwei sql"])
    assert len(fake_api) == 1 and first is not None
    vectors._stores.clear()  # wie nach einem Neustart: von der Platte lesen
    again = task_search.embed(["zwei sql", "eins python", "drei pflege"])
    assert fake_api[1] == ["drei pflege"], "nur der neue Text kostet"
    assert np.allclose(again[1], first[0], atol=1e-2)
    assert vectors.path("text-embedding-3-small").parent == config.DATA_ROOT / "vektoren"
    assert vectors.count("text-embedding-3-small") == 3


def test_failed_call_keeps_what_was_paid(fake_api, monkeypatch):
    original = task_search.requests.post
    batches = []

    def flaky(url, headers=None, json=None, timeout=None):
        batches.append(1)
        if len(batches) > 1:
            raise task_search.requests.RequestException("weg")
        return original(url, headers=headers, json=json, timeout=timeout)

    monkeypatch.setattr(task_search.requests, "post", flaky)
    assert task_search.embed([f"text {i}" for i in range(150)]) is None
    assert vectors.count("text-embedding-3-small") == 100


def _seed_sources(monkeypatch):
    db.init_db()
    app_id = db.add_application({"source": "Link", "external_id": "https://a.ch/jobs/1", "title": "Data Engineer",
                                 "company": "Alpha AG", "url": "https://a.ch/jobs/1", "description": TEXT,
                                 "status": "gefunden"})
    store = {"zeit": None, "stellen": {
        # dieselbe Adresse wie im Tracker, anders geschrieben
        "HTTPS://A.ch/jobs/1/": {"url": "HTTPS://A.ch/jobs/1/", "title": "Data Engineer",
                                             "company": "Alpha", "description": TEXT, "status": "neu"},
        # dieselbe Anzeige bei einer anderen Adresse (Jobportal der Firma)
        "https://jobs.example/alpha/77": {"url": "https://jobs.example/alpha/77", "title": "Data Engineer (m/w/d) 100%",
                                          "company": "Alpha AG", "description": TEXT + " ", "status": "neu"},
        "https://b.ch/pflege": {"url": "https://b.ch/pflege", "title": "Pflegefachperson", "company": "Heim B",
                                "description": OTHER, "status": "neu"},
        "https://b.ch/weit": {"url": "https://b.ch/weit", "title": "Pflegehilfe", "company": "Heim C",
                              "description": OTHER + " Weit weg.", "status": "zu_weit"},
        "https://c.ch/titel": {"url": "https://c.ch/titel", "title": "Python Entwickler", "company": "Gamma",
                               "description": "", "status": "neu"},
    }}
    company_jobs.save(store)
    return app_id


def test_collect_merges_sources_and_marks_hidden(monkeypatch):
    app_id = _seed_sources(monkeypatch)
    records = {r["url"]: r for r in job_index.collect([{"url": "https://p.ch/1", "title": "Portalstelle",
                                                       "description": OTHER}])}
    tracked = records["https://a.ch/jobs/1"]
    assert tracked["quellen"] == ["Tracker", "Firmenseite"] and tracked["quelle"] == "Tracker"
    assert tracked["app_id"] == app_id
    assert records["https://b.ch/weit"]["ausgeblendet"]
    assert records["https://c.ch/titel"]["nur_titel"]
    assert records["https://p.ch/1"]["quelle"] == "Jobportale"
    assert len(records) == 6


def test_search_similar_and_duplicates(fake_api, monkeypatch):
    _seed_sources(monkeypatch)
    index = job_index.build(job_index.collect())
    hits = job_index.search(index, "Automatisierung mit PowerShell und SQL")
    assert hits[0]["company"].startswith("Alpha")
    assert sum(h["company"].startswith("Alpha") for h in hits) == 1, "Doppelte nur einmal"
    assert "Pflegehilfe" not in {h["title"] for h in hits}, "zu weit entfernt bleibt ausgeblendet"
    assert "Pflegehilfe" in {h["title"] for h in job_index.search(index, "Pflege Patienten", show_hidden=True)}
    groups = job_index.duplicate_groups(index)
    assert len(groups) == 1 and {r["url"] for r in groups[0]} == {"https://a.ch/jobs/1", "https://jobs.example/alpha/77"}
    similar = job_index.similar(index, quality.job_key("https://b.ch/pflege", OTHER))
    assert similar[0]["title"] == "Pflegehilfe"
    assert all(not r["company"].startswith("Alpha") for r in similar[:1])


def test_same_template_different_title_is_not_a_duplicate(fake_api):
    records = [job_index._record({"url": f"https://h.ch/{t}", "title": t, "description": TEXT}, "Firmenseite")
               for t in ("Manager Value Chain", "Senior Manager Value Chain")]
    assert job_index.duplicate_groups(job_index.build(records)) == []


@pytest.mark.parametrize("title, expected", [
    ("Senior Software Engineer C# 80–100 % (M/W/D)", "senior software engineer c#"),
    ("Anlagen- / Maschinenführer*in 100%", "anlagen maschinenführer"),
    ("Data Engineer m/w/d", "data engineer"),
])
def test_title_norm(title, expected):
    assert job_index.title_norm(title) == expected


def test_no_embedding_provider_means_no_index(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://localhost:1234/v1")
    record = job_index._record({"url": "u", "title": "T", "description": TEXT}, "Tracker")
    assert job_index.build([record]) is None
