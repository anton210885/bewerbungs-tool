import pytest

from src import discovery, skill_search, task_search

PROFILE = {"berufserfahrung": [
    {"position": "Data Engineer", "aufgaben": ["Entwicklung von ETL-Datenpipelines in Azure",
                                               {"text": "Pflege von SQL-Datenbanken", "quelle": "lebenslauf"}],
     "erfolge": ["Entwicklung von ETL-Datenpipelines in Azure"]},
    {"position": "Logistiker", "aufgaben": ["Disposition von Lieferungen und Touren"]},
]}


@pytest.fixture(autouse=True)
def no_real_embeddings(monkeypatch):
    """Tests dürfen nie den echten Embedding-Dienst aufrufen."""
    monkeypatch.setattr(task_search, "embed", lambda texts: None)


def test_profile_tasks_are_collected_without_duplicates():
    assert task_search.profile_tasks(PROFILE) == ["Entwicklung von ETL-Datenpipelines in Azure",
                                                  "Pflege von SQL-Datenbanken", "Disposition von Lieferungen und Touren"]


def test_suggest_fields_validates_ai_answer(monkeypatch):
    monkeypatch.setattr(task_search, "chat_json", lambda *a, **kw: {"felder": [
        {"name": "Datenintegration", "aufgaben": [0, 1, 99, "x", 0],
         "suchbegriffe": ["Data Engineer", " ETL ", "etl", "Ein viel zu langer Suchbegriff mit sehr vielen Wörtern",
                          "Datenintegration", "SQL", "Azure", "Python"]},
        {"name": "", "suchbegriffe": ["leer"]},
        {"name": "Ohne Begriffe", "suchbegriffe": []},
    ]})
    fields = task_search.suggest_fields(PROFILE)
    assert len(fields) == 1
    assert fields[0]["aufgaben"] == ["Entwicklung von ETL-Datenpipelines in Azure", "Pflege von SQL-Datenbanken"]
    assert fields[0]["suchbegriffe"] == ["Data Engineer", "ETL", "Datenintegration", "SQL", "Azure", "Python"]


def test_suggest_fields_needs_tasks():
    with pytest.raises(ValueError):
        task_search.suggest_fields({})


def test_search_terms_alternate_between_selected_fields():
    fields = [{"name": "A", "suchbegriffe": ["a1", "a2", "a3"]}, {"name": "B", "suchbegriffe": ["b1", "A1"]},
              {"name": "C", "suchbegriffe": ["c1"]}]
    assert task_search.search_terms(fields, ["A", "B"]) == ["a1", "b1", "a2", "a3"]
    prefs = {"search_mode": "Aufgaben", "task_fields": fields, "selected_fields": ["C"], "terms": ["Ignoriert"]}
    assert skill_search.search_terms(prefs) == ["c1"]


def test_chunks_split_bullets_and_sentences():
    text = "Deine Aufgaben\n- Du entwickelst ETL-Strecken für unser Data Warehouse\n- Kurz\nWir bieten dir viel. " \
           "Du betreust Schnittstellen zu Partnersystemen im Team."
    parts = task_search.chunks(text)
    assert "Du entwickelst ETL-Strecken für unser Data Warehouse" in parts
    assert "Du betreust Schnittstellen zu Partnersystemen im Team." in parts
    assert all(len(p) >= 25 for p in parts)


def test_rank_by_word_overlap_without_embeddings():
    items = [{"title": "Disponent", "description": "Disposition von Lieferungen und Touren im Lager"},
             {"title": "Data Engineer", "description": "Entwicklung von ETL-Datenpipelines in Azure und Pflege "
                                                       "von SQL-Datenbanken für unsere Kunden"}]
    fields = [{"name": "Daten", "aufgaben": ["Entwicklung von ETL-Datenpipelines in Azure",
                                            "Pflege von SQL-Datenbanken"]},
              {"name": "Logistik", "aufgaben": ["Disposition von Lieferungen und Touren"]}]
    ranked = task_search.rank(PROFILE, items, task_search.selected_tasks(fields, ["Daten"]))
    assert ranked[0]["title"] == "Data Engineer"
    assert ranked[0]["aufgaben_match"]["methode"] == "Wörter"
    assert ranked[0]["aufgaben_match"]["passende_aufgaben"]
    assert ranked[1]["aufgaben_match"]["abgedeckt"] == 0, "abgewählte Logistik-Aufgaben zählen nicht"


