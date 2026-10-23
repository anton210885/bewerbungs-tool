"""Unit-Tests für Tracker-Statistik und Erinnerungen."""
from datetime import date, timedelta

from src import tracker


def _app(**kwargs):
    base = {
        "id": 1,
        "title": "Engineer",
        "company": "Test AG",
        "status": "gefunden",
        "score": None,
        "applied_at": None,
        "follow_up_at": None,
        "interview_at": None,
        "deadline": None,
        "updated_at": None,
    }
    base.update(kwargs)
    return base


def test_stats_counts_sent_statuses():
    apps = [
        _app(status="gefunden"),
        _app(id=2, status="beworben", applied_at="2026-10-10", score=80),
        _app(id=3, status="Gespräch", applied_at="2026-10-11", score=70),
        _app(id=4, status="Absage", applied_at="2026-10-12", score=60),
    ]
    s = tracker.stats(apps)
    assert s["gesamt"] == 4
    assert s["beworben"] == 3
    assert s["antworten"] == 2
    assert s["einladungen"] == 1
    assert s["antwortquote"] == 67
    assert s["passung_schnitt"] == 70


def test_stats_weekly_chart_uses_applied_at():
    apps = [
        _app(status="beworben", applied_at="2026-10-08"),  # Mi
        _app(id=2, status="beworben", applied_at="2026-10-09"),
    ]
    s = tracker.stats(apps)
    # Montag der Woche 2026-10-05
    assert s["pro_woche"] == {"2026-10-05": 2}


def test_stats_empty():
    s = tracker.stats([])
    assert s["beworben"] == 0
    assert s["antwortquote"] == 0
    assert s["passung_schnitt"] is None


def test_reminder_follow_up_after_days():
    today = date(2026, 10, 15)
    apps = [
        _app(status="beworben", applied_at=(today - timedelta(days=14)).isoformat()),
    ]
    rem = tracker.reminders(apps, today=today)
    assert any(r["art"] == "nachfassen" for r in rem)


def test_reminder_stale_draft():
    today = date(2026, 10, 15)
    apps = [
        _app(status="in Bearbeitung",
             updated_at=(today - timedelta(days=10)).isoformat()),
    ]
    rem = tracker.reminders(apps, today=today)
    assert any(r["art"] == "entwurf" for r in rem)


def test_reminder_ignores_gefunden_without_deadline():
    rem = tracker.reminders([_app(status="gefunden")], today=date(2026, 10, 15))
    assert rem == []
