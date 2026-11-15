import json

import pytest

from src import scraper


def test_search_urls_use_portal_specific_locations_and_units():
    from urllib.parse import parse_qs, urlsplit
    jobs_query = parse_qs(urlsplit(scraper.search_url("jobs.ch", "Data Engineer", "Zürich, Schweiz", 25, 2)).query)
    linkedin_query = parse_qs(urlsplit(scraper.search_url("LinkedIn", "Data Engineer", "Zürich, Schweiz", 25, 2)).query)
    assert jobs_query["location"] == ["Zürich"]
    assert linkedin_query["distance"] == ["16"]
    assert linkedin_query["start"] == ["25"]


def test_jobs_listing_structured_data_preserves_order_and_deduplicates():
    postings = [{"@type": "JobPosting", "title": f"Engineer {i}",
                 "url": f"https://www.jobs.ch/de/stellenangebote/detail/{i}/",
                 "hiringOrganization": {"name": "Test AG"},
                 "jobLocation": {"address": {"addressLocality": "Zürich"}}} for i in range(2)]
    page = '<script type="application/ld+json">' + json.dumps({"itemListElement": postings}) + '</script>'
    page += '<a href="/de/stellenangebote/detail/0/?tracking=yes">Engineer 0</a>'
    result = scraper.parse_listing(page, "jobs.ch")
    assert len(result) == 2
    assert result[0]["title"] == "Engineer 0"
    assert result[0]["company"] == "Test AG"
    assert result[0]["location"] == "Zürich"


def test_linkedin_cards_ignore_login_and_external_links():
    page = '''<div class><div class="base-search-card job-search-card">
      <a class="base-card__full-link" href="https://ch.linkedin.com/jobs/view/engineer-123?tracking=a"></a>
      <h3 class="base-search-card__title">Data Engineer</h3>
      <h4 class="base-search-card__subtitle"><a>Test AG</a></h4>
      <span class="job-search-card__location">Zürich</span></div>
      <a href="https://evil.example/jobs/view/test">Fake job</a><a href="/login">Login</a></div>'''
    result = scraper.parse_listing(page, "LinkedIn")
    assert len(result) == 1
    assert result[0]["company"] == "Test AG"
    assert result[0]["url"] == "https://ch.linkedin.com/jobs/view/engineer-123"


def test_details_never_evaluate_cookie_page_as_full_description():
    details = scraper.parse_detail("<h1>Sign in</h1><p>Accept all cookies</p>" * 100, "LinkedIn")
    assert details["preliminary"] is True
    assert not details.get("description")
    rich = "Wir suchen Python- und SQL-Kenntnisse für Datenpipelines. " * 10
    details = scraper.parse_detail('<div class="show-more-less-html__markup">' + rich + '</div>', "LinkedIn")
    assert details["description"].startswith("Wir suchen")
    assert details["preliminary"] is False


@pytest.mark.parametrize("status,url,title", [
    (429, "https://www.linkedin.com/jobs/search/", ""),
    (200, "https://www.linkedin.com/authwall", ""),
    (200, "https://www.jobs.ch/", "Just a moment"),
])
def test_client_stops_on_portal_blocks(monkeypatch, status, url, title):
    class Response:
        status_code = status
        text = f"<title>{title}</title>"
    response = Response()
    response.url = url
    client = scraper.Client()
    monkeypatch.setattr(client.session, "get", lambda *a, **kw: response)
    with pytest.raises(scraper.PortalError):
        client.get(url)
    client.session.close()


def test_blocked_source_is_not_retried_for_other_terms(monkeypatch):
    calls = []
    def blocked(self, url):
        calls.append(url)
        raise scraper.PortalError("HTTP 429")
    monkeypatch.setattr(scraper.Client, "get", blocked)
    result, errors = scraper.search({"terms": ["Engineer", "Analyst"], "location": "Zürich"}, ["jobs.ch"], pages=2)
    assert not result
    assert len(calls) == 1
    assert len(errors) == 1