def test_rank_with_embeddings_uses_meaning(monkeypatch):
    # Vektoren: Achse 0 = Daten, Achse 1 = Logistik
    vectors = {"Entwicklung von ETL-Datenpipelines in Azure": [1, 0], "Pflege von SQL-Datenbanken": [0.9, 0.1],
               "Disposition von Lieferungen und Touren": [0, 1]}
    def fake_embed(texts):
        return [vectors.get(t, [0.95, 0.05] if "Daten" in t or "Data" in t else [0.1, 0.9]) for t in texts]
    monkeypatch.setattr(task_search, "embed", fake_embed)
    items = [{"title": "Lagerlogistiker", "description": "Du planst Touren und Transporte für den Versand"},
             {"title": "BI Engineer", "description": "Du baust Datenstrecken für unser Data Warehouse"}]
    ranked = task_search.rank(PROFILE, items)
    assert [i["title"] for i in ranked] == ["BI Engineer", "Lagerlogistiker"]
    match = ranked[0]["aufgaben_match"]
    assert match["methode"] == "Bedeutung" and match["abgedeckt"] == match["abschnitte"]


def test_api_search_uses_ranker(monkeypatch):
    from src import jobs
    monkeypatch.setattr(jobs, "search_adzuna", lambda *a, **kw: [
        jobs.Job("Adzuna", "1", "A", "", "", "https://example.org/a"),
        jobs.Job("Adzuna", "2", "B", "", "", "https://example.org/b")])
    prefs = {"search_mode": "Aufgaben", "task_fields": [{"name": "F", "suchbegriffe": ["x"]}],
             "selected_fields": ["F"], "location": "", "radius": 25}
    items, errors = discovery.search_api(prefs, ranker=lambda found: list(reversed(found)))
    assert [i["title"] for i in items] == ["B", "A"] and not errors


def test_short_listing_does_not_beat_strong_full_ad(monkeypatch):
    monkeypatch.setattr(task_search, "embed", lambda texts: [
        [1, 0] if "ETL" in t or "Datenstrecken" in t else [0.6, 0.8] if "Lieferung" in t else [0.2, 0.98]
        for t in texts])
    items = [{"title": "KV Praktikum Lieferunterstützung", "description": ""},
             {"title": "BI Engineer", "description": "\n".join(["Du baust Datenstrecken für das Data Warehouse"] * 3
                                                               + ["Wir bieten flexible Arbeitszeiten und Homeoffice"] * 5)}]
    ranked = task_search.rank(PROFILE, items, ["Entwicklung von ETL-Datenpipelines in Azure"])
    assert ranked[0]["title"] == "BI Engineer"
    assert ranked[0]["aufgaben_match"]["naehe"] == 100
    assert ranked[1]["aufgaben_match"]["naehe"] < 100


def test_recent_fields_preselects_current_work():
    profile = {"berufserfahrung": [
        {"position": "Data Engineer", "von": "01/2023", "bis": "", "aufgaben": ["ETL entwickeln"]},
        {"position": "Logistiker", "von": "01/2008", "bis": "12/2012", "aufgaben": ["Touren planen"]}]}
    fields = [{"name": "Daten", "aufgaben": ["ETL entwickeln"]}, {"name": "Logistik", "aufgaben": ["Touren planen"]}]
    assert task_search.recent_fields(profile, fields) == ["Daten"]


def test_same_job_under_two_links_is_merged():
    items = [{"title": "ICT System Engineer", "company": "AVA", "url": "https://www.jobs.ch/de/detail/1",
              "search_terms": ["Software Engineer"]},
             {"title": "ICT  System Engineer", "company": "ava", "url": "https://www.jobs.ch/de/detail/2",
              "search_terms": ["Support"]}]
    result = discovery.deduplicate(items)
    assert len(result) == 1 and result[0]["search_terms"] == ["Software Engineer", "Support"]


def test_own_task_terms_take_precedence():
    fields = [{"name": "A", "suchbegriffe": ["a1", "a2"]}]
    prefs = {"search_mode": "Aufgaben", "task_fields": fields, "selected_fields": ["A"],
             "task_terms": ["Eigener Begriff", "a1", "eigener begriff"]}
    assert skill_search.search_terms(prefs) == ["Eigener Begriff", "a1"]
    assert skill_search.search_terms({**prefs, "task_terms": []}) == ["a1", "a2"]
