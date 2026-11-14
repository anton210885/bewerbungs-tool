import pytest

from src import company_jobs, db, discovery, job_index

LONG = "Du betreust unsere Server und automatisierst Abläufe mit PowerShell und Python. " * 3


@pytest.mark.parametrize("text, expected", [
    ("Arbeitsort: 5033 Buchs AG\nDein Team", "5033 Buchs AG"),
    ("Standort: Lenzburg - mit Homeoffice", "Lenzburg"),
    ("Standort: Muri bei Bern. Wir freuen uns", "Muri bei Bern"),
    ("Mammut Sports Group, Hauptstrasse 3, 87787 Wolfertschwenden", "87787 Wolfertschwenden"),
    ("Bewerbung an CH-8957 Spreitenbach", "8957 Spreitenbach"),
    ("Rosenbergstrasse 1, 9000 St. Gallen", "9000 St. Gallen"),
    # keine Orte
    ("Einsatz an unseren Standorten mit Schwerpunkt Aarau", ""),
    ("Location: flat structures, short decision paths", ""),
    ("Ab 2027 Starten wir neu", ""),
    ("Wir beschäftigen 4000 Mitarbeitende", ""),
])
def test_location_from_text(text, expected):
    assert company_jobs.location_from_text(text) == expected


def _store(*jobs):
    return {"zeit": None, "stellen": {j["url"]: {"status": "neu", "website": "https://firma.ch", **j} for j in jobs}}


def test_fill_locations_prefers_text_and_falls_back_to_company_town():
    store = _store(
        {"url": "a", "title": "A", "description": LONG + " Arbeitsort: Baden"},
        {"url": "b", "title": "B", "description": LONG},
        {"url": "c", "title": "C", "description": LONG, "location": "Zürich"},
        {"url": "d", "title": "D", "description": "", "website": "https://andere.ch"},
    )
    data = {"firmen": [{"website": "https://firma.ch", "ort": "Aarau"}]}
    assert company_jobs.fill_locations(store, data) == 2
    jobs = store["stellen"]
    assert (jobs["a"]["location"], jobs["a"]["ort_quelle"]) == ("Baden", "Anzeigentext")
    assert (jobs["b"]["location"], jobs["b"]["ort_quelle"]) == ("Aarau", "Firmensitz")
    assert jobs["c"]["location"] == "Zürich" and "ort_quelle" not in jobs["c"], "vorhandene Angabe bleibt"
    assert not jobs["d"].get("location")

    # Später geladener Text mit Arbeitsort ersetzt den vermuteten Firmensitz
    jobs["b"]["description"] = LONG + " 5400 Baden"
    jobs["b"]["distanz_km"] = 12
    company_jobs.fill_locations(store, data)
    assert (jobs["b"]["location"], jobs["b"]["ort_quelle"]) == ("5400 Baden", "Anzeigentext")
    assert "distanz_km" not in jobs["b"], "Entfernung wird neu berechnet"


def test_missing_details_skips_failed_and_closed_jobs():
    store = _store(
        {"url": "a", "title": "nur Titel"},
        {"url": "b", "title": "mit Text", "description": LONG},
        {"url": "c", "title": "gescheitert", "detail_fehler": "kaum Anzeigentext"},
        {"url": "d", "title": "verworfen", "status": "verworfen"},
    )
    assert [j["url"] for j in company_jobs.missing_details(store)] == ["a"]


def test_portal_items_survive_restart_and_feed_the_job_database():
    items = [{"url": f"https://jobs.ch/{i}", "title": f"Stelle {i}", "description": LONG, "gefunden": f"2026-11-{i:02d}"}
             for i in range(1, 4)]
    discovery.save_portal_items(items)
    loaded = discovery.load_portal_items()
    assert [i["title"] for i in loaded] == ["Stelle 3", "Stelle 2", "Stelle 1"], "neueste zuerst"
    db.init_db()
    records = job_index.collect()
    assert {r["quelle"] for r in records} == {"Jobportale"} and len(records) == 3
    discovery.clear_portal_items()
    assert discovery.load_portal_items() == []


def test_portal_items_keep_only_the_newest(monkeypatch):
    monkeypatch.setattr(discovery, "MAX_PORTAL_ITEMS", 2)
    discovery.save_portal_items([{"title": str(i), "gefunden": f"2026-11-0{i}"} for i in range(1, 5)])
    assert [i["title"] for i in discovery.load_portal_items()] == ["4", "3"]