def test_jobs_ch_searches_the_canton_and_reports_empty_searches(monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    lookups, requested = [], []
    def lookup(place):
        lookups.append(place)
        return "Aargau"
    monkeypatch.setattr(scraper, "_lookup_region", lookup)
    posting = {"@type": "JobPosting", "title": "Leiter Qualität", "url": "https://www.jobs.ch/de/stellenangebote/detail/q/"}
    def get(self, url):
        requested.append(url)
        if "Krisen" in url:
            return "<title>Keine Krisenmanagement Jobs in Aargau - jobs.ch</title>"
        return '<script type="application/ld+json">' + json.dumps(posting) + '</script>'
    monkeypatch.setattr(scraper.Client, "get", get)
    result, errors = scraper.search({"terms": ["Qualität", "Krisenmanagement"], "location": "Lenzburg, Schweiz"},
                                    ["jobs.ch"], detail_limit=0)
    assert parse_qs(urlsplit(requested[0]).query)["location"] == ["Aargau"]
    assert [r["title"] for r in result] == ["Leiter Qualität"]
    assert errors == ["jobs.ch: keine Stellen in Aargau für «Krisenmanagement» – die Suche selbst hat funktioniert."]
    # der Kanton wird gespeichert und nicht nochmals nachgeschlagen
    assert scraper.jobs_ch_location("Lenzburg") == "Aargau" and lookups == ["Lenzburg"]


def test_jobs_ch_keeps_the_place_when_lookup_fails(monkeypatch):
    def offline(place):
        raise scraper.requests.ConnectionError("offline")
    monkeypatch.setattr(scraper, "_lookup_region", offline)
    assert scraper.jobs_ch_location("Lenzburg, Schweiz") == "Lenzburg"
    assert not scraper.regions_path().exists(), "beim nächsten Mal erneut versuchen"


def test_load_missing_texts_fills_title_only_items_and_stops_a_blocking_portal(monkeypatch):
    text = "Du leitest das Qualitätsmanagement und führst Audits durch. " * 5
    items = [
        {"url": "https://www.jobs.ch/de/stellenangebote/detail/a/", "title": "QM-Leiter", "description": ""},
        {"url": "https://ch.linkedin.com/jobs/view/1", "title": "Controller", "description": ""},
        {"url": "https://ch.linkedin.com/jobs/view/2", "title": "Projektleiter", "description": ""},
        {"url": "https://www.jobs.ch/de/stellenangebote/detail/b/", "title": "Schon da", "description": text},
        {"url": "https://andere.ch/job/1", "title": "Fremde Seite", "description": ""},
    ]
    requested, waits = [], []
    def get(self, url):
        requested.append(url)
        if "linkedin" in url:
            raise scraper.PortalError("Portal blockiert den Zugriff (HTTP 429). Quelle wird angehalten.")
        return '<script type="application/ld+json">' + json.dumps(
            {"@type": "JobPosting", "title": "QM-Leiter", "description": text,
             "hiringOrganization": {"name": "Firma AG"}}) + "</script>"
    monkeypatch.setattr(scraper.Client, "get", get)
    loaded, errors = scraper.load_missing_texts(items, limit=10, sleep=waits.append)
    assert loaded == 1
    assert items[0]["description"].startswith("Du leitest") and items[0]["company"] == "Firma AG"
    assert not items[0]["preliminary"]
    # LinkedIn sperrt: die zweite LinkedIn-Anzeige wird nicht mehr versucht, fremde Seiten nie
    assert requested == ["https://www.jobs.ch/de/stellenangebote/detail/a/", "https://ch.linkedin.com/jobs/view/1"]
    assert len(errors) == 1 and "nächsten Klick" in errors[0]
    assert waits == [scraper.LINKEDIN_WAIT - 1.0]


def test_double_encoded_html_in_postings_becomes_plain_text():
    posting = {"@type": "JobPosting", "title": "Fachplaner",
               "description": "&amp;lt; alle Stellen&lt;br&gt;&lt;br&gt;Du planst Räume &amp;amp; Möbel. " * 6}
    details = scraper.parse_detail('<script type="application/ld+json">' + json.dumps(posting) + "</script>",
                                   "LinkedIn")
    assert "<br" not in details["description"] and "&lt;" not in details["description"]
    assert "Räume & Möbel" in details["description"]
