import shutil

import yaml

from src.config import DATA_DIR, ROOT

PROFILE_PATH = DATA_DIR / "profile.yaml"
EXAMPLE_PATH = ROOT / "profile.example.yaml"


def load_profile_text() -> str:
    if not PROFILE_PATH.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(EXAMPLE_PATH, PROFILE_PATH)
    return PROFILE_PATH.read_text(encoding="utf-8")


def save_profile_text(text: str) -> None:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise yaml.YAMLError("Das Profil muss ein YAML-Objekt (Schlüssel: Wert) sein.")
    PROFILE_PATH.write_text(text, encoding="utf-8")


def load_profile() -> dict:
    return yaml.safe_load(load_profile_text()) or {}
