import shutil

import yaml

from src.config import DATA_DIR, ROOT

PROFILE_PATH = DATA_DIR / "profile.yaml"
BACKUP_PATH = DATA_DIR / "profile.backup.yaml"
EXAMPLE_PATH = ROOT / "profile.example.yaml"
EXAMPLE_NAME = "Max Muster"


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


def is_example_profile(profile: dict) -> bool:
    return (profile.get("persoenlich") or {}).get("name") == EXAMPLE_NAME


def save_generated_profile(new: dict) -> None:
    """Speichert ein von der KI erstelltes Profil. Foto und eigene Zusatzinfos bleiben erhalten."""
    old = load_profile()
    if not is_example_profile(old):
        shutil.copy(PROFILE_PATH, BACKUP_PATH)
        old_p = old.get("persoenlich") or {}
        new.setdefault("persoenlich", {})
        if old_p.get("foto"):
            new["persoenlich"]["foto"] = old_p["foto"]
        for key in ("weitere_infos", "referenzen"):
            if old.get(key) and not new.get(key):
                new[key] = old[key]
    new.setdefault("persoenlich", {}).setdefault("foto", "")
    if not new.get("referenzen"):
        new["referenzen"] = "Auf Anfrage"
    header = (
        "# Von der KI aus deinen Unterlagen erstellt. Bitte prüfen und bei Bedarf ergänzen.\n"
        "# Tipp: Unter 'weitere_infos' z.B. Verfügbarkeit, Pensum und Lohnvorstellung eintragen.\n\n"
    )
    PROFILE_PATH.write_text(
        header + yaml.safe_dump(new, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
