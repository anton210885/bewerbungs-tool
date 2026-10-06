"""Werte, die bei jedem Durchlauf der App frisch geladen werden (Profil, Einstellungen)."""
from src import settings
from src.config import llm_configured
from src.profile import is_example_profile, load_profile

LLM_OK = False
profile: dict = {}
PROFILE_READY = False
NAME = ""
CV_TEMPLATE = ""
CV_ACCENT = ""
CV_OPTIONS: dict = {}


def refresh() -> None:
    global LLM_OK, profile, PROFILE_READY, NAME, CV_TEMPLATE, CV_ACCENT, CV_OPTIONS
    LLM_OK = llm_configured()
    profile = load_profile()
    PROFILE_READY = not is_example_profile(profile)
    NAME = (profile.get("persoenlich") or {}).get("name", "")
    CV_TEMPLATE, CV_ACCENT = settings.get_cv_style()
    CV_OPTIONS = settings.get_cv_options()
