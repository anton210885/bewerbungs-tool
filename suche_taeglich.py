"""Wird von der Windows-Aufgabenplanung täglich gestartet: prüft alle gespeicherten Suchen auf neue Stellen."""
from datetime import datetime

from src import searches
from src.config import DATA_DIR
from src.profile import is_example_profile, load_profile

LOG_PATH = DATA_DIR / "suche_taeglich.log"


def main() -> None:
    profile = load_profile()
    if is_example_profile(profile):
        return
    lines = []
    errors = searches.run_all(profile, on_progress=lines.append)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {datetime.now():%d.%m.%Y %H:%M} ===\n" + "\n".join(lines + errors) + "\n")


if __name__ == "__main__":
    main()
