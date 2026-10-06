import base64
import io
import json
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageOps

from src.config import DATA_DIR, LLM_API_KEY, LLM_BASE_URL
from src.generate import L
from src.llm import chat, chat_images, extract_json

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
    "Frisur: ordentlich gestylt": (
        "Neatly style the person's hair: tidy, well-groomed and professional, flyaway strands removed. "
        "Keep the same hair colour and roughly the same length."
    ),
    "Gesicht: dezent retuschieren": (
        "Apply subtle professional portrait retouching: make the face look slightly slimmer and more defined "
        "(jawline and cheeks), even out the skin tone and reduce blemishes, while keeping the natural skin texture."
    ),
}

# Diese Merkmale lassen sich gezielt per Voreinstellung oder eigenem Wunsch verändern
EDITABLE_PRESETS = {"Frisur: ordentlich gestylt", "Gesicht: dezent retuschieren"}

STRICT_IDENTITY = (
    " Keep the person's face, facial features, expression, skin texture, hairstyle, age and identity exactly "
    "the same. Photorealistic result, no beautification filters, no change to body shape, no text or watermark."
)
FLEXIBLE_IDENTITY = (
    " Make the requested changes clearly visible, but keep them natural and realistic. Apart from the requested "
    "changes, the person must remain clearly recognisable: same identity, eye colour, age and expression. "
    "Photorealistic result, no text or watermark."
)

TRANSLATE_SYSTEM = (
    "Übersetze den Bearbeitungswunsch für ein Foto in eine klare, kurze englische Anweisung für ein "
    "Bildbearbeitungsmodell. Gib nur die Anweisung zurück, ohne Anführungszeichen und ohne Kommentar."
)

REVIEW_SYSTEM = f"""Du bist Fotografin und Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Bewerte dieses Foto als Bewerbungsfoto für einen Lebenslauf: Ausschnitt, Licht, Schärfe, Hintergrund,
Kleidung, Ausdruck und Gesamtwirkung. Sei ehrlich, freundlich und konkret.
Antworte ausschliesslich mit JSON:
{{"note": <1-10>, "fazit": "<1-2 Sätze>", "positiv": ["..."], "verbesserungen": ["..."],
  "empfohlene_bearbeitungen": ["<passende Einträge aus: {', '.join(PRESETS)}>"]}}"""


COMPARE_SYSTEM = f"""Du bist Fotografin und Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Du siehst zwei Versionen eines Bewerbungsfotos: Bild A (erstes Bild) und Bild B (zweites Bild),
meist das Original und eine KI-Bearbeitung. Vergleiche sie ehrlich und konkret.
Prüfe besonders:
- Ist auf B eindeutig noch dieselbe Person wie auf A zu erkennen? Ein Bewerbungsfoto muss der Person ähnlich sehen.
- Wirkt B natürlich, oder gibt es KI-Fehler (verformte Augen, Ohren, Zähne, Hände, Haare, Brille, Kleidung,
  unnatürlich glatte Haut, seltsamer Hintergrund)?
- Was ist auf B besser und was schlechter als auf A (Licht, Hintergrund, Kleidung, Ausschnitt, Ausdruck)?
Antworte ausschliesslich mit JSON:
{{"note_a": <1-10>, "note_b": <1-10>,
  "aehnlichkeit": <1-10, wie klar B dieselbe Person wie A zeigt>, "aehnlichkeit_fazit": "<1 Satz>",
  "besser": ["<was auf B besser ist>"], "schlechter": ["<was auf B schlechter ist>"],
  "ki_fehler": ["<sichtbare Fehler oder unnatürliche Stellen auf B – sonst leer>"],
  "empfehlung": "<A oder B>", "begruendung": "<1-2 Sätze>",
  "naechste_schritte": ["<konkreter Bearbeitungswunsch für eine noch bessere Version>"]}}"""


def version_label(path: Path) -> str:
    kind = "Original" if "original" in path.name else "Bearbeitet"
    try:
        when = datetime.strptime(path.name[:15], "%Y%m%d-%H%M%S").strftime("%d.%m. %H:%M")
    except ValueError:
        when = ""
    return f"{kind} {when}".strip()


