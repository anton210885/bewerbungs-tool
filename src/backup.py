"""Sicherung aller persönlichen Daten (Profil, Unterlagen, Fotos, Tracker) als ZIP-Datei."""
import io
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from src import config, settings
from src.config import DATA_ROOT, ROOT

MARKER = "bewerbungs-tool-sicherung.txt"
REMIND_AFTER_DAYS = 7


def create_backup() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MARKER, f"Sicherung vom {datetime.now():%d.%m.%Y %H:%M}\n")
        for path in sorted(DATA_ROOT.rglob("*")):
            if path.is_file():
                z.write(path, (Path("data") / path.relative_to(DATA_ROOT)).as_posix())
    data = settings.load()
    data["letzte_sicherung"] = datetime.now().isoformat(timespec="seconds")
    settings.save(data)
    return buf.getvalue()


def backup_filename() -> str:
    return f"Bewerbungs-Tool_Sicherung_{datetime.now():%Y-%m-%d_%H%M}.zip"


def save_backup_to_folder() -> Path:
    target = Path(settings.get_save_dir()) / "Sicherungen"
    target.mkdir(parents=True, exist_ok=True)
    path = target / backup_filename()
    path.write_bytes(create_backup())
    return path


def days_since_last_backup() -> int | None:
    last = settings.load().get("letzte_sicherung")
    return (datetime.now() - datetime.fromisoformat(last)).days if last else None


def restore_backup(data: bytes) -> Path:
    """Spielt eine Sicherung ein. Der bisherige Stand wird vorher in einen eigenen Ordner kopiert."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if MARKER not in names:
            raise ValueError("Diese ZIP-Datei ist keine Sicherung des Bewerbungs-Tools.")
        for name in names:
            parts = PurePosixPath(name).parts
            if name != MARKER and (not parts or parts[0] != "data" or ".." in parts or name.startswith("/")):
                raise ValueError(f"Ungültiger Eintrag in der Sicherung: {name}")
        previous = ROOT / f"data_vor_wiederherstellung_{datetime.now():%Y%m%d-%H%M%S}"
        if DATA_ROOT.exists():
            shutil.copytree(DATA_ROOT, previous)
        for name in names:
            if name != MARKER and not name.endswith("/"):
                target = ROOT / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
    config.reset_active_profile()
    return previous
