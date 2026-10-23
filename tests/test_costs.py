"""Unit-Tests für Kosten-Schätzung und Zusammenfassung."""
import json

from src import costs


def test_estimate_usd_gpt4o_mini():
    # 1M in + 1M out zu Default-Preisen 0.15 / 0.60
    usd = costs.estimate_usd("gpt-4o-mini", 1_000_000, 1_000_000)
    assert abs(usd - 0.75) < 1e-9


def test_estimate_usd_small_request():
    usd = costs.estimate_usd("gpt-4o-mini", 1000, 500)
    assert usd == (1000 * 0.15 + 500 * 0.60) / 1_000_000


def test_format_money():
    assert costs.format_money(0) == "$0.00"
    assert costs.format_money(1.5) == "$1.50"
    assert costs.format_money(None) == "–"
    assert costs.format_money(12.3, "DIEM") == "12.30 DIEM"


def test_record_and_local_summary(tmp_path, monkeypatch):
    usage = tmp_path / "kosten.json"
    monkeypatch.setattr(costs, "USAGE_PATH", usage)
    costs.record_usage("gpt-4o-mini", 10_000, 2_000)
    costs.record_usage("gpt-4o-mini", 5_000, 1_000)
    summary = costs.local_summary()
    assert summary["aufrufe"] == 2
    assert summary["heute_usd"] > 0
    assert summary["gesamt_usd"] == summary["heute_usd"]
    data = json.loads(usage.read_text(encoding="utf-8"))
    assert len(data["eintraege"]) == 2


def test_local_summary_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(costs, "USAGE_PATH", tmp_path / "missing.json")
    s = costs.local_summary()
    assert s == {
        "heute_usd": 0.0,
        "monat_usd": 0.0,
        "gesamt_usd": 0.0,
        "tokens_heute": 0,
        "aufrufe": 0,
    }
