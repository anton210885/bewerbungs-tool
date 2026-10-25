import pytest

from src import config


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Jeder Test arbeitet in einem leeren Datenordner, nie in den echten Daten unter data/."""
    root = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_ROOT", root)
    monkeypatch.setattr(config, "PROFILES_DIR", root / "profile")
    monkeypatch.setattr(config, "ACTIVE_PROFILE_PATH", root / "aktives_profil.txt")
    monkeypatch.setattr(config, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(config, "_active_profile", None)
    return root
