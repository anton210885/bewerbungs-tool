import json
import re
import shutil
from datetime import date
from pathlib import Path

import typst

from src.config import COUNTRY, DATA_DIR, TEMPLATES_DIR
from src.llm import chat_json

LOCALES = {
    "ch": {
        "markt": "Schweizer",
        "stil": (
            "Schreibe in Schweizer Hochdeutsch: verwende niemals «ß», sondern immer «ss». "
            "Beträge in CHF. Halte dich an Schweizer Bewerbungskonventionen."
        ),
        "gruss": "Freundliche Grüsse",
        "anlagen": "Beilagen: Lebenslauf, Arbeitszeugnisse, Diplome",
        "region": "CH",
    },
    "de": {
        "markt": "deutschen",
        "stil": "Schreibe in deutschem Hochdeutsch.",
        "gruss": "Mit freundlichen Grüßen",
        "anlagen": "Anlagen: Lebenslauf, Zeugnisse",
        "region": "DE",
    },
}
L = LOCALES.get(COUNTRY, LOCALES["ch"])

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

ANALYZE_SYSTEM = f"""Du bist eine erfahrene Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Vergleiche das Bewerberprofil ehrlich und präzise mit der Stellenanzeige.
Berücksichtige auch formale Kriterien wie Arbeitsbewilligung, Sprachkenntnisse und Pensum."""

ANALYZE_SYSTEM += """
Gib folgendes JSON zurück:
{
  "score": <0-100, wie gut das Profil passt>,
  "zusammenfassung": "<2-3 Sätze>",
  "staerken": ["<konkrete Übereinstimmung>", ...],
  "luecken": ["<geforderte Punkte, die im Profil fehlen>", ...],
  "keywords": ["<wichtige Begriffe aus der Anzeige für ATS-Systeme>", ...],
  "empfehlung": "<worauf die Bewerbung den Fokus legen sollte>"
}"""

CV_SYSTEM = f"""Du bist Expertin für Lebensläufe auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
"""

CV_SYSTEM += """Passe den Lebenslauf an die Stellenanzeige an. Strenge Regeln:
- Verwende AUSSCHLIESSLICH Fakten aus dem Profil. Erfinde nichts: keine Tätigkeiten, Zahlen, Tools oder Erfolge.
- Du darfst umformulieren, kürzen, priorisieren und Begriffe aus der Anzeige verwenden, wenn sie durch das Profil belegt sind.
- Pro Position höchstens 5 Stichpunkte, die relevantesten zuerst, aktiv und prägnant formuliert.
- Alle Positionen bleiben enthalten (keine Lücken im Lebenslauf).
- Skills: nur Einträge aus dem Profil, wörtlich übernommen, relevanteste zuerst; irrelevante darfst du weglassen.
Gib folgendes JSON zurück:
{
  "kurzprofil": "<3-4 Sätze, zugeschnitten auf die Stelle>",
  "berufserfahrung": [{"index": <index aus Profil>, "punkte": ["...", ...]}, ...],
  "projekte": [{"index": <index aus Profil>, "punkte": ["...", ...]}, ...],
  "skills_fachlich": ["...", ...],
  "skills_software": ["...", ...]
}
Bei "projekte" nur die für die Stelle relevanten Projekte aufnehmen."""

LETTER_SYSTEM = f"""Du schreibst überzeugende Bewerbungsschreiben für den {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Grussformel: "{L["gruss"]}".
"""

LETTER_SYSTEM += """Regeln:
- Verwende AUSSCHLIESSLICH Fakten aus dem Profil. Erfinde nichts.
- Maximal eine Seite: 3-4 Absätze, insgesamt 250-350 Wörter.
- Kein Floskel-Einstieg wie "hiermit bewerbe ich mich". Steige mit einem konkreten Bezug zur Stelle oder Firma ein.
- Belege die wichtigsten Anforderungen der Anzeige mit konkreten Erfahrungen aus dem Profil.
- Schluss mit Verfügbarkeit/Gehaltsvorstellung nur, wenn im Profil oder in den Hinweisen angegeben, und Wunsch nach persönlichem Gespräch.
- Ist in der Anzeige eine Ansprechperson genannt, sprich sie direkt an, sonst "Sehr geehrte Damen und Herren,".
Gib folgendes JSON zurück:
{
  "betreff": "Bewerbung als ...",
  "anrede": "Sehr geehrte ...,",
  "absaetze": ["...", "...", "..."],
  "gruss": "<Grussformel>"
}"""


