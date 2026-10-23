from dataclasses import dataclass

from src import discovery, scraper, skill_search


def test_extract_skills_from_categories_named_entries_and_levels():
    profile = {"skills": {"software": ["Python", "SQL", {"name": "Excel", "niveau": "gut"}],
                          "fachlich": "Projektmanagement; Kundenberatung"},
               "kenntnisse": {"Python": "Fortgeschritten", "SAP": "Grundkenntnisse"},
               "kompetenzen": [{"label": "Fachlich", "text": "SQL, Prozessoptimierung"}]}
    result = skill_search.profile_skills(profile)
    assert result == ["Python", "SQL", "Excel", "Projektmanagement", "Kundenberatung", "SAP", "Prozessoptimierung"]
    assert "gut" not in result
    assert "software" not in result


def test_skill_mode_ignores_job_titles_and_works_without_them():
    prefs = {"search_mode": "Fähigkeiten", "terms": ["Buchhalter"], "selected_skills": ["Python", "SQL"]}
    assert skill_search.search_terms(prefs) == ["Python", "SQL"]
    prefs["terms"] = []
    assert skill_search.search_terms(prefs) == ["Python", "SQL"]


def test_legacy_and_mixed_modes_keep_both_query_types_with_limit():
    assert skill_search.search_terms({"terms": ["Engineer"], "selected_skills": ["SQL"]}) == ["Engineer"]
    prefs = {"search_mode": "Berufe + Fähigkeiten", "terms": ["Engineer", "Analyst", "Admin"],
             "selected_skills": ["SQL", "Python", "Excel"]}
    assert skill_search.search_terms(prefs) == ["Engineer", "SQL", "Analyst", "Python", "Admin"]


def test_matching_has_word_boundaries_and_handles_programming_languages():
    item = {"title": "JavaScript Engineer", "description": "Kenntnisse in C++, C# und PYTHON, aber keine weiteren Angaben."}
    matches = skill_search.matching_skills(item, ["Java", "C++", "C#", "Python", "SQL"])
    assert matches == ["C++", "C#", "Python"]


def test_rank_keeps_transferrable_jobs_without_title_match():
    items = [{"title": "Sachbearbeitung", "description": "Excel und SQL einsetzen"},
             {"title": "SQL Specialist", "description": ""}, {"title": "Andere Stelle", "description": ""}]
    preferences = {"search_mode": "Fähigkeiten", "selected_skills": ["SQL", "Excel"]}
    result = skill_search.rank(list(reversed(items)), preferences)
    assert result == items


def test_search_term_provenance_survives_deduplication():
    items = [{"title": "Engineer", "url": "https://example.org/job/1", "search_terms": ["Python"]},
             {"title": "Engineer", "url": "https://example.org/job/1", "search_terms": ["SQL", "Python"]}]
    result = discovery.deduplicate(items)
    assert len(result) == 1
    assert result[0]["search_terms"] == ["Python", "SQL"]


def test_api_uses_selected_skills_not_job_titles(monkeypatch):
    seen = []
    def search(term, *args, **kwargs):
        seen.append(term)
        return []
    monkeypatch.setattr(discovery.jobs, "search_adzuna", search)
    discovery.search_api({"terms": ["Buchhalter"], "search_mode": "Fähigkeiten", "selected_skills": ["SQL"],
                          "location": "Zürich", "radius": 25})
    assert seen == ["SQL"]


def test_scraper_searches_skill_and_loads_result_with_unrelated_title(monkeypatch):
    import json
    from urllib.parse import parse_qs, urlsplit
    requests = []
    posting = {"@type": "JobPosting", "title": "Sachbearbeiter Datenqualität", "url": "https://www.jobs.ch/de/stellenangebote/detail/test/"}
    listing = '<script type="application/ld+json">' + json.dumps(posting) + '</script>'
    def get(self, url):
        requests.append(url)
        if "/detail/" in url:
            return '<script type="application/ld+json">' + json.dumps({**posting, "description": "SQL und Excel werden zur Datenkontrolle benötigt. " * 10}) + '</script>'
        return listing
    monkeypatch.setattr(scraper.Client, "get", get)
    result, errors = scraper.search({"terms": ["Buchhalter"], "search_mode": "Fähigkeiten", "selected_skills": ["SQL"], "location": "Zürich"}, ["jobs.ch"], detail_limit=1)
    assert not errors
    assert parse_qs(urlsplit(requests[0]).query)["term"] == ["SQL"]
    assert result[0]["title"] == "Sachbearbeiter Datenqualität"
    assert result[0]["search_terms"] == ["SQL"]
    assert not result[0]["preliminary"]


def test_skill_wishes_do_not_treat_manual_search_terms_as_proven_qualifications():
    wishes = skill_search.evaluation_wishes({"search_mode": "Fähigkeiten", "selected_skills": ["SAP"], "wishes": "80 %"})
    assert "80 %" in wishes and "SAP" in wishes
    assert "keine belegten Qualifikationen" in wishes
    assert skill_search.evaluation_wishes({"wishes": "80 %"}) == "80 %"


def test_old_preferences_get_skill_defaults_without_losing_existing_search(tmp_path, monkeypatch):
    path = tmp_path / "preferences.json"
    path.write_text('{"terms": ["Engineer"], "location": "Basel"}')
    monkeypatch.setattr(discovery, "PREFERENCES", path)
    prefs = discovery.load_preferences({"skills": {"software": ["SQL"]}})
    assert prefs["terms"] == ["Engineer"]
    assert prefs["search_mode"] == "Berufe"
    assert prefs["selected_skills"] == ["SQL"]
