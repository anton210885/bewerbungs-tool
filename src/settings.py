import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src import config


def _settings_path():
    return config.data_dir() / "einstellungen.json"


_PICKER_CODE = """
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
print(filedialog.askdirectory(initialdir=sys.argv[1], title=sys.argv[2]) or "")
"""


def _default_save_dir() -> str:
    """Pro Profil ein eigener Unterordner, damit sich die Bewerbungen mehrerer Personen nicht mischen."""
    from src import profiles

    documents_dir = Path.home() / "Documents"
    base = documents_dir if documents_dir.exists() else Path.home()
    return str(base / "Bewerbungen" / profiles.display_name(config.active_profile()))


def load() -> dict:
    data = json.loads(_settings_path().read_text(encoding="utf-8")) if _settings_path().exists() else {}
    data.setdefault("save_dir", _default_save_dir())
    return data


def save(data: dict) -> None:
    config.data_dir().mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_save_dir() -> str:
    return load()["save_dir"]


def set_save_dir(path: str) -> None:
    data = load()
    data["save_dir"] = path
    save(data)


def get_cv_style() -> tuple[str, str]:
    """Gewählte Lebenslauf-Vorlage und Akzentfarbe."""
    from src.generate import CV_TEMPLATES, DEFAULT_TEMPLATE

    data = load()
    template = data.get("cv_template", DEFAULT_TEMPLATE)
    if template not in CV_TEMPLATES:
        template = DEFAULT_TEMPLATE
    return template, data.get("cv_accent") or CV_TEMPLATES[template]["farbe"]


def set_cv_style(template: str, accent: str | None = None) -> None:
    data = load()
    data["cv_template"] = template
    data["cv_accent"] = accent
    save(data)


def get_cv_options() -> dict:
    from src.generate import DEFAULT_CV_OPTIONS

    return {**DEFAULT_CV_OPTIONS, **load().get("cv_options", {})}


def set_cv_options(options: dict | None) -> None:
    data = load()
    if options is None:
        data.pop("cv_options", None)
    else:
        data["cv_options"] = options
    save(data)


def get_zeugnis_dir() -> str:
    return load().get("zeugnis_dir") or str(Path(get_save_dir()) / "Zeugnisse")


def set_zeugnis_dir(path: str) -> None:
    data = load()
    data["zeugnis_dir"] = path
    save(data)


def pick_folder(initial: str, title: str = "Speicherort für Bewerbungen wählen") -> str | None:
    """Öffnet den Windows-Ordnerdialog (in eigenem Prozess, weil Streamlit nicht im Hauptthread läuft)."""
    start = next((str(p) for p in (Path(initial), *Path(initial).parents) if p.exists()), str(Path.home()))
    result = subprocess.run([sys.executable, "-c", _PICKER_CODE, start, title],
                            capture_output=True, text=True, timeout=600)
    chosen = result.stdout.strip()
    return str(Path(chosen)) if chosen else None


def copy_files(files: list[Path], target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in files:
        if f.exists():
            copied.append(Path(shutil.copy2(f, target_dir / f.name)))
    return copied


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
