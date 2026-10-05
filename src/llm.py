import base64
import json
import re

from openai import OpenAI

from src.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_VISION_MODEL

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def _complete(system: str, user_content, temperature: float, max_tokens: int | None, model: str) -> str:
    extra_body = None
    if "venice.ai" in LLM_BASE_URL:
        extra_body = {"venice_parameters": {"include_venice_system_prompt": False}}
    resp = _get_client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )
    text = resp.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def chat(system: str, user: str, temperature: float = 0.4, max_tokens: int | None = None) -> str:
    return _complete(system, user, temperature, max_tokens, LLM_MODEL)


def chat_json(system: str, user: str, temperature: float = 0.3, max_tokens: int | None = None) -> dict:
    system += "\n\nAntworte ausschliesslich mit gültigem JSON, ohne Markdown und ohne weiteren Text."
    return extract_json(chat(system, user, temperature, max_tokens))


def chat_images(system: str, text: str, images: list[bytes], mime: str = "image/png") -> str:
    content = [{"type": "text", "text": text}] + [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(img).decode()}"}}
        for img in images
    ]
    return _complete(system, content, 0.0, 8000, LLM_VISION_MODEL)


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"KI-Antwort enthielt kein JSON:\n{text[:500]}")
        return json.loads(match.group(0))
