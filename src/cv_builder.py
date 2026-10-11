"""Lebenslauf per Checkbox zusammenstellen: Aufgaben und Hobbies wählen, Rest bleibt fix."""
import json

from src.config import DATA_DIR

SELECTION_PATH = DATA_DIR / "cv_auswahl.json"
QUELLE_LABEL = {"lebenslauf": "CV", "zeugnis": "Zeugnis", "beides": "CV+Zeugnis", "": ""}


def aufgabe_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or "").strip()
    return str(item or "").strip()


def aufgabe_quelle(item) -> str:
    if isinstance(item, dict):
        return str(item.get("quelle") or "").strip().lower()
    return ""


def normalize_aufgabe(item) -> dict:
    text = aufgabe_text(item)
    quelle = aufgabe_quelle(item) if isinstance(item, dict) else ""
    if quelle not in ("lebenslauf", "zeugnis", "beides"):
        quelle = ""
    return {"text": text, "quelle": quelle} if text else {}


def stellen_aufgaben(profile: dict) -> list[dict]:
    """Pro Stelle die normalisierten Aufgaben und Erfolge."""
    result = []
    for i, e in enumerate(profile.get("berufserfahrung") or []):
        aufgaben = [a for a in (normalize_aufgabe(x) for x in e.get("aufgaben") or []) if a]
        erfolge = [a for a in (normalize_aufgabe(x) for x in e.get("erfolge") or []) if a]
        result.append({
            "index": i,
            "position": str(e.get("position") or ""),
            "firma": str(e.get("firma") or ""),
            "ort": str(e.get("ort") or ""),
            "von": str(e.get("von") or ""),
            "bis": str(e.get("bis") or ""),
            "aufgaben": aufgaben,
            "erfolge": erfolge,
        })
    return result


def hobbies(profile: dict) -> list[str]:
    return [str(x).strip() for x in (profile.get("interessen") or []) if str(x).strip()]


def default_selection(profile: dict) -> dict:
    """Standard: pro Stelle max. 5 Aufgaben (+ alle Erfolge), alle Hobbies."""
    aufgaben, erfolge = {}, {}
    for s in stellen_aufgaben(profile):
        i = str(s["index"])
        erfolge[i] = list(range(len(s["erfolge"])))
        aufgaben[i] = list(range(min(5, len(s["aufgaben"]))))
    return {
        "aufgaben": aufgaben,
        "erfolge": erfolge,
        "hobbies": list(range(len(hobbies(profile)))),
        "kurzprofil": True,
    }


def load_selection(profile: dict) -> dict:
    base = default_selection(profile)
    if not SELECTION_PATH.exists():
        return base
    try:
        data = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return base
    # ungültige Indizes entfernen
    stellen = {str(s["index"]): s for s in stellen_aufgaben(profile)}
    clean_a, clean_e = {}, {}
    for i, s in stellen.items():
        clean_a[i] = [j for j in data.get("aufgaben", {}).get(i, base["aufgaben"].get(i, []))
                      if isinstance(j, int) and 0 <= j < len(s["aufgaben"])]
        clean_e[i] = [j for j in data.get("erfolge", {}).get(i, base["erfolge"].get(i, []))
                      if isinstance(j, int) and 0 <= j < len(s["erfolge"])]
    n_h = len(hobbies(profile))
    return {
        "aufgaben": clean_a,
        "erfolge": clean_e,
        "hobbies": [j for j in data.get("hobbies", base["hobbies"]) if isinstance(j, int) and 0 <= j < n_h],
        "kurzprofil": bool(data.get("kurzprofil", True)),
    }


def save_selection(selection: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SELECTION_PATH.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")


def build_cv_from_selection(profile: dict, selection: dict | None = None) -> dict:
    """Lebenslauf nur mit den per Checkbox gewählten Aufgaben/Hobbies; Adresse/Ausbildung bleiben fix."""
    from src.generate import _merge_cv

    sel = selection or load_selection(profile)
    experiences = []
    for s in stellen_aufgaben(profile):
        i = str(s["index"])
        punkte = []
        for j in sel.get("erfolge", {}).get(i, []):
            if 0 <= j < len(s["erfolge"]):
                punkte.append(s["erfolge"][j]["text"])
        for j in sel.get("aufgaben", {}).get(i, []):
            if 0 <= j < len(s["aufgaben"]):
                punkte.append(s["aufgaben"][j]["text"])
        experiences.append({"index": s["index"], "punkte": punkte})
    hobby_list = hobbies(profile)
    chosen_hobbies = [hobby_list[j] for j in sel.get("hobbies", []) if 0 <= j < len(hobby_list)]
    slim = json.loads(json.dumps(profile))
    slim["interessen"] = chosen_hobbies
    result = {
        "kurzprofil": (profile.get("kurzprofil") or "") if sel.get("kurzprofil", True) else "",
        "berufserfahrung": experiences,
        "projekte": [
            {"index": i, "punkte": [p["beschreibung"]] if p.get("beschreibung") else []}
            for i, p in enumerate(profile.get("projekte") or [])
            if isinstance(p, dict) and p.get("name")
        ],
        "skills_fachlich": (profile.get("skills") or {}).get("fachlich") or [],
        "skills_software": (profile.get("skills") or {}).get("software") or [],
    }
    return _merge_cv(slim, result)


def selection_from_suggestions(profile: dict, suggestions: dict) -> dict:
    """Übernimmt KI-Vorschläge als Checkbox-Auswahl (bestehende Hobbies behalten)."""
    sel = load_selection(profile)
    stellen = {s["index"]: s for s in stellen_aufgaben(profile)}
    aufgaben = {str(i): [] for i in stellen}
    for block in suggestions.get("vorschlaege") or []:
        idx = block.get("stellen_index")
        if idx not in stellen:
            continue
        texts = {a["text"]: j for j, a in enumerate(stellen[idx]["aufgaben"])}
        chosen = []
        for item in block.get("aufgaben") or []:
            t = str(item.get("text") or "").strip()
            if t in texts:
                chosen.append(texts[t])
        aufgaben[str(idx)] = chosen
    sel["aufgaben"] = aufgaben
    return sel


def normalize_profile_aufgaben(profile: dict) -> dict:
    """Stellt sicher, dass Aufgaben als {text, quelle} gespeichert sind."""
    updated = json.loads(json.dumps(profile))
    for e in updated.get("berufserfahrung") or []:
        e["aufgaben"] = [a for a in (normalize_aufgabe(x) for x in e.get("aufgaben") or []) if a]
        e["erfolge"] = [a for a in (normalize_aufgabe(x) for x in e.get("erfolge") or []) if a]
    return updated
