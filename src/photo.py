import base64
import io
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageOps

from src.config import DATA_DIR, LLM_API_KEY, LLM_BASE_URL
from src.generate import L
from src.llm import chat_images, extract_json

PHOTO_DIR = DATA_DIR / "foto"
VERSIONS_DIR = PHOTO_DIR / "versionen"
FINAL_PATH = PHOTO_DIR / "bewerbungsfoto.png"
FINAL_REL = "foto/bewerbungsfoto.png"
MAX_SIDE = 2048

MODELS = {
    "nano-banana-pro-edit": "Nano Banana Pro – beste Qualität (ca. $0.18, Anonymized)",
    "gpt-image-2-5-flare-edit": "GPT Image 2.5 Flare – sehr gut, günstiger (ca. $0.08, Anonymized)",
    "grok-imagine-quality-edit": "Grok Imagine HQ – privat (ca. $0.06, Private)",
    "firered-image-edit": "FireRed – günstig und privat (ca. $0.04, Private)",
}

PRESETS = {
    "Professionell aufwerten": (
        "Turn this into a professional, high-quality job application headshot: soft even studio lighting, "
        "natural skin tones, sharp focus on the eyes, head-and-shoulders framing, neutral light grey background."
    ),
    "Licht & Farben verbessern": (
        "Improve lighting, exposure, white balance and colours so it looks like a professional photo. "
        "Reduce harsh shadows. Keep everything else unchanged."
    ),
    "Hintergrund: neutral hellgrau": "Replace the background with a smooth neutral light grey studio backdrop with a soft gradient.",
    "Hintergrund: weiss": "Replace the background with a clean, evenly lit white studio background.",
    "Hintergrund: Büro unscharf": "Replace the background with a softly blurred, bright, modern office (shallow depth of field).",
    "Kleidung: dunkler Blazer": "Dress the person in a well-fitting dark navy blazer over a plain white shirt or blouse.",
    "Kleidung: Hemd / Bluse": "Dress the person in a plain, neatly ironed light blue collared shirt or blouse.",
    "Ausschnitt: Brustbild hochformat": "Reframe as a centred portrait-format head-and-shoulders shot with a little space above the head.",
}

IDENTITY_RULES = (
    " Keep the person's face, facial features, expression, skin texture, hairstyle, age and identity exactly "
    "the same. Photorealistic result, no beautification filters, no change to body shape, no text or watermark."
)

REVIEW_SYSTEM = f"""Du bist Fotografin und Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Bewerte dieses Foto als Bewerbungsfoto für einen Lebenslauf: Ausschnitt, Licht, Schärfe, Hintergrund,
Kleidung, Ausdruck und Gesamtwirkung. Sei ehrlich, freundlich und konkret.
Antworte ausschliesslich mit JSON:
{{"note": <1-10>, "fazit": "<1-2 Sätze>", "positiv": ["..."], "verbesserungen": ["..."],
  "empfohlene_bearbeitungen": ["<passende Einträge aus: {', '.join(PRESETS)}>"]}}"""


def _normalize(data: bytes) -> bytes:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _new_version_path(label: str) -> Path:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return VERSIONS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_{label}.png"


def save_original(data: bytes) -> Path:
    path = _new_version_path("original")
    path.write_bytes(_normalize(data))
    return path


def list_versions() -> list[Path]:
    if not VERSIONS_DIR.exists():
        return []
    return sorted(VERSIONS_DIR.glob("*.png"), reverse=True)


def delete_version(path: Path) -> None:
    path.unlink(missing_ok=True)


def build_prompt(presets: list[str], custom: str) -> str:
    parts = [PRESETS[p] for p in presets if p in PRESETS]
    if custom.strip():
        parts.append(custom.strip())
    return " ".join(parts) + IDENTITY_RULES


def edit(source: Path, prompt: str, model: str) -> Path:
    body = {
        "model": model,
        "image": base64.b64encode(source.read_bytes()).decode(),
        "prompt": prompt,
        "aspect_ratio": "3:4",
        "output_format": "png",
    }
    resp = _post_edit(body)
    if resp.status_code == 400:
        body.pop("aspect_ratio")
        resp = _post_edit(body)
    if resp.status_code != 200:
        raise RuntimeError(f"Venice-Fehler {resp.status_code}: {resp.text[:300]}")
    if resp.headers.get("x-venice-is-content-violation") == "true":
        raise RuntimeError("Das Bild wurde vom Inhaltsfilter blockiert. Bitte anderen Wunsch formulieren.")
    path = _new_version_path("bearbeitet")
    path.write_bytes(_normalize(resp.content))
    return path


def _post_edit(body: dict) -> requests.Response:
    return requests.post(
        f"{LLM_BASE_URL}/image/edit",
        headers={"Authorization": f"Bearer {LLM_API_KEY}"},
        json=body,
        timeout=240,
    )


def review(path: Path) -> dict:
    result = extract_json(chat_images(REVIEW_SYSTEM, "Bewerte dieses Bewerbungsfoto.", [path.read_bytes()]))
    try:
        result["note"] = max(1, min(10, round(float(result.get("note", 0)))))
    except (TypeError, ValueError):
        result["note"] = 0
    return result


def use_as_application_photo(path: Path) -> None:
    """Speichert die Version im Hochformat 3:4 als Foto für den Lebenslauf."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    target = 3 / 4
    if w / h > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    elif w / h < target:
        new_h = int(w / target)
        top = int((h - new_h) * 0.25)
        img = img.crop((0, top, w, top + new_h))
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    img.save(FINAL_PATH, "PNG")
