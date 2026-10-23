"""Pfad- und API-Konfiguration. Werte kommen aus der `.env` und können im Tool geändert werden."""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
TEMPLATES_DIR = ROOT / "templates"

DEFAULTS = {
    "COUNTRY": "ch",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "https://api.venice.ai/api/v1",
    "LLM_MODEL": "claude-sonnet-5-5",
    "LLM_VISION_MODEL": "",
    "ADZUNA_APP_ID": "",
    "ADZUNA_APP_KEY": "",
}

PROVIDERS = {
    "Venice AI": {
        "LLM_BASE_URL": "https://api.venice.ai/api/v1",
        "LLM_MODEL": "claude-sonnet-5-5",
        "hinweis": "OpenAI-kompatibel, gute private Modelle. Key: https://venice.ai",
    },
    "OpenAI": {
        "LLM_BASE_URL": "https://api.openai.com/v1",
        "LLM_MODEL": "gpt-4o-mini",
        "hinweis": "Offizielles OpenAI. Key: https://platform.openai.com/api-keys",
    },
    "Eigen / anderer Anbieter": {
        "LLM_BASE_URL": "",
        "LLM_MODEL": "",
        "hinweis": "Beliebige OpenAI-kompatible API (z.B. Azure, lokal, anderer Host).",
    },
}

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def ensure_env_file() -> Path:
    """Legt `.env` aus der Vorlage an, falls sie fehlt."""
    if not ENV_PATH.exists() and ENV_EXAMPLE.exists():
        ENV_PATH.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    elif not ENV_PATH.exists():
        lines = ["# Bewerbungs-Tool – API-Einstellungen (nicht teilen, nicht hochladen)\n"]
        for key, value in DEFAULTS.items():
            lines.append(f"{key}={value}\n")
        ENV_PATH.write_text("".join(lines), encoding="utf-8")
    return ENV_PATH


def read_env_file() -> dict[str, str]:
    ensure_env_file()
    values = dict(DEFAULTS)
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if m := _ENV_LINE.match(stripped):
            values[m.group(1)] = _parse_value(m.group(2))
    return values


def write_env_file(updates: dict[str, str]) -> None:
    """Schreibt bekannte Schlüssel in die `.env`, ohne andere Zeilen/Kommentare zu verlieren."""
    ensure_env_file()
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and (m := _ENV_LINE.match(stripped)):
            key = m.group(1)
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                seen.add(key)
                continue
        new_lines.append(line if line.endswith("\n") else line + "\n")
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}\n")
    ENV_PATH.write_text("".join(new_lines), encoding="utf-8")


def reload() -> None:
    """Liest `.env` neu und setzt die Modul-Variablen (nach Speichern im Tool)."""
    global COUNTRY, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_VISION_MODEL
    global ADZUNA_APP_ID, ADZUNA_APP_KEY
    load_dotenv(ENV_PATH, override=True)
    values = read_env_file()
    for key, value in values.items():
        os.environ[key] = value
    COUNTRY = (values.get("COUNTRY") or "ch").lower()
    LLM_API_KEY = values.get("LLM_API_KEY") or ""
    LLM_BASE_URL = (values.get("LLM_BASE_URL") or DEFAULTS["LLM_BASE_URL"]).rstrip("/")
    LLM_MODEL = values.get("LLM_MODEL") or DEFAULTS["LLM_MODEL"]
    vision = (values.get("LLM_VISION_MODEL") or "").strip()
    LLM_VISION_MODEL = vision or LLM_MODEL
    ADZUNA_APP_ID = values.get("ADZUNA_APP_ID") or ""
    ADZUNA_APP_KEY = values.get("ADZUNA_APP_KEY") or ""


def save_api_settings(values: dict[str, str]) -> None:
    """Speichert API-Einstellungen, aktualisiert Laufzeitwerte und setzt den KI-Client zurück."""
    allowed = {k: str(values.get(k, "")).strip() for k in DEFAULTS}
    if allowed["COUNTRY"] not in ("ch", "de"):
        allowed["COUNTRY"] = "ch"
    allowed["LLM_BASE_URL"] = normalize_base_url(allowed["LLM_BASE_URL"])
    if err := validate_api_settings(allowed):
        raise ValueError(err)
    write_env_file(allowed)
    reload()
    try:
        from src import llm
        llm.reset_client()
    except Exception:
        pass
    try:
        from src import generate
        generate.refresh_locale()
    except Exception:
        pass
    try:
        from src.costs import CACHE_PATH
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
    except Exception:
        pass


