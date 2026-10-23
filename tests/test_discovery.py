from email.message import EmailMessage

from src import discovery


def test_email_html_retains_links_and_ignores_attachment():
    message = EmailMessage()
    message.set_content('<p>Data Engineer</p><a href="https://www.jobs.ch/de/stellenangebote/detail/123/">Details</a>', subtype="html")
    message.add_attachment(b"secret attachment", maintype="application", subtype="octet-stream", filename="private.bin")
    text = discovery.email_text(message.as_bytes())
    assert "Data Engineer" in text
    assert "https://www.jobs.ch/de/stellenangebote/detail/123/" in text
    assert "secret attachment" not in text


def test_dedup_tracking_preserves_other_query_ids_and_excludes():
    items = [{"title": "Engineer", "url": "https://www.jobs.ch/de/detail/123/?utm_source=a"},
             {"title": "Engineer", "url": "https://www.jobs.ch/de/detail/123/?utm_source=b"},
             {"title": "Praktikum", "url": "https://example.org/?job=1"},
             {"title": "Engineer", "url": "https://example.org/?job=2"},
             {"title": "Engineer", "url": "https://example.org/?job=3"}]
    result = discovery.deduplicate(items, "Praktikum")
    assert len(result) == 3
    assert result[0]["url"] == "https://www.jobs.ch/de/detail/123"
    assert result[1]["url"] != result[2]["url"]


def test_import_rejects_hallucinated_and_unsafe_urls(monkeypatch):
    from src import llm
    monkeypatch.setattr(llm, "chat_json", lambda *a, **kw: {"stellen": [
        {"title": "Engineer", "url": "https://invented.example/job"},
        {"title": "Analyst", "url": "javascript:alert(1)"}]})
    result = discovery.import_alert("Neue passende Stellen in deiner Region. javascript:alert(1)")
    assert len(result) == 2
    assert all(not item["url"] for item in result)


def test_evaluation_uses_supplied_text_without_fetch(monkeypatch):
    from src import generate
    captured = {}
    def analyze(profile, text, **kwargs):
        captured.update(profile=profile, text=text)
        return {"score": 80}
    monkeypatch.setattr(generate, "analyze_match", analyze)
    monkeypatch.setattr(discovery.jobs, "fetch_job", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("network access")))
    original = {"wuensche": "bestehende Wünsche"}
    result = discovery.evaluate(original, {"description": "Aufgaben und Anforderungen. " * 20}, "80 Prozent")
    assert result["analysis"]["score"] == 80
    assert captured["profile"]["wuensche"]["stellensuche"] == "80 Prozent"
    assert original["wuensche"] == "bestehende Wünsche"


def test_api_failure_does_not_expose_key(monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("https://api.example/?app_key=SECRET")
    monkeypatch.setattr(discovery.jobs, "search_adzuna", fail)
    items, errors = discovery.search_api({"terms": ["Engineer"], "location": "Zürich", "radius": 25})
    assert not items
    assert len(errors) == 1
    assert "SECRET" not in errors[0]
