import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
TEMPLATES_DIR = ROOT / "templates"

# "ch" = Schweiz, "de" = Deutschland
COUNTRY = os.getenv("COUNTRY", "ch").lower()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.venice.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b")

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")


def llm_configured() -> bool:
    return bool(LLM_API_KEY)


def adzuna_configured() -> bool:
    return bool(ADZUNA_APP_ID and ADZUNA_APP_KEY)
