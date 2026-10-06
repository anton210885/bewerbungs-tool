"""Erinnerungen und Statistik für den Bewerbungs-Tracker."""
from datetime import date, datetime, timedelta

FOLLOW_UP_AFTER_DAYS = 14
STALE_DRAFT_DAYS = 7
SENT = ("beworben", "Gespräch", "Zusage", "Absage")


def _date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def reminders(apps: list[dict], today: date | None = None) -> list[dict]:
    """Was jetzt zu tun ist – wichtigstes zuerst. Jede Erinnerung: {art, app, text, prio}."""
    today = today or date.today()
    out = []
    for a in apps:
        status = a.get("status")
        applied, follow, talk, deadline = (_date(a.get(k)) for k in ("applied_at", "follow_up_at", "interview_at",
                                                                       "deadline"))
        label = f"{a.get('title')} – {a.get('company') or '?'}"
        if talk and today <= talk <= today + timedelta(days=7) and status in ("beworben", "Gespräch"):
            days = (talk - today).days
            when = "heute" if days == 0 else "morgen" if days == 1 else f"in {days} Tagen ({talk:%d.%m.})"
            out.append({"art": "gespraech", "app": a, "prio": 0,
                        "text": f"Vorstellungsgespräch {when}: {label}. Bereite dich unter „2. Stelle prüfen & "
                                "bewerben“ → „6. Vorstellungsgespräch vorbereiten“ vor."})
        if deadline and today <= deadline <= today + timedelta(days=5) and status in ("gefunden", "in Bearbeitung"):
            out.append({"art": "frist", "app": a, "prio": 1,
                        "text": f"Bewerbungsfrist am {deadline:%d.%m.}: {label}"})
        if status == "beworben":
            if follow and follow <= today:
                out.append({"art": "nachfassen", "app": a, "prio": 2, "text": f"Nachfassen fällig: {label}"})
            elif not follow and applied and (today - applied).days >= FOLLOW_UP_AFTER_DAYS:
                out.append({"art": "nachfassen", "app": a, "prio": 2,
                            "text": f"Seit {(today - applied).days} Tagen keine Antwort: {label} – jetzt nachfassen?"})
        if status == "in Bearbeitung":
            updated = _date(a.get("updated_at"))
            if updated and (today - updated).days >= STALE_DRAFT_DAYS:
                out.append({"art": "entwurf", "app": a, "prio": 3,
                            "text": f"Seit {(today - updated).days} Tagen angefangen, aber nicht abgeschickt: {label}"})
    return sorted(out, key=lambda r: r["prio"])


def stats(apps: list[dict]) -> dict:
    sent = [a for a in apps if a.get("status") in SENT]
    answered = [a for a in sent if a.get("status") in ("Gespräch", "Zusage", "Absage")]
    invited = [a for a in sent if a.get("status") in ("Gespräch", "Zusage")]
    scores = [a["score"] for a in sent if a.get("score") is not None]
    weeks: dict[date, int] = {}
    for a in sent:
        if d := _date(a.get("applied_at")):
            monday = d - timedelta(days=d.weekday())
            weeks[monday] = weeks.get(monday, 0) + 1
    return {
        "gesamt": len(apps),
        "beworben": len(sent),
        "antworten": len(answered),
        "einladungen": len(invited),
        "antwortquote": round(100 * len(answered) / len(sent)) if sent else 0,
        "einladungsquote": round(100 * len(invited) / len(sent)) if sent else 0,
        "passung_schnitt": round(sum(scores) / len(scores)) if scores else None,
        "pro_woche": {monday.isoformat(): n for monday, n in sorted(weeks.items())},
    }
