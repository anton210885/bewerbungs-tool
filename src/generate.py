import copy
import json
import re
import shutil
from datetime import date
from pathlib import Path

import typst
from PIL import Image

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

CV_TEMPLATES = {
    "klassisch": {"name": "Klassisch", "datei": "cv.typ", "farbe": "#1f4e79", "schrift": "Calibri"},
    "seitenleiste": {"name": "Modern mit Seitenleiste", "datei": "cv_seitenleiste.typ", "farbe": "#2d4a5a",
                     "schrift": "Calibri"},
    "minimal": {"name": "Minimalistisch", "datei": "cv_minimal.typ", "farbe": "#222222", "schrift": "Arial"},
    "elegant": {"name": "Elegant", "datei": "cv_elegant.typ", "farbe": "#7a1f2b", "schrift": "Cambria"},
    "kompakt": {"name": "Kompakt", "datei": "cv_kompakt.typ", "farbe": "#0b6e4f", "schrift": "Calibri"},
    "kreativ": {"name": "Kreativ mit Farbband", "datei": "cv_kreativ.typ", "farbe": "#00796b",
                "schrift": "Calibri"},
}
DEFAULT_TEMPLATE = "klassisch"

CV_FONTS = {
    "Wie Vorlage": None,
    "Calibri": ["Calibri", "Carlito", "Arial"],
    "Arial": ["Arial", "Liberation Sans"],
    "Segoe UI": ["Segoe UI", "Arial"],
    "Verdana": ["Verdana", "DejaVu Sans", "Arial"],
    "Cambria": ["Cambria", "Georgia", "Libertinus Serif"],
    "Georgia": ["Georgia", "Cambria", "Libertinus Serif"],
    "Garamond": ["Garamond", "EB Garamond", "Libertinus Serif"],
}
CV_SIZES = {"Klein": 0.92, "Normal": 1.0, "Gross": 1.08}
CV_SECTIONS = {
    "kurzprofil": "Profil / Kurzprofil",
    "angaben": "Persönliche Angaben",
    "ausbildung": "Ausbildung",
    "projekte": "Projekte",
    "kenntnisse": "Kenntnisse & Sprachen",
    "referenzen": "Referenzen",
}
CV_SPACING = {"Eng": 0.55, "Normal": 1.0, "Weit": 1.4}
CV_PHOTO_SIZES = {"Klein": 0.78, "Mittel": 1.0, "Gross": 1.2}
DEFAULT_CV_OPTIONS = {"schrift": "Wie Vorlage", "groesse": "Normal", "foto": True,
                      "abschnitte": list(CV_SECTIONS), "max_punkte": 8, "abstand": "Normal",
                      "fotogroesse": "Mittel", "angaben_im_kopf": False, "max_seiten": 0}


def apply_cv_options(data: dict, options: dict | None) -> dict:
    """Wendet die Gestaltungs-Einstellungen (Schrift, Grösse, Abschnitte, Foto) auf die Lebenslauf-Daten an."""
    opts = {**DEFAULT_CV_OPTIONS, **(options or {})}
    d = copy.deepcopy(data)
    for key in CV_SECTIONS:
        if key not in opts["abschnitte"]:
            d[key] = "" if key == "kurzprofil" else []
    if not opts["foto"]:
        d["foto"] = ""
    for e in d.get("berufserfahrung", []) + d.get("projekte", []):
        e["punkte"] = e["punkte"][: int(opts["max_punkte"])]
    if fonts := CV_FONTS.get(opts["schrift"]):
        d["schrift"] = fonts
    d["groesse"] = CV_SIZES.get(opts["groesse"], 1.0)
    d["abstand"] = CV_SPACING.get(opts["abstand"], 1.0)
    d["fotofaktor"] = CV_PHOTO_SIZES.get(opts["fotogroesse"], 1.0)
    d["angaben_im_kopf"] = bool(opts["angaben_im_kopf"])
    return d


