"""Unit-Tests für Stellentitel-Erkennung und dünne Jobseiten."""
from src.jobs import clean_job_title, is_thin_job_page, resolve_job_title, title_from_url


def test_clean_job_title_strips_site_suffix():
    assert clean_job_title("AI Engineer Job Details | Hero Group", "Hero Group") == "AI Engineer"
    assert clean_job_title("Stellenangebot | Aargauische Kantonalbank",
                           "Aargauische Kantonalbank") == ""


def test_clean_job_title_rejects_generic():
    assert clean_job_title("Jobtitel") == ""
    assert clean_job_title("Stellenangebot") == ""
    assert clean_job_title("Careers") == ""


def test_title_from_url_hero():
    url = "https://careers.hero-group.ch/job/AI-Engineer/4064-en_US/"
    assert title_from_url(url) == "AI Engineer"


def test_title_from_url_skips_ids():
    assert "4064" not in title_from_url(
        "https://careers.example.com/job/Software-Engineer/4064-en_US/"
    )


def test_is_thin_job_page_placeholders():
    thin = "Stellenangebot\nInhalt wird geladen...\n{{Jobtitel}}\n{{Pensum}}\n{{Ort}}\n"
    assert is_thin_job_page(thin) is True
    assert is_thin_job_page("x" * 50) is True
    rich = "Wir suchen eine erfahrene Software Engineerin. " * 20
    assert is_thin_job_page(rich) is False


def test_resolve_job_title_prefers_analysis():
    title = resolve_job_title(
        {},
        {"titel": "Software & Data Engineer"},
        {"title": "Stellenangebot | Bank"},
        "https://example.com/job/Other-Role/1",
    )
    assert title == "Software & Data Engineer"


def test_resolve_job_title_falls_back_to_url():
    title = resolve_job_title(
        {},
        {"titel": "Stellenangebot"},
        {"title": "Jobtitel"},
        "https://careers.hero-group.ch/job/AI-Engineer/4064-en_US/",
    )
    assert title == "AI Engineer"