def _s(value) -> str:
    return "" if value is None else str(value).strip()


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def _profile_for_llm(profile: dict) -> dict:
    return {
        "kurzprofil": profile.get("kurzprofil", ""),
        "berufserfahrung": [{"index": i, **e} for i, e in enumerate(profile.get("berufserfahrung") or [])],
        "ausbildung": profile.get("ausbildung") or [],
        "skills": profile.get("skills") or {},
        "sprachen": profile.get("sprachen") or [],
        "zertifikate": profile.get("zertifikate") or [],
        "projekte": [{"index": i, **p} for i, p in enumerate(profile.get("projekte") or [])],
        "weitere_infos": profile.get("weitere_infos", ""),
    }


def analyze_match(profile: dict, job_text: str) -> dict:
    user = f"PROFIL:\n{_dump(_profile_for_llm(profile))}\n\nSTELLENANZEIGE:\n{job_text}"
    result = chat_json(ANALYZE_SYSTEM, user)
    try:
        result["score"] = max(0, min(100, int(result.get("score", 0))))
    except (TypeError, ValueError):
        result["score"] = 0
    return result


def tailor_cv(profile: dict, job_text: str, analysis: dict | None, hinweise: str = "") -> dict:
    user = (
        f"PROFIL:\n{_dump(_profile_for_llm(profile))}\n\n"
        f"STELLENANZEIGE:\n{job_text}\n\n"
        f"ANALYSE:\n{_dump(analysis or {})}\n\n"
        f"ZUSÄTZLICHE HINWEISE:\n{hinweise or '-'}"
    )
    result = _localize(chat_json(CV_SYSTEM, user))
    return _merge_cv(profile, result)


def _localize(obj):
    """Schweizer Rechtschreibung erzwingen, falls das Modell trotzdem «ß» schreibt."""
    if COUNTRY != "ch":
        return obj
    if isinstance(obj, str):
        return obj.replace("ß", "ss")
    if isinstance(obj, list):
        return [_localize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _localize(v) for k, v in obj.items()}
    return obj


def _merge_cv(profile: dict, result: dict) -> dict:
    """Fakten (Firmen, Daten, Abschlüsse) kommen immer aus dem Profil, nur Texte aus der KI."""
    p = profile.get("persoenlich") or {}
    skills = profile.get("skills") or {}

    def bullets_by_index(key):
        return {e.get("index"): e.get("punkte") or [] for e in result.get(key) or [] if isinstance(e, dict)}

    exp_bullets = bullets_by_index("berufserfahrung")
    berufserfahrung = []
    for i, e in enumerate(profile.get("berufserfahrung") or []):
        punkte = exp_bullets.get(i) or [*(e.get("aufgaben") or []), *(e.get("erfolge") or [])][:5]
        berufserfahrung.append(_entry(e, _s(e.get("position")), [e.get("firma"), e.get("ort")], punkte))

    ausbildung = [
        _entry(e, _s(e.get("abschluss")), [e.get("institution"), e.get("ort")], e.get("details") or [])
        for e in profile.get("ausbildung") or []
    ]

    projekte_src = profile.get("projekte") or []
    proj_bullets = bullets_by_index("projekte")
    projekte = []
    for i, punkte in proj_bullets.items():
        if isinstance(i, int) and 0 <= i < len(projekte_src):
            pr = projekte_src[i]
            projekte.append(_entry(pr, _s(pr.get("name")), [", ".join(pr.get("technologien") or [])], punkte))

    kenntnisse = []
    for label, key in [("Fachlich", "fachlich"), ("Software", "software")]:
        selected = _filter_known(result.get(f"skills_{key}"), skills.get(key) or [])
        if selected:
            kenntnisse.append({"label": label, "text": ", ".join(selected)})
    sprachen = [
        f"{_s(x.get('sprache'))} ({_s(x.get('niveau'))})" if isinstance(x, dict) else _s(x)
        for x in profile.get("sprachen") or []
    ]
    if sprachen:
        kenntnisse.append({"label": "Sprachen", "text": ", ".join(sprachen)})
    zertifikate = [
        " ".join(filter(None, [_s(z.get("name")), f"({_s(z.get('jahr'))})" if z.get("jahr") else ""]))
        if isinstance(z, dict) else _s(z)
        for z in profile.get("zertifikate") or []
    ]
    if zertifikate:
        kenntnisse.append({"label": "Zertifikate", "text": ", ".join(zertifikate)})
    if profile.get("interessen"):
        kenntnisse.append({"label": "Interessen", "text": ", ".join(map(_s, profile["interessen"]))})

    angaben = [
        {"label": label, "text": _s(p.get(key))}
        for label, key in [
            ("Geburtsdatum", "geburtsdatum"),
            ("Nationalität", "nationalitaet"),
            ("Bewilligung", "bewilligung"),
            ("Zivilstand", "zivilstand"),
            ("Führerausweis", "fuehrerausweis"),
        ]
        if _s(p.get(key))
    ]

    referenzen_src = profile.get("referenzen")
    if isinstance(referenzen_src, str):
        referenzen = [referenzen_src.strip()] if referenzen_src.strip() else []
    else:
        referenzen = [
            ", ".join(filter(None, [_s(r.get("name")), _s(r.get("funktion")), _s(r.get("firma")),
                                    _s(r.get("telefon")), _s(r.get("email"))]))
            for r in referenzen_src or [] if isinstance(r, dict)
        ]

    return {
        "region": L["region"],
        "persoenlich": {"name": _s(p.get("name")), "titel": _s(p.get("titel"))},
        "kontaktzeile": _kontaktzeile(p),
        "foto": _s(p.get("foto")),
        "angaben": angaben,
        "kurzprofil": _s(result.get("kurzprofil")) or _s(profile.get("kurzprofil")),
        "berufserfahrung": berufserfahrung,
        "ausbildung": ausbildung,
        "projekte": projekte,
        "kenntnisse": kenntnisse,
        "referenzen": referenzen,
    }


