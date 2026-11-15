"""Nach dem Laden der Anzeigentexte: die passendsten zuerst, davon die besten unbewerteten bewerten."""
from src import discovery, task_search
from ui import state, tab_discovery

TEXT = "Du leitest das Controlling und planst Budgets mit den Abteilungen. " * 4


def test_evaluate_best_only_unrated_with_text_in_order(monkeypatch):
    monkeypatch.setattr(discovery, "evaluate", lambda profile, item, wishes="": {**item, "analysis": {"score": 70}})
    items = [
        {"url": "u1", "title": "Ohne Text", "description": ""},
        {"url": "u2", "title": "Schon bewertet", "description": TEXT, "analysis": {"score": 50}},
        {"url": "u3", "title": "Verworfen", "description": TEXT, "status": "verworfen"},
        {"url": "u4", "title": "Controller", "description": TEXT},
        {"url": "u5", "title": "Budgetplaner", "description": TEXT},
        {"url": "u6", "title": "Dritter", "description": TEXT},
    ]
    errors = tab_discovery.evaluate_best(items, 2, "")
    assert not errors
    assert [i["title"] for i in items if i.get("analysis", {}).get("score") == 70] == ["Controller", "Budgetplaner"]
    assert items[1]["analysis"]["score"] == 50 and "analysis" not in items[5]


def test_by_fit_keeps_the_same_entries(monkeypatch):
    items = [{"url": "a", "title": "A", "description": ""}, {"url": "b", "title": "B", "description": ""}]
    monkeypatch.setattr(task_search, "rank", lambda profile, found, tasks=None: [dict(found[1]), dict(found[0])])
    monkeypatch.setattr(state, "profile", {})
    ordered = tab_discovery._by_fit(items, [])
    assert ordered[0] is items[1] and ordered[1] is items[0]
