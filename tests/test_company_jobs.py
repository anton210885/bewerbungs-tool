import json

import pytest

from src import company_jobs, companies, discovery, task_search
from tests.test_companies import FakeResponse, FakeSession

COMPANY = {"name": "Muster AG", "website": "https://muster.ch", "karriere": "https://muster.ch/jobs"}
NAV = "".join(f'<a href="/seite{i}">Seite {i}</a>' for i in range(5))


class AllowAll:
    def allowed(self, url):
        return True


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    monkeypatch.setattr(task_search, "embed", lambda texts: None)
    monkeypatch.setattr(company_jobs.db, "list_applications", lambda: [])


def test_clean_text_and_candidate_links():
    html = ('<a href="/jobs/1"><style>#p{padding:1px}</style>Software Engineer 100 %</a>'
            '<a href="/bild.jpg">Grosses Bild</a><a href="mailto:x@y.ch">Mail an uns</a>'
            '<a href="https://muster.ch/jobs">Jobs</a><a href="/x">ab</a>')
    assert company_jobs.candidate_links(html, "https://muster.ch/jobs") == [
        ("https://muster.ch/jobs/1", "Software Engineer 100 %")]
    assert company_jobs.clean_text("Titel #a { padding: 1px } Rest") == "Titel #a Rest"


def test_jsonld_postings_need_no_ai():
    posting = {"@type": "JobPosting", "title": "Data Engineer (m/w/d)", "description": "<p>Pipelines bauen</p>",
               "jobLocation": {"address": {"addressLocality": "Aarau"}}}
    html = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
    session = FakeSession({"https://muster.ch/jobs": html})

    def no_ai(links):
        raise AssertionError("KI darf nicht aufgerufen werden")

    result = company_jobs.collect_company(COMPANY, session, AllowAll(), choose=no_ai)
    job = result["stellen"][0]
    assert job["title"] == "Data Engineer (m/w/d)" and job["location"] == "Aarau" and "Pipelines" in job["description"]
    assert job["url"] == "https://muster.ch/jobs#data-engineer-m-w-d"


def test_ai_choice_plus_obvious_job_titles():
    html = NAV + ('<a href="/jobs/dev">Entwickler</a><a href="/jobs/support">Support-Mitarbeiter/in (40-60%)</a>'
                  '<a href="/aktion">25% Rabatt im Shop</a>')
    session = FakeSession({"https://muster.ch/jobs": html})
    result = company_jobs.collect_company(
        COMPANY, session, AllowAll(),
        choose=lambda links: [{"url": "https://muster.ch/jobs/dev", "titel": "x", "title": "Entwickler"}])
    assert [j["url"] for j in result["stellen"]] == ["https://muster.ch/jobs/dev", "https://muster.ch/jobs/support"]
    assert result["links_hash"]


def test_unchanged_page_skips_ai():
    html = NAV + '<a href="/jobs/dev">Entwickler (m/w/d)</a>'
    links = company_jobs.candidate_links(html, "https://muster.ch/jobs")
    company = {**COMPANY, "links_hash": company_jobs.links_hash(links), "stellen_anzahl": 1}

    def no_ai(links):
        raise AssertionError("unveränderte Seite braucht keine KI")

    result = company_jobs.collect_company(company, FakeSession({"https://muster.ch/jobs": html}), AllowAll(), no_ai)
    assert result["stellen"] is None


def test_follows_one_link_to_open_positions():
    start = NAV + '<a href="/jobs/offene-stellen">Offene Stellen</a>'
    listing = NAV + '<a href="/jobs/42">Projektleiter/in Bau 100%</a>'
    session = FakeSession({"https://muster.ch/jobs": start, "https://muster.ch/jobs/offene-stellen": listing})
    result = company_jobs.collect_company(COMPANY, session, AllowAll(), choose=lambda links: [])
    assert [j["title"] for j in result["stellen"]] == ["Projektleiter/in Bau 100%"]


def test_merge_keeps_dismissed_and_removes_vanished_open_jobs():
    store = {"stellen": {
        "u1": {"url": "u1", "website": "https://muster.ch", "status": "neu", "title": "Alt"},
        "u2": {"url": "u2", "website": "https://muster.ch", "status": "verworfen", "title": "Nein danke"},
        "u3": {"url": "u3", "website": "https://andere.ch", "status": "neu", "title": "Andere Firma"},
    }}
    found = [company_jobs._job(COMPANY, "u2", "Nein danke"), company_jobs._job(COMPANY, "u4", "Lernende/r Logistik"),
             company_jobs._job(COMPANY, "u5", "Data Engineer"), company_jobs._job(COMPANY, "u6", "Im Tracker")]
    added = company_jobs.merge(store, COMPANY, found, exclude=["lernende"], tracked={"u6"})
    assert added == 1
    assert set(store["stellen"]) == {"u2", "u3", "u4", "u5", "u6"}
    assert store["stellen"]["u2"]["status"] == "verworfen", "verworfene kommen nicht wieder"
    assert store["stellen"]["u4"]["status"] == "ausgeschlossen"
    assert store["stellen"]["u6"]["status"] == "übernommen"


def test_collect_all_updates_companies_and_store(monkeypatch):
    data = {"firmen": [{**COMPANY}, {"name": "Aus", "website": "https://aus.ch", "karriere": "https://aus.ch/j",
                                     "ausgeblendet": True}]}
    store = company_jobs.load()
    monkeypatch.setattr(company_jobs, "collect_company", lambda c, s, r, choose: {
        "stellen": [company_jobs._job(c, "https://muster.ch/jobs/1", "Entwickler")], "hinweis": "", "links_hash": "h"})
    counts = company_jobs.collect_all(data, store, {"exclude": ""})
    assert counts == {"firmen": 1, "mit_stellen": 1, "neu": 1, "fehler": 0}
    assert data["firmen"][0]["stellen_anzahl"] == 1 and data["firmen"][0]["links_hash"] == "h"
    assert list(company_jobs.load()["stellen"]) == ["https://muster.ch/jobs/1"]
    assert companies.load()["firmen"][0]["stellen_anzahl"] == 1


