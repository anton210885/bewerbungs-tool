"""Wird von der Windows-Aufgabenplanung täglich gestartet: prüft die gespeicherten Suchen aller Profile."""
from datetime import datetime

from src import config, profiles, searches
from src.profile import is_example_profile, load_profile


def main() -> None:
    config.active_profile()  # übernimmt bei Bedarf Daten aus der Zeit vor den Profilen
    for entry in profiles.list_profiles():
        config.set_active_profile(entry["slug"], persist=False)
        profile = load_profile()
        if is_example_profile(profile) or not searches.list_searches():
            continue
        lines = []
        errors = searches.run_all(profile, on_progress=lines.append)
        with (config.data_dir() / "suche_taeglich.log").open("a", encoding="utf-8") as log:
            log.write(f"\n=== {datetime.now():%d.%m.%Y %H:%M} ===\n" + "\n".join(lines + errors) + "\n")


if __name__ == "__main__":
    main()
