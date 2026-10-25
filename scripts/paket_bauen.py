"""Baut dist/bewerbungs-tool-<version>.zip zum Weitergeben (z.B. per USB-Stick).

Nur ausdrücklich erlaubte Dateien kommen ins Paket; persönliche Daten (data/, .env, output/) nie.
Aufruf: .venv\\Scripts\\python scripts\\paket_bauen.py
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import __version__  # noqa: E402

FILES = ["app.py", "start.bat", "start.command", "requirements.txt", ".env.example", "profile.example.yaml",
         "suche_taeglich.py", "CHANGELOG.md", "ANLEITUNG.txt", "pyproject.toml"]
DIRS = ["src", "ui", "templates", ".streamlit"]
SKIP_SUFFIXES = {".pyc", ".pyo", ".db", ".log"}
FORBIDDEN = {".env", "profile.yaml", "bewerbungen.db", "einstellungen.json"}


def collect() -> list[Path]:
    paths = [ROOT / f for f in FILES]
    for folder in DIRS:
        paths += [p for p in sorted((ROOT / folder).rglob("*"))
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix not in SKIP_SUFFIXES]
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        sys.exit(f"Fehlende Dateien: {', '.join(missing)}")
    return paths


def secrets() -> list[str]:
    """Werte aus der eigenen .env, die nie im Paket stehen dürfen."""
    env = ROOT / ".env"
    if not env.exists():
        return []
    values = re.findall(r"^[ \t]*\w*(?:KEY|ID|TOKEN|SECRET)\w*[ \t]*=[ \t]*(\S{8,})", env.read_text(encoding="utf-8"),
                        re.M)
    return [v.strip("'\"") for v in values] + personal()


def personal() -> list[str]:
    """Name, Adresse und Kontakt aus allen Personen-Profilen (und einem alten data/profile.yaml)."""
    import yaml

    values = []
    for profile in [ROOT / "data" / "profile.yaml", *sorted((ROOT / "data" / "profile").glob("*/profile.yaml"))]:
        if not profile.exists():
            continue
        data = (yaml.safe_load(profile.read_text(encoding="utf-8")) or {}).get("persoenlich") or {}
        values += [str(data.get(k) or "") for k in ("name", "strasse", "email", "telefon")]
        values += str(data.get("name") or "").split()
    return [v for v in values if len(v) >= 4 and v != "Max Muster"]


def check(paths: list[Path]) -> None:
    hidden = secrets()
    for path in paths:
        if path.name in FORBIDDEN:
            sys.exit(f"Abbruch: {path.name} darf nicht ins Paket.")
        content = path.read_bytes()
        if any(s.encode() in content for s in hidden):
            sys.exit(f"Abbruch: {path.relative_to(ROOT)} enthält einen Schlüssel aus deiner .env.")


def main() -> None:
    paths = collect()
    check(paths)
    target = ROOT / "dist" / f"bewerbungs-tool-{__version__}.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            name = (Path("bewerbungs-tool") / path.relative_to(ROOT)).as_posix()
            if path.suffix == ".command":
                # Unter macOS per Doppelklick ausführbar (rwxr-xr-x)
                info = zipfile.ZipInfo.from_file(path, name)
                info.external_attr = 0o100755 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
            else:
                archive.write(path, name)
    print(f"{target} ({len(paths)} Dateien, {target.stat().st_size // 1024} KB)")

    # Zusätzlich entpackt, z.B. zum direkten Kopieren auf einen USB-Stick
    folder = target.parent / target.stem
    if folder.exists():
        shutil.rmtree(folder)
    with zipfile.ZipFile(target) as archive:
        archive.extractall(folder)
    print(f"{folder / 'bewerbungs-tool'} (entpackt)")


if __name__ == "__main__":
    main()
