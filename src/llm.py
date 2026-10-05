import json
import re

from openai import OpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def chat(system: str, user: str, temperature: float = 0.4) -> str:
    extra_body = None
    if "venice.ai" in LLM_BASE_URL:
        extra_body = {"venice_parameters": {"include_venice_system_prompt": False}}
    resp = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        extra_body=extra_body,
    )
    text = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def chat_json(system: str, user: str, temperature: float = 0.3) -> dict:
    system += "\n\nAntworte ausschließlich mit gültigem JSON, ohne Markdown und ohne weiteren Text."
    return extract_json(chat(system, user, temperature))


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"KI-Antwort enthielt kein JSON:\n{text[:500]}")
        return json.loads(match.group(0))
