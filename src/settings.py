import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.config import DATA_DIR

SETTINGS_PATH = DATA_DIR / "einstellungen.json"

_PICKER_CODE = """
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
print(filedialog.askdirectory(initialdir=sys.argv[1], title="Speicherort für Bewerbungen wählen") or "")
"""


def _default_save_dir() -> str:
    documents_dir = Path.home() / "Documents"
    base = documents_dir if documents_dir.exists() else Path.home()
    return str(base / "Bewerbungen")


def load() -> dict:
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8")) if SETTINGS_PATH.exists() else {}
    data.setdefault("save_dir", _default_save_dir())
    return data


def save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_save_dir() -> str:
    return load()["save_dir"]


def set_save_dir(path: str) -> None:
    data = load()
    data["save_dir"] = path
    save(data)


def pick_folder(initial: str) -> str | None:
    """Öffnet den Windows-Ordnerdialog (in eigenem Prozess, weil Streamlit nicht im Hauptthread läuft)."""
    start = initial if Path(initial).exists() else str(Path.home())
    result = subprocess.run([sys.executable, "-c", _PICKER_CODE, start],
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
