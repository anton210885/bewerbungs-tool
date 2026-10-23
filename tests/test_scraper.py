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
