"""Mehrere Personen in einer Installation: jedes Profil hat einen eigenen Daten- und Ausgabeordner.

Gemeinsam bleiben nur der API-Zugang (.env) und die Kostenübersicht, weil beide am selben Schlüssel hängen.
"""
import json
import re
import shutil
import unicodedata
from datetime import datetime

import yaml

from src import config

META_NAME = "profil.json"
DELETED_NAME = "geloeschte_profile"
# Dateien, die für alle Profile gelten und beim Übernehmen alter Daten im Hauptordner bleiben
GLOBAL_FILES = {"kosten.json", "kosten_anbieter.json", "venice_modelle.json", "aktives_profil.txt"}
EXAMPLE_NAME = "Max Muster"


def _deleted_dir():
    return config.DATA_ROOT / DELETED_NAME


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40] or "profil"


def _unique_slug(name: str) -> str:
    base = slug = slugify(name)
    counter = 2
    while (config.PROFILES_DIR / slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _write_meta(slug: str, name: str) -> None:
    folder = config.PROFILES_DIR / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / META_NAME).write_text(json.dumps({"name": name}, ensure_ascii=False, indent=2), encoding="utf-8")


def display_name(slug: str) -> str:
    meta = config.PROFILES_DIR / slug / META_NAME
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("name") or slug
    except (OSError, ValueError):
        return slug


def list_profiles() -> list[dict]:
    """[{"slug": ..., "name": ...}] alphabetisch nach Name."""
    if not config.PROFILES_DIR.exists():
        return []
    folders = [p.name for p in config.PROFILES_DIR.iterdir() if p.is_dir()]
    return sorted(({"slug": s, "name": display_name(s)} for s in folders), key=lambda p: p["name"].casefold())


def create(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValueError("Bitte einen Namen für das Profil eingeben.")
    if any(p["name"].casefold() == name.casefold() for p in list_profiles()):
        raise ValueError(f"Ein Profil «{name}» gibt es schon.")
    slug = _unique_slug(name)
    _write_meta(slug, name)
    return slug


def rename(slug: str, name: str) -> None:
    name = " ".join(name.split())
    if not name:
        raise ValueError("Bitte einen Namen eingeben.")
    if any(p["name"].casefold() == name.casefold() and p["slug"] != slug for p in list_profiles()):
        raise ValueError(f"Ein Profil «{name}» gibt es schon.")
    _write_meta(slug, name)


def switch(slug: str) -> None:
    if not (config.PROFILES_DIR / slug).is_dir():
        raise ValueError("Dieses Profil gibt es nicht.")
    config.set_active_profile(slug)


def delete(slug: str) -> None:
    """Verschiebt das Profil in «geloeschte_profile» statt es endgültig zu löschen."""
    profiles = list_profiles()
    if len(profiles) <= 1:
        raise ValueError("Das letzte Profil kann nicht gelöscht werden.")
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    _deleted_dir().mkdir(parents=True, exist_ok=True)
    shutil.move(str(config.PROFILES_DIR / slug), str(_deleted_dir() / f"{slug}_{stamp}"))
    output = config.OUTPUT_ROOT / slug
    if output.exists():
        shutil.move(str(output), str(_deleted_dir() / f"{slug}_{stamp}_output"))
    if config.active_profile() == slug:
        switch(next(p["slug"] for p in profiles if p["slug"] != slug))


def _legacy_name() -> str:
    """Name für Daten aus der Zeit vor den Profilen: Name aus dem alten profile.yaml."""
    try:
        data = yaml.safe_load((config.DATA_ROOT / "profile.yaml").read_text(encoding="utf-8")) or {}
        name = str((data.get("persoenlich") or {}).get("name") or "").strip()
    except (OSError, yaml.YAMLError):
        name = ""
    return name if name and name != EXAMPLE_NAME else "Mein Profil"


def migrate_legacy() -> str | None:
    """Übernimmt Daten, die noch direkt in data/ liegen (alte Version oder alte Sicherung), in ein Profil."""
    root = config.DATA_ROOT
    if not root.exists():
        return None
    legacy = [p for p in root.iterdir()
              if p.name not in GLOBAL_FILES and p != config.PROFILES_DIR and p.name != DELETED_NAME]
    if not legacy:
        return None
    name = _legacy_name()
    if any(p["name"] == name for p in list_profiles()):
        name = f"{name} (übernommen {datetime.now():%d.%m.%Y %H:%M})"
    slug = _unique_slug(name)
    _write_meta(slug, name)
    target = config.PROFILES_DIR / slug
    for path in legacy:
        shutil.move(str(path), str(target / path.name))
    # Bisher erzeugte Dokumente gehören zum selben Profil
    known = {p["slug"] for p in list_profiles()}
    if config.OUTPUT_ROOT.exists():
        old_output = [p for p in config.OUTPUT_ROOT.iterdir() if p.name not in known]
        if old_output:
            (config.OUTPUT_ROOT / slug).mkdir(parents=True, exist_ok=True)
            for path in old_output:
                shutil.move(str(path), str(config.OUTPUT_ROOT / slug / path.name))
    return slug


def ensure_ready() -> str:
    """Alte Daten übernehmen, mindestens ein Profil sicherstellen und das aktive Profil liefern."""
    migrated = migrate_legacy()
    profiles = list_profiles()
    if not profiles:
        migrated = create("Mein Profil")
        profiles = list_profiles()
    slugs = [p["slug"] for p in profiles]
    try:
        active = config.ACTIVE_PROFILE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        active = ""
    if active not in slugs:
        active = migrated if migrated in slugs else slugs[0]
        config.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        config.ACTIVE_PROFILE_PATH.write_text(active, encoding="utf-8")
    return active