def _entry(src: dict, titel: str, unter: list, punkte: list) -> dict:
    von, bis = _s(src.get("von")), _s(src.get("bis"))
    if von and bis:
        zeitraum = f"{von} – {bis}"
    elif von:
        zeitraum = f"seit {von}"
    else:
        zeitraum = bis
    return {
        "zeitraum": zeitraum,
        "titel": titel,
        "untertitel": ", ".join(filter(None, map(_s, unter))),
        "punkte": [_s(x) for x in punkte if _s(x)],
    }


def _filter_known(selected, allowed: list) -> list[str]:
    allowed_map = {_s(a).lower(): _s(a) for a in allowed}
    result = [allowed_map[_s(x).lower()] for x in selected or [] if _s(x).lower() in allowed_map]
    return list(dict.fromkeys(result)) or list(allowed_map.values())


def _kontaktzeile(p: dict) -> str:
    ort = " ".join(filter(None, [_s(p.get("plz")), _s(p.get("ort"))]))
    teile = [_s(p.get("strasse")), ort, _s(p.get("telefon")), _s(p.get("email")), _s(p.get("linkedin"))]
    return "  ·  ".join(t for t in teile if t)


def write_letter(profile: dict, app: dict, analysis: dict | None, hinweise: str = "") -> dict:
    user = (
        f"BEWERBER: {_s((profile.get('persoenlich') or {}).get('name'))}\n\n"
        f"PROFIL:\n{_dump(_profile_for_llm(profile))}\n\n"
        f"STELLE: {app.get('title')} bei {app.get('company')} ({app.get('location')})\n\n"
        f"STELLENANZEIGE:\n{app.get('description')}\n\n"
        f"ANALYSE:\n{_dump(analysis or {})}\n\n"
        f"ZUSÄTZLICHE HINWEISE:\n{hinweise or '-'}"
    )
    result = _localize(chat_json(LETTER_SYSTEM, user, temperature=0.6))
    return {
        "betreff": _s(result.get("betreff")) or f"Bewerbung als {app.get('title')}",
        "anrede": _s(result.get("anrede")) or "Sehr geehrte Damen und Herren,",
        "absaetze": [_s(a) for a in result.get("absaetze") or [] if _s(a)],
        "gruss": _s(result.get("gruss")) or L["gruss"],
    }


def build_letter_data(profile: dict, letter: dict, empfaenger: list[str]) -> dict:
    p = profile.get("persoenlich") or {}
    heute = date.today()
    datum = f"{heute.day}. {MONATE[heute.month - 1]} {heute.year}"
    return {
        **letter,
        "region": L["region"],
        "absender": {"name": _s(p.get("name"))},
        "kontaktzeile": _kontaktzeile(p),
        "empfaenger": [z for z in empfaenger if z.strip()],
        "ort_datum": f"{_s(p.get('ort'))}, {datum}".lstrip(", "),
        "anlagen": L["anlagen"],
    }


def render_cv(data: dict, out_dir: Path, filename: str) -> Path:
    data = dict(data)
    if data.get("foto"):
        src = Path(data["foto"])
        src = src if src.is_absolute() else DATA_DIR / src
        if src.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            target = f"foto{src.suffix.lower()}"
            shutil.copy(src, out_dir / target)
            data["foto"] = target
        else:
            data["foto"] = ""
    return _render("cv.typ", "cv.json", data, out_dir, filename)


def render_letter(data: dict, out_dir: Path, filename: str) -> Path:
    return _render("letter.typ", "letter.json", data, out_dir, filename)


def _render(template: str, data_name: str, data: dict, out_dir: Path, filename: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATES_DIR / template, out_dir / template)
    (out_dir / data_name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pdf_path = out_dir / filename
    typst.compile(str(out_dir / template), output=str(pdf_path))
    return pdf_path


def safe_filename(*parts: str) -> str:
    name = "_".join(p for p in parts if p)
    return re.sub(r"[^\w\-äöüÄÖÜß]+", "_", name).strip("_")[:120]
