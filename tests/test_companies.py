import pytest

from src import companies


class FakeResponse:
    def __init__(self, url, text="", status=200, content_type="text/html"):
        self.url, self.text, self.status_code = url, text, status
        self.headers = {"content-type": content_type}


class FakeSession:
    """Seiten nach Adresse; alles andere 404."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url in self.pages:
            page = self.pages[url]
            return page if isinstance(page, FakeResponse) else FakeResponse(url, page)
        return FakeResponse(url, "", 404)


def test_normalize_and_domain():
    assert companies.normalize_website("www.Firma.ch/") == "https://www.firma.ch"
    assert companies.normalize_website("http://firma.ch/de/;https://x.ch") == "http://firma.ch/de"
    assert companies.normalize_website("kein link") == ""
    assert companies.domain("https://www.firma.ch/de") == "firma.ch"


def test_parse_overpass_merges_branches_of_same_company():
    elements = [
        {"tags": {"name": "Aveniq AG", "office": "it", "website": "https://www.aveniq.ch", "addr:city": "Lenzburg"}},
        {"tags": {"name": "Aveniq AG Filiale", "office": "it", "website": "aveniq.ch/"}},
        {"tags": {"name": "Ohne Webseite", "office": "company"}},
        {"tags": {"name": "Schreinerei Muster", "craft": "carpenter", "contact:website": "muster.ch"}},
    ]
    result = companies.parse_overpass(elements)
    assert [c["name"] for c in result] == ["Aveniq AG", "Schreinerei Muster"]
    assert result[0]["branche"] == "IT & Software" and result[0]["ort"] == "Lenzburg"
    assert result[1]["branche"] == "Handwerk" and result[1]["status"] == "offen"


def test_overpass_query_limits_radius_and_branch_filter_is_local():
    query = companies.overpass_query(47.38, 8.17, 80)
    assert "around:50000" in query, "Umkreis ist begrenzt"
    elements = [{"tags": {"name": "IT AG", "office": "it", "website": "it.ch"}},
                {"tags": {"name": "Beck", "shop": "bakery", "website": "beck.ch"}},
                {"tags": {"name": "Maler", "craft": "painter", "website": "maler.ch"}}]
    assert [c["name"] for c in companies.parse_overpass(elements, ["IT & Software"])] == ["IT AG"]
    assert [c["name"] for c in companies.parse_overpass(elements)] == ["IT AG", "Maler"], "Läden zählen nie"


def test_merge_keeps_checked_and_hidden_entries():
    old = [{"name": "A", "website": "https://a.ch", "status": "gefunden", "karriere": "https://a.ch/jobs",
            "ausgeblendet": True, "branche": ""}]
    new = [{"name": "A AG", "website": "https://www.a.ch", "status": "offen", "karriere": "", "branche": "IT & Software",
            "ausgeblendet": False},
           {"name": "B", "website": "https://b.ch", "status": "offen", "karriere": "", "branche": "", "ausgeblendet": False}]
    merged, added = companies.merge(old, new)
    assert added == 1
    assert merged[0]["karriere"] == "https://a.ch/jobs" and merged[0]["ausgeblendet"]
    assert merged[0]["branche"] == "IT & Software"


def test_career_link_from_homepage_prefers_job_system():
    html = """<a href="/news/karriere-event">Karrieretag 2026</a><a href="/ueber-uns">Über uns</a>
              <a href="/de/karriere">Karriere</a><a href="https://firma.refline.ch/123/jobs">Offene Stellen</a>"""
    assert companies.best_career_link(html, "https://www.firma.ch") == "https://firma.refline.ch/123/jobs"
    html = '<a href="/de/karriere">Karriere</a><a href="/jobticket">Jobticket</a>'
    assert companies.best_career_link(html, "https://www.firma.ch") == "https://www.firma.ch/de/karriere"
    assert companies.best_career_link('<a href="/kontakt">Kontakt</a>', "https://www.firma.ch") == ""
    assert companies.best_career_link('<a href="/webseiten">Webseite erstellen lassen</a>', "https://www.firma.ch") == ""


def test_find_career_page_respects_robots():
    session = FakeSession({"https://firma.ch/robots.txt": FakeResponse("https://firma.ch/robots.txt",
                                                                       "User-agent: *\nDisallow: /", 200, "text/plain"),
                           "https://firma.ch": '<a href="/jobs">Jobs</a>'})
    result = companies.find_career_page("https://firma.ch", session)
    assert result["status"] == "gesperrt"
    assert "https://firma.ch" not in session.calls


def test_find_career_page_tries_common_paths():
    home = "<html>" + "".join(f'<a href="/p{i}">Seite {i}</a>' for i in range(8)) + "</html>"
    session = FakeSession({"https://firma.ch": home,
                           "https://firma.ch/karriere": "<title>Start</title>",  # 200, aber ohne Stellenbezug
                           "https://firma.ch/jobs": "<title>Jobs</title><h1>Offene Stellen</h1>"})
    session.pages["https://firma.ch/karriere"] = FakeResponse("https://firma.ch", "<title>Start</title>")
    result = companies.find_career_page("https://firma.ch", session)
    assert result == {"karriere": "https://firma.ch/jobs", "status": "gefunden",
                      "hinweis": "über eine übliche Adresse gefunden"}


def test_find_career_page_reports_unreachable_and_empty_sites():
    assert companies.find_career_page("https://weg.ch", FakeSession({}))["status"] == "fehler"
    result = companies.find_career_page("https://leer.ch", FakeSession({"https://leer.ch": "<div id=app></div>"}))
    assert result["status"] == "keine" and "Browser" in result["hinweis"]


def test_check_career_pages_updates_and_saves(monkeypatch):
    data = {"firmen": [
        {"name": "A", "website": "https://a.ch", "status": "offen", "quelle": "OpenStreetMap"},
        {"name": "B", "website": "https://b.ch", "status": "offen", "ausgeblendet": True},
        {"name": "C", "website": "https://c.ch", "status": "gefunden", "karriere": "https://c.ch/x",
         "quelle": "von Hand", "quelle_karriere": "von Hand"},
    ]}
    monkeypatch.setattr(companies, "find_career_page", lambda url, s, r: {"karriere": url + "/jobs",
                                                                          "status": "gefunden", "hinweis": ""})
    progress = []
    counts = companies.check_career_pages(data, recheck=True, on_progress=lambda d, t, c: progress.append(c["name"]))
    assert progress == ["A"] and counts["gefunden"] == 1
    assert data["firmen"][0]["karriere"] == "https://a.ch/jobs" and data["firmen"][0]["geprueft"]
    assert data["firmen"][2]["karriere"] == "https://c.ch/x", "von Hand eingetragen bleibt"
    assert companies.load()["firmen"][0]["status"] == "gefunden"


def test_add_manual_rejects_duplicates():
    data = companies.load()
    companies.add_manual(data, "Firma", "www.firma.ch", "firma.ch/jobs")
    assert data["firmen"][0]["status"] == "gefunden"
    with pytest.raises(ValueError):
        companies.add_manual(data, "Nochmal", "https://firma.ch")
