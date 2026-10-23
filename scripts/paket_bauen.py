"""Baut dist/bewerbungs-tool-<version>.zip zum Weitergeben (z.B. per USB-Stick).

Nur ausdrücklich erlaubte Dateien kommen ins Paket; persönliche Daten (data/, .env, output/) nie.
Aufruf: .venv\\Scripts\\python scripts\\paket_bauen.py
"""
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src import __version__  # noqa: E402

FILES = ["app.py", "start.bat", "requirements.txt", ".env.example", "profile.example.yaml",
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
    """Name, Adresse und Kontakt aus dem eigenen Profil."""
    profile = ROOT / "data" / "profile.yaml"
    if not profile.exists():
        return []
    import yaml
    data = (yaml.safe_load(profile.read_text(encoding="utf-8")) or {}).get("persoenlich") or {}
    values = [str(data.get(k) or "") for k in ("name", "strasse", "email", "telefon")]
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
            archive.write(path, Path("bewerbungs-tool") / path.relative_to(ROOT))
    print(f"{target} ({len(paths)} Dateien, {target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
