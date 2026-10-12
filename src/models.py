"""KI-Modelle bei Venice: verfügbare Modelle, Datenschutz-Stufe und die aktuelle Auswahl."""
import json
import time

import requests

from src import config, settings
from src.config import DATA_DIR

CACHE_PATH = DATA_DIR / "venice_modelle.json"
CACHE_SECONDS = 24 * 3600

RECOMMENDED = {
    "claude-sonnet-5-5": "Claude Sonnet 5.5 – beste Texte auf Deutsch",
    "kimi-k3": "Kimi K3 – sehr gut, privat, versteht Bilder",
    "grok-4-7": "Grok 4.7 – gut, privat, versteht Bilder",
    "deepseek-v4-pro": "DeepSeek V4 Pro – privat und günstig (ohne Bilder)",
    "z-ai-glm-5-3": "GLM 5.3 – privat (ohne Bilder)",
}
PRIVATE_VISION_FALLBACK = "kimi-k3"
PRIVACY_LABELS = {
    "private": "Privat – Venice speichert nichts, Anbieter sieht nichts",
    "anonymized": "Anonymisiert – läuft beim Hersteller (z.B. Anthropic), ohne deinen Namen/Konto",
}


def list_models(force: bool = False) -> list[dict]:
    """Textmodelle mit Datenschutz-Stufe, Bildverständnis und Preis (USD pro 1 Mio. Tokens)."""
    if not force and CACHE_PATH.exists() and time.time() - CACHE_PATH.stat().st_mtime < CACHE_SECONDS:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if "venice.ai" not in config.LLM_BASE_URL or not config.LLM_API_KEY:
        return []
    try:
        resp = requests.get(f"{config.LLM_BASE_URL}/models",
                            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                            timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else []
    models = []
    for m in resp.json().get("data", []):
        spec = m.get("model_spec") or {}
        if spec.get("offline") or m.get("type", "text") != "text":
            continue
        pricing = spec.get("pricing") or {}
        models.append({
            "id": m["id"],
            "name": spec.get("name") or m["id"],
            "privacy": spec.get("privacy", ""),
            "vision": bool((spec.get("capabilities") or {}).get("supportsVision")),
            "preis_in": (pricing.get("input") or {}).get("usd"),
            "preis_out": (pricing.get("output") or {}).get("usd"),
        })
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(models, ensure_ascii=False, indent=1), encoding="utf-8")
    return models


def model_info(model_id: str) -> dict | None:
    return next((m for m in list_models() if m["id"] == model_id), None)


def current_model() -> str:
    return settings.load().get("llm_model") or config.LLM_MODEL


def set_model(model_id: str | None) -> None:
    data = settings.load()
    data["llm_model"] = model_id
    settings.save(data)


def current_vision_model() -> str:
    """Modell für Bilder (Scans, Fotos). Kann das gewählte Modell keine Bilder, wird ein passendes gewählt."""
    model = current_model()
    info = model_info(model)
    if info is None or info["vision"]:
        return model
    if config.LLM_VISION_MODEL and config.LLM_VISION_MODEL != config.LLM_MODEL:
        return config.LLM_VISION_MODEL
    return PRIVATE_VISION_FALLBACK if info["privacy"] == "private" else config.LLM_VISION_MODEL