DESIGN_SYSTEM = """Du setzt Gestaltungswünsche für einen Lebenslauf in Einstellungen um.
Du änderst NUR das Design, niemals Inhalte. Verfügbare Einstellungen und erlaubte Werte:
- vorlage: {vorlagen}
- akzent: Farbe als Hex-Code, z.B. «#1f4e79»
- schrift: {schriften}
- groesse (Textgrösse): {groessen}
- abstand (vertikale Abstände zwischen Abschnitten und Einträgen): {abstaende}
- fotogroesse: {fotogroessen}
- foto: true/false (Foto anzeigen)
- angaben_im_kopf: true/false – persönliche Angaben (Geburtsdatum, Nationalität, Zivilstand) direkt neben
  Namen und Foto im Kopfbereich statt als eigener Abschnitt. Das schliesst die Lücke zwischen Kopf und Angaben.
- max_seiten: 0 (keine Begrenzung) oder 1–4. Das Programm verkleinert dann automatisch, bis es passt.
- max_punkte: 1–10 Stichpunkte pro Stelle
- abschnitte: Liste der sichtbaren Abschnitte aus {abschnitte} (Berufserfahrung ist immer sichtbar)

Hinweise: «keine Lücken», «kompakter», «weniger Weissraum» → abstand «Eng», angaben_im_kopf true,
eventuell fotogroesse «Klein». «max 2 Seiten» → max_seiten 2. «luftiger» → abstand «Weit».
Gib nur die Einstellungen zurück, die wirklich geändert werden sollen.

Antwortformat:
{{"vorlage": null oder Schlüssel, "akzent": null oder Hex, "optionen": {{nur geänderte Einstellungen}},
 "erklaerung": ["was du geändert hast, kurz auf Deutsch"],
 "nicht_moeglich": ["Wünsche, die mit diesen Einstellungen nicht umsetzbar sind"]}}"""


