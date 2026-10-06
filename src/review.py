"""Prüfungen der erstellten Unterlagen: Was hat die KI geändert, Stichwort-Abgleich, Faktencheck."""
import json
import re
from difflib import SequenceMatcher

from src.generate import L, _localize, base_cv_data
from src.llm import chat_json

FACTCHECK_SYSTEM = f"""Du prüfst Bewerbungsunterlagen auf Ehrlichkeit für den {L["markt"]} Arbeitsmarkt.
{L["stil"]}
Du erhältst das Bewerberprofil (die einzige Faktenquelle) sowie einen angepassten Lebenslauf und ein
Bewerbungsschreiben. Prüfe jede Aussage: Ist sie durch das Profil belegt?
Melde nur echte Probleme:
- erfundene Tätigkeiten, Tools, Zahlen, Erfolge, Verantwortung oder Abschlüsse
- deutliche Übertreibungen (z.B. «leitete» statt «arbeitete mit», «Experte» ohne Beleg)
- falsche Daten, Firmen oder Titel
Umformulierungen, die inhaltlich stimmen, sind in Ordnung und werden nicht gemeldet.
Antworte mit JSON:
{{"fazit": "<1-2 Sätze>",
  "probleme": [{{"dokument": "<Lebenslauf oder Bewerbungsschreiben>", "aussage": "<wörtlich>",
                "problem": "<was nicht belegt ist>", "vorschlag": "<ehrliche Formulierung>"}}]}}"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def cv_changes(profile: dict, cv: dict) -> dict:
    """Stellt Profil und angepassten Lebenslauf gegenüber (pro Stelle, Kurzprofil, Kenntnisse)."""
    base = base_cv_data(profile)
    positions = []
    src_positions = profile.get("berufserfahrung") or []
    for i, entry in enumerate(cv.get("berufserfahrung", [])):
        src = src_positions[i] if i < len(src_positions) else {}
        original = [str(x) for x in [*(src.get("erfolge") or []), *(src.get("aufgaben") or [])] if str(x).strip()]
        bullets = []
        for punkt in entry.get("punkte", []):
            best = max((SequenceMatcher(None, _norm(punkt), _norm(o)).ratio() for o in original), default=0.0)
            status = "unverändert" if best >= 0.9 else "umformuliert" if best >= 0.5 else "neu formuliert"
            bullets.append({"text": punkt, "status": status})
        positions.append({"titel": entry.get("titel", ""), "untertitel": entry.get("untertitel", ""),
                          "original": original, "neu": bullets})

    def skills(data: dict) -> set[str]:
        return {s.strip() for k in data.get("kenntnisse", []) if k["label"] in ("Fachlich", "Software")
                for s in k["text"].split(",") if s.strip()}

    return {
        "kurzprofil_alt": base.get("kurzprofil", ""),
        "kurzprofil_neu": cv.get("kurzprofil", ""),
        "positionen": positions,
        "weggelassene_kenntnisse": sorted(skills(base) - skills(cv)),
    }


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(v) for v in value)
    return str(value or "")


def _contains(text: str, keyword: str) -> bool:
    kw = _norm(keyword)
    if not kw:
        return False
    if kw in text:
        return True
    words = [w for w in re.split(r"[\s/,()\-]+", kw) if len(w) > 3]
    return bool(words) and all(w[:max(4, len(w) - 2)] in text for w in words)


def keyword_coverage(keywords: list[str], cv: dict | None, letter: dict | None, profile: dict) -> dict:
    """Wie viele wichtige Begriffe aus dem Inserat in Lebenslauf/Schreiben vorkommen."""
    docs_text = _norm(_flatten(cv or {}) + " " + _flatten(letter or {}))
    profile_text = _norm(_flatten(profile))
    found, addable, missing = [], [], []
    for kw in dict.fromkeys(k.strip() for k in keywords if k and k.strip()):
        if _contains(docs_text, kw):
            found.append(kw)
        elif _contains(profile_text, kw):
            addable.append(kw)
        else:
            missing.append(kw)
    total = len(found) + len(addable) + len(missing)
    return {"prozent": round(100 * len(found) / total) if total else 0, "gefunden": found,
            "im_profil": addable, "fehlt": missing}


def fact_check(profile: dict, cv: dict | None, letter: dict | None) -> dict:
    user = (f"PROFIL (Faktenquelle):\n{json.dumps(profile, ensure_ascii=False, default=str)}\n\n"
            f"LEBENSLAUF:\n{json.dumps(cv or {}, ensure_ascii=False)}\n\n"
            f"BEWERBUNGSSCHREIBEN:\n{json.dumps(letter or {}, ensure_ascii=False)}")
    return _localize(chat_json(FACTCHECK_SYSTEM, user, temperature=0.0, max_tokens=4000))
