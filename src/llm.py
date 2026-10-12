import base64
import json
import re

import json_repair
from openai import OpenAI

from src import config
from src.models import current_model, current_vision_model

_client: OpenAI | None = None


def reset_client() -> None:
    """Nach Änderung von API-Key oder Basis-URL den Client neu aufbauen."""
    global _client
    _client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


JSON_RULES = (
    "\n\nAntworte ausschliesslich mit gültigem JSON, ohne Markdown und ohne weiteren Text. "
    "Verwende innerhalb von Texten keine doppelten Anführungszeichen (\"), sondern «...» oder einfache ('...')."
)
MAX_JSON_TOKENS = 16000


def _complete(system: str, user_content, temperature: float, max_tokens: int | None, model: str) -> tuple[str, str]:
    extra_body = None
    if "venice.ai" in config.LLM_BASE_URL:
        extra_body = {"venice_parameters": {"include_venice_system_prompt": False}}
    try:
        resp = _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
    except Exception as e:
        raise RuntimeError(config.friendly_api_error(e)) from e
    choice = resp.choices[0]
    text = re.sub(r"<think>.*?</think>", "", choice.message.content or "", flags=re.S).strip()
    if text.lstrip().lower().startswith("<!doctype") or text.lstrip().lower().startswith("<html"):
        raise RuntimeError(config.friendly_api_error(ValueError(text[:500])))
    return text, choice.finish_reason or ""


def chat(system: str, user: str, temperature: float = 0.4, max_tokens: int | None = None) -> str:
    return _complete(system, user, temperature, max_tokens, current_model())[0]


def chat_messages(system: str, messages: list[dict], temperature: float = 0.6, max_tokens: int = 1500) -> str:
    """Mehrstufiges Gespräch: messages = [{"role": "user"|"assistant", "content": "..."}]."""
    extra_body = None
    if "venice.ai" in config.LLM_BASE_URL:
        extra_body = {"venice_parameters": {"include_venice_system_prompt": False}}
    resp = _get_client().chat.completions.create(
        model=current_model(),
        messages=[{"role": "system", "content": system}, *messages],
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
    return re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S).strip()


def chat_json(system: str, user: str, temperature: float = 0.3, max_tokens: int | None = None) -> dict:
    """Fragt JSON an. Abgeschnittene oder fehlerhafte Antworten werden repariert bzw. einmal neu angefragt."""
    system += JSON_RULES
    tokens = max_tokens or 8000
    last_error: Exception | None = None
    for attempt in range(2):
        text, finish = _complete(system, user, temperature, tokens, current_model())
        if finish == "length":
            tokens = min(tokens * 2, MAX_JSON_TOKENS)
            last_error = ValueError("Die KI-Antwort war zu lang und wurde abgeschnitten.")
            continue
        try:
            return extract_json(text)
        except ValueError as e:
            last_error = e
            user += "\n\nWICHTIG: Deine letzte Antwort war kein gültiges JSON. Achte genau auf das Format."
    raise ValueError(f"Die KI hat kein gültiges Ergebnis geliefert. Bitte nochmals versuchen. ({last_error})")


def chat_images(system: str, text: str, images: list[bytes], mime: str = "image/png") -> str:
    content = [{"type": "text", "text": text}] + [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(img).decode()}"}}
        for img in images
    ]
    return _complete(system, content, 0.0, 8000, current_vision_model())[0]


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    candidate = match.group(0) if match else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = json_repair.loads(candidate)
    if isinstance(repaired, dict) and repaired:
        return repaired
    raise ValueError(f"KI-Antwort enthielt kein gültiges JSON: {text[:300]}")