def api_settings() -> dict[str, str]:
    """Aktuelle API-Werte für die Anzeige im Tool."""
    return {
        "COUNTRY": COUNTRY,
        "LLM_API_KEY": LLM_API_KEY,
        "LLM_BASE_URL": LLM_BASE_URL,
        "LLM_MODEL": LLM_MODEL,
        "LLM_VISION_MODEL": "" if LLM_VISION_MODEL == LLM_MODEL else LLM_VISION_MODEL,
        "ADZUNA_APP_ID": ADZUNA_APP_ID,
        "ADZUNA_APP_KEY": ADZUNA_APP_KEY,
    }


def mask_secret(value: str) -> str:
    if not value:
        return "(nicht gesetzt)"
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]


def normalize_base_url(url: str) -> str:
    """Korrigiert häufige Fehl-URLs (z.B. die OpenAI-Key-Verwaltungsseite)."""
    u = (url or "").strip().rstrip("/")
    lower = u.lower()
    if "platform.openai.com" in lower or lower.endswith("/api-keys"):
        return "https://api.openai.com/v1"
    if lower in {"https://api.openai.com", "https://openai.com", "https://www.openai.com"}:
        return "https://api.openai.com/v1"
    if lower in {"https://api.venice.ai", "https://venice.ai", "https://www.venice.ai"}:
        return "https://api.venice.ai/api/v1"
    return u


def validate_api_settings(values: dict[str, str]) -> str | None:
    """Gibt eine Fehlermeldung zurück oder None, wenn alles ok wirkt."""
    url = normalize_base_url(values.get("LLM_BASE_URL", ""))
    key = (values.get("LLM_API_KEY") or "").strip()
    model = (values.get("LLM_MODEL") or "").strip()
    if not url.startswith("http"):
        return "Die API-Basis-URL muss mit https:// beginnen."
    if "platform.openai.com" in url or "/api-keys" in url:
        return ("Falsche URL: Das ist die Website für API-Keys, nicht die API. "
                "Für OpenAI bitte https://api.openai.com/v1 verwenden.")
    if not key:
        return "Bitte einen API-Schlüssel eintragen."
    if "openai.com" in url and model.startswith("claude"):
        return (f"Modell «{model}» gibt es bei OpenAI nicht. "
                "Nimm z.B. gpt-4o-mini – oder wechsel zu Venice AI.")
    if "venice.ai" in url and key.startswith("sk-") and "venice" not in key.lower():
        # nur Hinweis, kein Block – sk- kann auch andere Anbieter sein
        pass
    return None


def friendly_api_error(exc: BaseException) -> str:
    """Macht typische API-/Cloudflare-Fehler für die Anzeige verständlich."""
    text = str(exc)
    low = text.lower()
    if "<html" in low or "cloudflare" in low or "cf-chl" in low or "enable javascript" in low:
        return (
            "Die API hat eine Website/Cloudflare-Seite statt einer KI-Antwort geliefert. "
            "Meist stimmt die Basis-URL nicht.\n\n"
            f"Aktuell: `{LLM_BASE_URL}`\n"
            "• OpenAI: `https://api.openai.com/v1`\n"
            "• Venice: `https://api.venice.ai/api/v1`\n\n"
            "Unter Einstellungen → API & KI korrigieren und «Verbindung testen»."
        )
    if "401" in text or "incorrect api key" in low or "invalid_api_key" in low:
        return "API-Schlüssel ungültig oder abgelehnt. Bitte unter API & KI prüfen."
    if "insufficient_quota" in low or "credit_balance" in low or "no credits remaining" in low:
        return (
            "Bei OpenAI sind keine Credits mehr vorhanden (Konto ohne Guthaben). "
            "Entweder unter platform.openai.com Guthaben aufladen, "
            "oder unter API & KI wieder zu Venice wechseln (mit Venice-Schlüssel und "
            "`https://api.venice.ai/api/v1`)."
        )
    if "429" in text and ("rate" in low or "quota" in low):
        return "API-Limit erreicht (zu viele Anfragen oder kein Guthaben). Kurz warten oder Anbieter/Konto prüfen."
    if "404" in text and "model" in low:
        return f"Modell nicht gefunden. Aktuell: `{LLM_MODEL}`. Unter API & KI ein gültiges Modell wählen."
    if len(text) > 400:
        return text[:400] + "…"
    return text


def llm_configured() -> bool:
    return bool(LLM_API_KEY)


def adzuna_configured() -> bool:
    return bool(ADZUNA_APP_ID and ADZUNA_APP_KEY)


# Beim Import einmal laden
COUNTRY = "ch"
LLM_API_KEY = ""
LLM_BASE_URL = DEFAULTS["LLM_BASE_URL"]
LLM_MODEL = DEFAULTS["LLM_MODEL"]
LLM_VISION_MODEL = DEFAULTS["LLM_MODEL"]
ADZUNA_APP_ID = ""
ADZUNA_APP_KEY = ""
reload()