def design_from_wish(wish: str, template: str, accent: str, options: dict) -> dict:
    system = DESIGN_SYSTEM.format(
        vorlagen=", ".join(f"«{k}» ({v['name']})" for k, v in CV_TEMPLATES.items()),
        schriften=", ".join(f"«{f}»" for f in CV_FONTS),
        groessen=", ".join(f"«{s}»" for s in CV_SIZES),
        abstaende=", ".join(f"«{s}»" for s in CV_SPACING),
        fotogroessen=", ".join(f"«{s}»" for s in CV_PHOTO_SIZES),
        abschnitte=", ".join(f"«{k}»" for k in CV_SECTIONS),
    )
    user = (f"Aktuelle Vorlage: {template}\nAktuelle Akzentfarbe: {accent}\n"
            f"Aktuelle Einstellungen: {json.dumps(options, ensure_ascii=False)}\n\nWunsch:\n{wish}")
    result = chat_json(system, user, temperature=0.1, max_tokens=1500)

    allowed = {
        "schrift": set(CV_FONTS), "groesse": set(CV_SIZES), "abstand": set(CV_SPACING),
        "fotogroesse": set(CV_PHOTO_SIZES),
    }
    clean: dict = {}
    for key, value in (result.get("optionen") or {}).items():
        if key in allowed and value in allowed[key]:
            clean[key] = value
        elif key in ("foto", "angaben_im_kopf") and isinstance(value, bool):
            clean[key] = value
        elif key == "max_seiten" and isinstance(value, int) and 0 <= value <= 4:
            clean[key] = value
        elif key == "max_punkte" and isinstance(value, int) and 1 <= value <= 10:
            clean[key] = value
        elif key == "abschnitte" and isinstance(value, list):
            clean[key] = [a for a in value if a in CV_SECTIONS]
    vorlage = result.get("vorlage") if result.get("vorlage") in CV_TEMPLATES else None
    akzent = result.get("akzent")
    akzent = akzent if isinstance(akzent, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", akzent) else None
    return {"vorlage": vorlage, "akzent": akzent, "optionen": clean,
            "erklaerung": result.get("erklaerung") or [], "nicht_moeglich": result.get("nicht_moeglich") or []}


def _fit_steps(opts: dict):
    """Schritte, um den Lebenslauf zu kürzen – vom unauffälligsten zum stärksten Eingriff."""
    yield {"abstand": "Eng"}, "Abstände verkleinert"
    yield {"angaben_im_kopf": True}, "Persönliche Angaben in den Kopf verschoben"
    yield {"fotogroesse": "Klein"}, "Foto verkleinert"
    yield {"groesse": "Klein"}, "Schrift verkleinert"
    for n in range(min(int(opts["max_punkte"]), 8) - 1, 1, -1):
        yield {"max_punkte": n}, f"max. {n} Stichpunkte pro Stelle"
    for key in ("referenzen", "projekte"):
        if key in opts["abschnitte"]:
            yield (lambda o, k=key: {"abschnitte": [a for a in o["abschnitte"] if a != k]},
                   f"Abschnitt «{CV_SECTIONS[key]}» ausgeblendet")


def _page_count(pdf: Path) -> int:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return doc.page_count

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

ANALYZE_SYSTEM = f"""Du bist eine erfahrene Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Vergleiche das Bewerberprofil ehrlich und präzise mit der Stellenanzeige.
Berücksichtige auch formale Kriterien wie Arbeitsbewilligung, Sprachkenntnisse und Pensum.
Prüfe ausserdem, ob die Stelle zu den Wünschen des Bewerbers passt (Wunschberuf, Pensum, Lohn, Region,
Verfügbarkeit) und nenne Abweichungen unter "luecken" mit dem Hinweis "Wunsch:"."""

ANALYZE_SYSTEM += """
Gib folgendes JSON zurück:
{
  "titel": "<Stellentitel laut Anzeige>",
  "firma": "<Firmenname laut Anzeige>",
  "ort": "<Arbeitsort laut Anzeige>",
  "score": <0-100, wie gut das Profil passt>,
  "fazit": "<ein Satz: Lohnt sich eine Bewerbung? Klar und direkt.>",
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
- Wenn unter «GEWÄHLTE AUFGABEN» Stichpunkte markiert sind: nimm diese bevorzugt auf (umformuliert erlaubt)
  und fülle nur bei Bedarf mit weiteren Profil-Aufgaben auf.
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

SUGGEST_SYSTEM = f"""Du bist eine erfahrene Recruiterin auf dem {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Du erhältst das Bewerberprofil (mit allen Aufgaben) und eine Stellenanzeige.
Wähle die Aufgaben aus dem Profil, die für DIESE Stelle am besten passen.
Strenge Regeln:
- Nur wörtlich vorhandene Aufgaben aus dem Profil. Erfinde nichts und formuliere nicht um.
- Pro Stelle höchstens die 5 relevantesten Aufgaben; irrelevante Stellen dürfen 0 haben.
- Begründe kurz, warum die Aufgabe zur Anzeige passt.
Gib JSON zurück:
{{"zusammenfassung": "<1-2 Sätze: worauf du beim Zuschneiden achtest>",
  "vorschlaege": [{{"stellen_index": <index>, "stelle": "<Position>", "firma": "<Firma>",
                   "aufgaben": [{{"text": "<wörtlich aus dem Profil>", "warum": "<kurz>",
                                 "passung": <1-10>}}]}}]}}"""

TRANSLATE_SYSTEM = """You translate a Swiss/German CV JSON into clear professional British/American English
for job applications. Rules:
- Translate all human-readable text: summary, job titles, company locations if German words,
  bullet points, skill labels, personal-detail labels, section headings.
- Keep names, company names, dates, phone numbers, emails, LinkedIn URLs and photo paths unchanged.
- Keep the exact same JSON structure and keys. Only change string values that are natural language.
- Use Swiss/German location names as-is (e.g. Zürich, Suhr).
- Job titles: natural English equivalents (e.g. «Sachbearbeiter» → «Clerk» / role-appropriate title).
- Do not invent new content.
Return only the full translated JSON object with the same keys."""

CV_HEADINGS_DE = {
    "angaben": "Persönliche Angaben",
    "profil": "Profil",
    "ueber_mich": "Über mich",
    "berufserfahrung": "Berufserfahrung",
    "ausbildung": "Ausbildung",
    "projekte": "Projekte",
    "kenntnisse": "Kenntnisse",
    "kenntnisse_persoenlich": "Kenntnisse & Persönliches",
    "referenzen": "Referenzen",
    "kontakt": "Kontakt",
    "persoenliches": "Persönliches",
}
CV_HEADINGS_EN = {
    "angaben": "Personal details",
    "profil": "Profile",
    "ueber_mich": "About me",
    "berufserfahrung": "Work experience",
    "ausbildung": "Education",
    "projekte": "Projects",
    "kenntnisse": "Skills",
    "kenntnisse_persoenlich": "Skills & personal",
    "referenzen": "References",
    "kontakt": "Contact",
    "persoenliches": "Personal",
}

LETTER_SYSTEM = f"""Du schreibst überzeugende Bewerbungsschreiben für den {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Grussformel: "{L["gruss"]}".
"""

LETTER_SYSTEM += """Regeln:
- Verwende AUSSCHLIESSLICH Fakten aus dem Profil. Erfinde nichts.
- Maximal eine Seite: 3-4 Absätze, insgesamt 250-350 Wörter.
- Kein Floskel-Einstieg wie "hiermit bewerbe ich mich". Steige mit einem konkreten Bezug zur Stelle oder Firma ein.
- Belege die wichtigsten Anforderungen der Anzeige mit konkreten Erfahrungen aus dem Profil.
- Bewertungen aus Arbeitszeugnissen darfst du sinngemäss aufgreifen (z.B. "wie mir mein Arbeitgeber bestätigt ...").
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
        "bewertungen_aus_arbeitszeugnissen": profile.get("bewertungen") or [],
        "wuensche": profile.get("wuensche") or {},
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


def aufgaben_katalog(profile: dict) -> list[dict]:
    """Flache Liste aller Aufgaben aus dem Profil (mit Stellenbezug)."""
    if katalog := profile.get("aufgaben_katalog"):
        return [x for x in katalog if isinstance(x, dict) and _s(x.get("text"))]
    items = []
    for i, e in enumerate(profile.get("berufserfahrung") or []):
        for n, text in enumerate([*(e.get("erfolge") or []), *(e.get("aufgaben") or [])]):
            if t := _s(text):
                items.append({
                    "id": f"{i}-{n}",
                    "stelle": _s(e.get("position")),
                    "firma": _s(e.get("firma")),
                    "text": t,
                    "stellen_index": i,
                })
    return items


def suggest_aufgaben(profile: dict, job_text: str, analysis: dict | None = None) -> dict:
    """Schlägt die zur Stelle passendsten Aufgaben aus dem Profil vor."""
    user = (
        f"PROFIL:\n{_dump(_profile_for_llm(profile))}\n\n"
        f"STELLENANZEIGE:\n{job_text}\n\n"
        f"ANALYSE:\n{_dump(analysis or {})}"
    )
    return _localize(chat_json(SUGGEST_SYSTEM, user, temperature=0.2, max_tokens=6000))


def tailor_cv(profile: dict, job_text: str, analysis: dict | None, hinweise: str = "",
              gewaehlte_aufgaben: list[dict] | None = None) -> dict:
    user = (
        f"PROFIL:\n{_dump(_profile_for_llm(profile))}\n\n"
        f"STELLENANZEIGE:\n{job_text}\n\n"
        f"ANALYSE:\n{_dump(analysis or {})}\n\n"
        f"GEWÄHLTE AUFGABEN (bevorzugt übernehmen):\n{_dump(gewaehlte_aufgaben or [])}\n\n"
        f"ZUSÄTZLICHE HINWEISE:\n{hinweise or '-'}"
    )
    result = _localize(chat_json(CV_SYSTEM, user))
    return _merge_cv(profile, result)


def translate_cv(cv: dict) -> dict:
    """Übersetzt einen fertigen Lebenslauf (CV-JSON) ins Englische."""
    result = chat_json(TRANSLATE_SYSTEM, _dump(cv), temperature=0.1, max_tokens=10000)
    # Struktur schützen: Foto, Region und Überschriften hart setzen
    result["foto"] = cv.get("foto", "")
    result["region"] = cv.get("region") or L["region"]
    result["ueberschriften"] = {**CV_HEADINGS_EN}
    result["sprache"] = "en"
    # Leere / fehlende Listen nicht verlieren
    for key in ("berufserfahrung", "ausbildung", "projekte", "kenntnisse", "angaben", "referenzen", "kontakt"):
        if key not in result and key in cv:
            result[key] = cv[key]
    return result


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
        punkte = exp_bullets.get(i) or [*(e.get("erfolge") or []), *(e.get("aufgaben") or [])][:6]
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
        "sprache": "de",
        "ueberschriften": dict(CV_HEADINGS_DE),
        "persoenlich": {"name": _s(p.get("name")), "titel": _s(p.get("titel"))},
        "kontaktzeile": _kontaktzeile(p),
        "kontakt": _kontakt_liste(p),
        "foto": _s(p.get("foto")),
        "angaben": angaben,
        "kurzprofil": _s(result.get("kurzprofil")) or _s(profile.get("kurzprofil")),
        "berufserfahrung": berufserfahrung,
        "ausbildung": ausbildung,
        "projekte": projekte,
        "kenntnisse": kenntnisse,
        "referenzen": referenzen,
    }


def base_cv_data(profile: dict) -> dict:
    """Allgemeiner Lebenslauf direkt aus dem Profil, ohne Anpassung an eine Stelle."""
    projekte = [
        {"index": i, "punkte": [p["beschreibung"]] if p.get("beschreibung") else []}
        for i, p in enumerate(profile.get("projekte") or [])
        if isinstance(p, dict) and p.get("name")
    ]
    return _merge_cv(profile, {"projekte": projekte})


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


def _kontakt_liste(p: dict) -> list[str]:
    ort = " ".join(filter(None, [_s(p.get("plz")), _s(p.get("ort"))]))
    teile = [_s(p.get("strasse")), ort, _s(p.get("telefon")), _s(p.get("email")), _s(p.get("linkedin"))]
    return [t for t in teile if t]


def _kontaktzeile(p: dict) -> str:
    return "  ·  ".join(_kontakt_liste(p))


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


def render_cv_fitted(data: dict, out_dir: Path, filename: str, template: str = DEFAULT_TEMPLATE,
                     accent: str | None = None, options: dict | None = None) -> tuple[Path, dict, list[str]]:
    """Wie render_cv, hält aber «max_seiten» ein. Liefert PDF, tatsächlich verwendete Optionen und Anpassungen."""
    opts = {**DEFAULT_CV_OPTIONS, **(options or {})}
    pdf = _render_cv_once(data, out_dir, filename, template, accent, opts)
    limit = int(opts.get("max_seiten") or 0)
    notes: list[str] = []
    if limit <= 0 or _page_count(pdf) <= limit:
        return pdf, opts, notes
    for change, note in _fit_steps(opts):
        if callable(change):
            change = change(opts)
        if all(opts.get(k) == v for k, v in change.items()):
            continue
        opts = {**opts, **change}
        if "max_punkte" in change:
            notes = [n for n in notes if not n.startswith("max. ")]
        notes.append(note)
        pdf = _render_cv_once(data, out_dir, filename, template, accent, opts)
        if _page_count(pdf) <= limit:
            return pdf, opts, notes
    notes.append(f"{limit} Seite(n) nicht ganz erreichbar – weitere Kürzungen bitte im Inhalt vornehmen")
    return pdf, opts, notes


def render_cv(data: dict, out_dir: Path, filename: str, template: str = DEFAULT_TEMPLATE,
              accent: str | None = None, options: dict | None = None) -> Path:
    return render_cv_fitted(data, out_dir, filename, template, accent, options)[0]


def _render_cv_once(data: dict, out_dir: Path, filename: str, template: str, accent: str | None,
                    options: dict) -> Path:
    tpl = CV_TEMPLATES.get(template, CV_TEMPLATES[DEFAULT_TEMPLATE])
    data = {"kontakt": [], **apply_cv_options(data, options), "akzent": accent or tpl["farbe"]}
    if data.get("foto"):
        src = Path(data["foto"])
        src = src if src.is_absolute() else DATA_DIR / src
        if src.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            img = Image.open(src).convert("RGB")
            img.thumbnail((600, 800))
            img.save(out_dir / "foto.jpg", "JPEG", quality=88)
            data["foto"] = "foto.jpg"
        else:
            data["foto"] = ""
    if not data["kontakt"] and data.get("kontaktzeile"):
        data["kontakt"] = data["kontaktzeile"].split("  ·  ")
    return _render(tpl["datei"], "cv.json", data, out_dir, filename)


def letter_style(template: str = DEFAULT_TEMPLATE, accent: str | None = None,
                 options: dict | None = None) -> dict:
    """Farbe, Schrift und Grösse des Bewerbungsschreibens passend zum gewählten Lebenslauf-Design."""
    tpl = CV_TEMPLATES.get(template, CV_TEMPLATES[DEFAULT_TEMPLATE])
    opts = {**DEFAULT_CV_OPTIONS, **(options or {})}
    font_name = opts["schrift"] if CV_FONTS.get(opts["schrift"]) else tpl["schrift"]
    return {"akzent": accent or tpl["farbe"], "schrift": CV_FONTS[font_name], "schrift_name": font_name,
            "groesse": CV_SIZES.get(opts["groesse"], 1.0)}


def render_letter(data: dict, out_dir: Path, filename: str, template: str = DEFAULT_TEMPLATE,
                  accent: str | None = None, options: dict | None = None) -> Path:
    return _render("letter.typ", "letter.json", {**data, **letter_style(template, accent, options)}, out_dir,
                   filename)


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