def compare(a: Path, b: Path) -> dict:
    text = "Bild A ist das erste Bild, Bild B das zweite. Vergleiche die beiden Bewerbungsfotos."
    result = extract_json(chat_images(COMPARE_SYSTEM, text, [_preview_bytes(a), _preview_bytes(b)],
                                     mime="image/jpeg"))
    for key in ("note_a", "note_b", "aehnlichkeit"):
        try:
            result[key] = max(1, min(10, round(float(result.get(key, 0)))))
        except (TypeError, ValueError):
            result[key] = 0
    result["empfehlung"] = "B" if str(result.get("empfehlung", "")).strip().upper().startswith("B") else "A"
    return result


def blend(a: Path, b: Path, amount: float) -> Image.Image:
    """Überblendet A und B (0 = nur A, 1 = nur B); B wird auf die Grösse von A gebracht."""
    img_a = Image.open(a).convert("RGB")
    img_b = ImageOps.fit(Image.open(b).convert("RGB"), img_a.size)
    return Image.blend(img_a, img_b, amount)


def _preview_bytes(path: Path, side: int = 1024) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


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
    _meta_path(path).unlink(missing_ok=True)


FACE_LOCK = (
    " The face is locked: do not alter face shape, jawline, cheeks, nose, eyes, mouth, teeth, smile, skin "
    "texture, wrinkles, freckles, hairline or hairstyle in any way. Only lighting, background, clothing and "
    "framing may change."
)
MIN_SIMILARITY = 7


def build_prompt(presets: list[str], custom: str, face_lock: bool = False) -> str:
    """Eigene Wünsche stehen zuerst und haben Vorrang. Mit face_lock bleibt das Gesicht strikt unverändert,
    Gesichts-/Frisur-Voreinstellungen werden dann ignoriert."""
    parts = []
    if custom.strip():
        try:
            wish = chat(TRANSLATE_SYSTEM, custom.strip(), temperature=0.0, max_tokens=300)
        except Exception:
            wish = custom.strip()
        parts.append(f"Most important requested change: {wish.rstrip('. ')}.")
    if face_lock:
        presets = [p for p in presets if p not in EDITABLE_PRESETS]
    parts += [PRESETS[p] for p in presets if p in PRESETS]
    if face_lock:
        return " ".join(parts) + STRICT_IDENTITY + FACE_LOCK
    flexible = bool(custom.strip()) or any(p in EDITABLE_PRESETS for p in presets)
    return " ".join(parts) + (FLEXIBLE_IDENTITY if flexible else STRICT_IDENTITY)


def _meta_path(version: Path) -> Path:
    return version.with_suffix(".json")


def load_meta(version: Path) -> dict:
    path = _meta_path(version)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_meta(version: Path, **values) -> None:
    _meta_path(version).write_text(json.dumps({**load_meta(version), **values}, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def find_original(version: Path) -> Path | None:
    """Das Original, aus dem eine Version (über mehrere Bearbeitungen) entstanden ist."""
    seen = set()
    while version and version.exists() and "original" not in version.name and version not in seen:
        seen.add(version)
        source = load_meta(version).get("quelle")
        version = VERSIONS_DIR / source if source else None
    if version and version.exists():
        return version
    originals = [v for v in list_versions() if "original" in v.name]
    return originals[0] if originals else None


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
    save_meta(path, quelle=source.name, prompt=prompt, modell=model)
    return path


def check_similarity(version: Path) -> dict | None:
    """Vergleicht eine bearbeitete Version mit ihrem Original und speichert das Ergebnis."""
    original = find_original(version)
    if not original or original == version:
        return None
    result = compare(original, version)
    save_meta(version, aehnlichkeit=result["aehnlichkeit"], aehnlichkeit_fazit=result.get("aehnlichkeit_fazit", ""),
              verglichen_mit=original.name)
    return result


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