def test_missing_store_forces_reread_of_unchanged_pages(monkeypatch):
    data = {"firmen": [{**COMPANY, "links_hash": "h", "stellen_anzahl": 2}]}
    seen = []
    monkeypatch.setattr(company_jobs, "collect_company", lambda c, s, r, choose: seen.append(dict(c)) or {
        "stellen": [], "hinweis": "", "links_hash": "h"})
    company_jobs.collect_all(data, {"stellen": {}}, {})
    assert "links_hash" not in seen[0], "ohne bekannte Stellen darf die Seite nicht übersprungen werden"


def test_details_rank_and_evaluate_best(monkeypatch):
    store = {"stellen": {}}
    for i, title in enumerate(["Data Engineer", "Disponent Logistik"]):
        store["stellen"][f"u{i}"] = company_jobs._job(COMPANY, f"u{i}", title)
    texts = {"u0": "Du entwickelst ETL-Datenpipelines in Azure und pflegst SQL-Datenbanken. " * 4,
             "u1": "Du planst Touren und Lieferungen im Lager und betreust Fahrer. " * 4}
    monkeypatch.setattr(company_jobs.jobs, "fetch_job",
                        lambda url: {"description": texts[url], "location": "Aarau", "thin": False})
    monkeypatch.setattr(company_jobs.companies, "_Robots", lambda session: AllowAll())
    profile = {"berufserfahrung": [{"aufgaben": ["Entwicklung von ETL-Datenpipelines in Azure",
                                                  "Pflege von SQL-Datenbanken"]}]}
    assert company_jobs.load_details(store, profile) == 2
    company_jobs.rank_open(store, profile)
    assert store["stellen"]["u0"]["location"] == "Aarau"
    assert [j["url"] for j in company_jobs.next_candidates(store, 1)] == ["u0"]

    monkeypatch.setattr(discovery, "evaluate", lambda p, job, wishes="": {**job, "analysis": {"score": 81}})
    assert company_jobs.evaluate_best(store, profile, 1) == []
    assert store["stellen"]["u0"]["status"] == "bewertet" and store["stellen"]["u1"]["status"] == "neu"
    assert company_jobs.open_jobs(store)[0]["url"] == "u0"
    company_jobs.set_status(store, "u1", "verworfen")
    assert [j["url"] for j in company_jobs.open_jobs(store)] == ["u0"]


def test_place_key_and_distance():
    assert company_jobs.place_key("5033 Buchs AG, Schweiz") == "5033 buchs ag, schweiz"
    assert company_jobs.place_key("Aarau / Zürich") == "aarau"
    assert company_jobs.place_key("nicht angegeben") == ""
    assert 30 < company_jobs.distance_km((47.39, 8.05), (47.37, 8.54)) < 40  # Aarau–Zürich


def test_apply_distance_hides_far_jobs_and_caches_places():
    staufen = (47.38, 8.17)
    points = {"lenzburg": [47.39, 8.18], "münchen": [48.14, 11.58]}
    calls = []

    class GeoResponse:
        def __init__(self, hits):
            self.hits = hits

        def json(self):
            return self.hits

        def raise_for_status(self):
            pass

    class GeoSession:
        def get(self, url, params=None, **kwargs):
            calls.append(params["q"])
            hit = points.get(params["q"])
            return GeoResponse([{"lat": hit[0], "lon": hit[1]}] if hit else [])

    store = {"stellen": {
        "a": {"url": "a", "status": "neu", "location": "Lenzburg"},
        "b": {"url": "b", "status": "neu", "location": "München"},
        "c": {"url": "c", "status": "neu", "location": ""},
        "d": {"url": "d", "status": "verworfen", "location": "Mars"},
    }}
    hidden = company_jobs.apply_distance(store, staufen, 30, session=GeoSession(), sleep=lambda s: None)
    assert hidden == 1
    assert store["stellen"]["a"]["status"] == "neu" and store["stellen"]["a"]["distanz_km"] <= 2
    assert store["stellen"]["b"]["status"] == "zu_weit"
    assert store["stellen"]["c"]["status"] == "neu", "ohne Ort bleibt die Stelle"
    assert sorted(calls) == ["lenzburg", "münchen"], "verworfene Stellen werden nicht nachgeschlagen"
    # Zweiter Lauf mit grösserem Umkreis: aus dem Cache, ausgeblendete Stelle kommt zurück
    calls.clear()
    company_jobs.apply_distance(store, staufen, 500, session=GeoSession(), sleep=lambda s: None)
    assert calls == [] and store["stellen"]["b"]["status"] == "neu"


def test_embedding_price_is_not_the_expensive_default():
    from src import costs
    assert costs.estimate_usd("text-embedding-3-small", 1_000_000, 0) == pytest.approx(0.02)


def test_comparison_tasks_use_selected_fields():
    prefs = {"task_fields": [{"name": "Daten", "aufgaben": ["ETL"]}, {"name": "Logistik", "aufgaben": ["Touren"]}],
             "selected_fields": ["Daten"]}
    assert company_jobs.comparison_tasks(prefs) == ["ETL"]
    assert company_jobs.comparison_tasks({}) is None
