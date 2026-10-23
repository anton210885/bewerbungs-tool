"""Suchbegriffe aus vorhandenen Fähigkeiten; keine erfundenen Qualifikationen."""
import re
import unicodedata

MODES = ("Berufe", "Fähigkeiten", "Berufe + Fähigkeiten")
MAX_TERMS = 5


def unique(values):
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str):
            continue
        value = " ".join(value.split()).strip("•- ")
        key = value.casefold()
        if value and key not in seen:
            result.append(value[:120])
            seen.add(key)
    return result


def profile_skills(profile):
    """Übliche Profilformate: Kategorien, Listen, benannte Einträge, Skill→Niveau."""
    found = []
    levels = {"grundkenntnisse", "fortgeschritten", "fortgeschrittene kenntnisse", "experte",
              "expertin", "sehr gut", "gut", "basic", "advanced", "expert", "beginner"}

    def visit(value):
        if isinstance(value, str):
            found.extend(re.split(r"[,;\n]", value))
        elif isinstance(value, list):
            for entry in value:
                visit(entry)
        elif isinstance(value, dict):
            for name in ("name", "bezeichnung", "skill", "faehigkeit"):
                if isinstance(value.get(name), str):
                    visit(value[name])
                    return
            if "text" in value:
                visit(value["text"])
                return
            for key, entry in value.items():
                if key in {"niveau", "level", "bewertung", "jahre", "label", "erfahrung"}:
                    continue
                if isinstance(entry, str) and entry.casefold().strip() in levels:
                    found.append(key)
                else:
                    visit(entry)

    for key in ("skills", "kenntnisse", "faehigkeiten", "kompetenzen"):
        visit(profile.get(key))
    return unique(found)[:80]


def search_terms(preferences):
    roles = unique(preferences.get("terms") or [])
    skills = unique(preferences.get("selected_skills") or [])
    mode = preferences.get("search_mode", "Berufe")
    if mode == "Fähigkeiten":
        values = skills
    elif mode == "Berufe + Fähigkeiten":
        values = [entry for i in range(max(len(roles), len(skills)))
                  for group in (roles, skills) if i < len(group) for entry in [group[i]]]
    else:
        values = roles
    return unique(values)[:MAX_TERMS]


def _normalized(text):
    return unicodedata.normalize("NFKC", text).casefold()


def matching_skills(item, skills):
    """Nur belegbare Texttreffer, kein erfundener semantischer Passungswert."""
    text = _normalized(" ".join(str(item.get(k) or "") for k in ("title", "description")))
    return [skill for skill in unique(skills)
            if re.search(r"(?<!\w)" + re.escape(_normalized(skill)) + r"(?!\w)", text)]


def rank(items, preferences):
    if preferences.get("search_mode", "Berufe") == "Berufe":
        return items
    return sorted(items, key=lambda item: len(matching_skills(item, preferences.get("selected_skills") or [])), reverse=True)


def evaluation_wishes(preferences):
    wishes = preferences.get("wishes", "")
    if preferences.get("search_mode", "Berufe") == "Berufe":
        return wishes
    skills = ", ".join(unique(preferences.get("selected_skills") or []))
    return (wishes + "\nSuche nach Fähigkeiten, auch für andere Berufsbezeichnungen. "
            f"Suchschwerpunkte des Bewerbers: {skills}. "
            "Manuell ergänzte Suchbegriffe sind keine belegten Qualifikationen. Nur Fähigkeiten und Erfahrung "
            "aus dem Profil als vorhanden bewerten. Erkläre in staerken, welche belegten Fähigkeiten auf die "
            "Aufgaben übertragbar sind. Beurteile die tatsächlichen Aufgaben und Anforderungen; ein anderer "
            "bisheriger Jobtitel allein ist keine Lücke. Fehlende Pflichtabschlüsse, Bewilligungen, Sprachen und "
            "Berufserfahrung ehrlich unter luecken nennen. Keine Fähigkeiten hinzuerfinden.")
