"""Kostenübersicht: lokale Schätzung aus Token-Verbrauch + Anbieter-Guthaben (Venice)."""
import json
from datetime import date, datetime

import requests

from src import config
from src.config import DATA_ROOT

USAGE_PATH = DATA_ROOT / "kosten.json"
CACHE_PATH = DATA_ROOT / "kosten_anbieter.json"
CACHE_SECONDS = 5 * 60


def _load_local() -> dict:
    if USAGE_PATH.exists():
        try:
            return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"eintraege": [], "gesamt_usd": 0.0}


def _save_local(data: dict) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    USAGE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _price_per_million(model: str) -> tuple[float, float]:
    """USD pro 1 Mio. Input-/Output-Tokens. Kein API-/Dateizugriff im Hot Path."""
    defaults = {
        # Embeddings (nur Input); ohne Eintrag galt der Standardwert, rund 50-mal zu hoch
        "text-embedding-3-small": (0.02, 0.0),
        "text-embedding-3-large": (0.13, 0.0),
        "text-embedding-bge-m3": (0.15, 0.0),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "claude-sonnet-5-5": (3.0, 15.0),
        "kimi-k3": (3.75, 18.75),
    }
    for key, prices in defaults.items():
        if key in (model or ""):
            return prices
    return (1.0, 3.0)


def estimate_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = _price_per_million(model)
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


def record_usage(model: str, prompt_tokens: int, completion_tokens: int,
                 source: str = "chat") -> float:
    """Speichert einen API-Aufruf und gibt die geschätzten USD zurück."""
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    usd = estimate_usd(model, prompt_tokens, completion_tokens)
    data = _load_local()
    data["eintraege"].append({
        "zeit": datetime.now().isoformat(timespec="seconds"),
        "modell": model,
        "quelle": source,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "usd": round(usd, 6),
        "anbieter": "venice" if "venice.ai" in config.LLM_BASE_URL else (
            "openai" if "openai.com" in config.LLM_BASE_URL else "andere"),
    })
    # nur die letzten 2000 Einträge behalten
    data["eintraege"] = data["eintraege"][-2000:]
    data["gesamt_usd"] = round(sum(e.get("usd", 0) for e in data["eintraege"]), 6)
    _save_local(data)
    return usd


def local_summary() -> dict:
    """Zusammenfassung der lokal erfassten Kosten."""
    data = _load_local()
    today = date.today().isoformat()
    month = date.today().strftime("%Y-%m")
    heute = monat = gesamt = 0.0
    tokens_heute = 0
    for e in data.get("eintraege") or []:
        usd = float(e.get("usd") or 0)
        gesamt += usd
        zeit = str(e.get("zeit") or "")
        if zeit.startswith(today):
            heute += usd
            tokens_heute += int(e.get("prompt_tokens") or 0) + int(e.get("completion_tokens") or 0)
        if zeit.startswith(month):
            monat += usd
    return {
        "heute_usd": round(heute, 4),
        "monat_usd": round(monat, 4),
        "gesamt_usd": round(gesamt, 4),
        "tokens_heute": tokens_heute,
        "aufrufe": len(data.get("eintraege") or []),
    }


def _fetch_venice() -> dict | None:
    if "venice.ai" not in config.LLM_BASE_URL or not config.LLM_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    base = config.LLM_BASE_URL.rstrip("/")
    result: dict = {"anbieter": "Venice AI"}
    try:
        bal = requests.get(f"{base}/billing/balance", headers=headers, timeout=15)
        if bal.status_code == 200:
            result["balance"] = bal.json()
        elif bal.status_code in (401, 403):
            result["balance_hinweis"] = (
                "Guthaben braucht oft einen Admin-API-Key. Verbrauch (unten) funktioniert meist trotzdem."
            )
        else:
            result["balance_fehler"] = f"HTTP {bal.status_code}"
    except requests.RequestException as e:
        result["balance_fehler"] = str(e)[:120]
    try:
        usage = requests.get(f"{base}/billing/usage-analytics", params={"lookback": "30d"},
                             headers=headers, timeout=20)
        if usage.status_code == 200:
            result["usage"] = usage.json()
        elif usage.status_code not in (401, 403):
            result["usage_fehler"] = f"HTTP {usage.status_code}"
    except requests.RequestException as e:
        result["usage_fehler"] = str(e)[:120]
    return result


def provider_summary(force: bool = False) -> dict | None:
    """Gecachte Anbieter-Daten (Venice-Guthaben/Verbrauch)."""
    if CACHE_PATH.exists() and not force:
        age = datetime.now().timestamp() - CACHE_PATH.stat().st_mtime
        if age < CACHE_SECONDS:
            try:
                return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    data = None
    if "venice.ai" in config.LLM_BASE_URL:
        data = _fetch_venice()
    elif "openai.com" in config.LLM_BASE_URL:
        data = {
            "anbieter": "OpenAI",
            "hinweis": ("OpenAI zeigt das Restguthaben nicht über die normale API. "
                        "Oben siehst du die geschätzten Kosten dieses Tools. "
                        "Restguthaben: platform.openai.com → Billing."),
        }
    else:
        data = {"anbieter": "API", "hinweis": "Geschätzte Kosten dieses Tools (lokal erfasst)."}
    if data is not None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        data["abgerufen"] = datetime.now().isoformat(timespec="seconds")
        CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def dashboard() -> dict:
    """Alles für die Anzeige oben in der App."""
    local = local_summary()
    provider = provider_summary() or {}
    remaining = None
    spent_30d = None
    currency = "USD"

    bal = provider.get("balance") or {}
    balances = bal.get("balances") or {}
    if balances:
        # bevorzugte Anzeige: USD, sonst DIEM/Credits
        if balances.get("usd") is not None:
            remaining = float(balances["usd"])
            currency = "USD"
        elif balances.get("diem") is not None:
            remaining = float(balances["diem"])
            currency = "DIEM"
        elif balances.get("bundledCredits") is not None:
            remaining = float(balances["bundledCredits"])
            currency = "Credits"
        elif balances.get("earnedCredits") is not None:
            remaining = float(balances["earnedCredits"])
            currency = "Credits"

    usage = provider.get("usage") or {}
    if by_date := usage.get("byDate"):
        spent_30d = round(sum(float(d.get("USD") or 0) for d in by_date), 4)

    return {
        "local": local,
        "provider": provider,
        "remaining": remaining,
        "currency": currency,
        "spent_30d": spent_30d,
        "can_consume": bal.get("canConsume"),
    }


def format_money(amount: float | None, currency: str = "USD") -> str:
    if amount is None:
        return "–"
    if currency == "USD":
        if amount == 0:
            return "$0.00"
        if abs(amount) < 0.01:
            return f"${amount:.4f}"
        return f"${amount:.2f}"
    return f"{amount:.2f} {currency}"
