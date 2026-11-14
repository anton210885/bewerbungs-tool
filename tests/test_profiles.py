import json

import pytest

from src import config, db, documents, profile, profiles, settings


def test_first_start_creates_default_profile(isolated_data):
    assert config.active_profile() == "mein-profil"
    assert profiles.list_profiles() == [{"slug": "mein-profil", "name": "Mein Profil"}]
    assert (isolated_data / "aktives_profil.txt").read_text(encoding="utf-8") == "mein-profil"


def test_legacy_data_moves_into_profile_named_after_person(isolated_data):
    (isolated_data / "dokumente" / "lebenslauf").mkdir(parents=True)
    (isolated_data / "dokumente" / "lebenslauf" / "cv.pdf").write_bytes(b"%PDF")
    (isolated_data / "profile.yaml").write_text("persoenlich:\n  name: Anna Müller\n", encoding="utf-8")
    (isolated_data / "kosten.json").write_text("{}", encoding="utf-8")
    (config.OUTPUT_ROOT / "basis").mkdir(parents=True)
    (config.OUTPUT_ROOT / "basis" / "cv.pdf").write_bytes(b"%PDF")

    assert config.active_profile() == "anna-muller"
    folder = config.PROFILES_DIR / "anna-muller"
    assert (folder / "dokumente" / "lebenslauf" / "cv.pdf").exists()
    assert (folder / "profile.yaml").exists()
    assert not (isolated_data / "profile.yaml").exists()
    assert (isolated_data / "kosten.json").exists(), "Kosten gelten für alle und bleiben im Hauptordner"
    assert (config.OUTPUT_ROOT / "anna-muller" / "basis" / "cv.pdf").exists()
    assert profiles.display_name("anna-muller") == "Anna Müller"


def test_shared_place_cache_never_becomes_a_profile(isolated_data):
    config.active_profile()
    before = {p["slug"] for p in profiles.list_profiles()}
    (isolated_data / "orte.json").write_text("{}", encoding="utf-8")
    (isolated_data / "vektoren").mkdir()
    (isolated_data / "vektoren" / "modell.npz").write_bytes(b"")
    config.reset_active_profile()
    config.active_profile()
    assert {p["slug"] for p in profiles.list_profiles()} == before
    assert (isolated_data / "orte.json").exists()
    assert (isolated_data / "vektoren" / "modell.npz").exists()


def test_profiles_are_isolated(isolated_data):
    first = config.active_profile()
    db.init_db()
    db.add_application({"source": "Link", "external_id": "1", "title": "Data Engineer"})
    profile.save_profile_text("persoenlich:\n  name: Anna\n")

    profiles.switch(profiles.create("Marco"))
    db.init_db()
    assert db.list_applications() == []
    assert profile.is_example_profile(profile.load_profile())
    assert documents.active_documents("lebenslauf") == []
    assert settings.get_save_dir().endswith("Marco")

    profiles.switch(first)
    assert [a["title"] for a in db.list_applications()] == ["Data Engineer"]
    assert profile.load_profile()["persoenlich"]["name"] == "Anna"


def test_create_rejects_duplicates_and_empty_names(isolated_data):
    config.active_profile()
    profiles.create("Marco")
    with pytest.raises(ValueError):
        profiles.create("  marco ")
    with pytest.raises(ValueError):
        profiles.create("   ")
    assert profiles.create("Marco Rossi") == "marco-rossi"


def test_delete_moves_profile_away_and_switches(isolated_data):
    first = config.active_profile()
    second = profiles.create("Marco")
    profiles.switch(second)
    profiles.delete(second)
    assert config.active_profile() == first
    assert [p["slug"] for p in profiles.list_profiles()] == [first]
    assert any(p.name.startswith("marco_") for p in (isolated_data / "geloeschte_profile").iterdir())
    with pytest.raises(ValueError):
        profiles.delete(first)


def test_invalid_active_profile_falls_back(isolated_data):
    config.active_profile()
    profiles.create("Marco")
    (isolated_data / "aktives_profil.txt").write_text("gibt-es-nicht", encoding="utf-8")
    config.reset_active_profile()
    assert config.active_profile() == "marco"  # erstes Profil alphabetisch
    assert json.loads((config.PROFILES_DIR / "marco" / "profil.json").read_text(encoding="utf-8"))["name"] == "Marco"
