import threading

import pytest

from src import models, quality

TEXT = "Du entwickelst Datenpipelines in Azure und betreust SQL-Datenbanken für unsere Kunden. " * 3
RATINGS = ["passt"] * 7 + ["teilweise"] * 6 + ["passt_nicht"] * 7


def rows(scores, ko=None):
    return [{"key": f"k{i}", "rating": quality.RATINGS[r], "score": s, "ko": bool(ko and i in ko),
             "kriterien": {}} for i, (r, s) in enumerate(zip(RATINGS, scores))]


GOOD = [90, 85, 88, 80, 84, 86, 82] + [55, 50, 58, 52, 54, 57] + [20, 25, 15, 30, 22, 18, 28]
RANDOM = [40, 70, 20, 55, 30, 65, 45] + [60, 25, 80, 35, 50, 75] + [85, 30, 60, 45, 70, 20, 55]


def test_clearly_better_variant_is_recognised():
    result = quality.compare(rows(RANDOM), rows(GOOD))
    assert result["gemeinsam"] == 20 and result["genug"]
    for name in ("top_passt", "paar_treffer", "rangkorrelation"):
        entry = result["kennzahlen"][name]
        assert entry["urteil"] == "B besser", name
        assert entry["p_besser"] >= quality.CONFIDENT and entry["diff"] > 0
    assert quality.compare(rows(GOOD), rows(RANDOM))["kennzahlen"]["paar_treffer"]["urteil"] == "B schlechter"


def test_same_results_are_no_difference():
    result = quality.compare(rows(GOOD), rows(GOOD))
    for entry in result["kennzahlen"].values():
        assert entry["diff"] == 0 and entry["urteil"] == "kein klarer Unterschied"


def test_fewer_wrong_ko_is_better():
    with_ko = rows(GOOD, ko={0, 1, 2})  # drei Stellen mit «passt» fälschlich K.-o.
    entry = quality.compare(with_ko, rows(GOOD))["kennzahlen"]["falsche_ko"]
    assert (entry["a"], entry["b"], entry["diff"]) == (3, 0, -3)
    assert not entry["hoeher_besser"] and entry["p_besser"] > 0.9


def test_compare_only_uses_jobs_both_rated_and_flags_small_samples():
    a, b = rows(GOOD), rows(GOOD)[:5]
    result = quality.compare(a, b)
    assert result["gemeinsam"] == 5 and not result["genug"]
    assert result["kennzahlen"]["paar_treffer"]["urteil"] == "zu wenig Stellen"


def test_fast_metrics_match_the_slow_ones():
    sample = rows(RANDOM, ko={3, 15})
    slow = quality.metrics(sample)
    fast = quality._fast_metrics(*quality._arrays(sample))
    assert fast["paar_treffer"] == pytest.approx(slow["paar_treffer"])
    assert fast["rangkorrelation"] == pytest.approx(slow["rangkorrelation"])
    assert fast["top_passt"] == pytest.approx(slow["top_passt"])
    assert fast["falsche_ko"] == slow["falsche_ko"]


def test_rescore_with_other_weights_without_ai():
    base = [
        {"key": "a", "rating": 1.0, "score": 60, "ko": False,
         "kriterien": {"aufgaben": 9, "muss": 3, "wuensche": 5, "senioritaet": None}},
        {"key": "b", "rating": 1.0, "score": 15, "ko": True,
         "kriterien": {"aufgaben": 9, "muss": 9, "wuensche": 9, "senioritaet": 9}},
        {"key": "c", "rating": 0.0, "score": 0, "ko": True, "kriterien": {}},
    ]
    only_tasks = quality.rescore(base, {"aufgaben": 100, "muss": 0, "wuensche": 0, "senioritaet": 0})
    assert [r["score"] for r in only_tasks] == [90, 20, 0], "K.-o. bleibt gedeckelt, ohne Einzelwerte unverändert"
    assert base[0]["score"] == 60, "Original bleibt"


def test_use_model_only_for_this_thread(monkeypatch):
    monkeypatch.setattr(models.settings, "load", lambda: {"llm_model": "eingestellt"})
    seen = {}
    with models.use_model("test-b"):
        seen["hier"] = models.current_model()
        other = threading.Thread(target=lambda: seen.update(anderer=models.current_model()))
        other.start()
        other.join()
    seen["danach"] = models.current_model()
    assert seen == {"hier": "test-b", "anderer": "eingestellt", "danach": "eingestellt"}


def _labels():
    for i, rating in enumerate(["passt", "passt", "teilweise", "passt_nicht", "passt_nicht"]):
        quality.set_label({"url": f"https://example.org/{i}", "title": f"Stelle {i}", "description": TEXT + str(i)},
                          {"score": 50}, rating)


def test_run_ab_evaluates_both_on_the_same_jobs(monkeypatch):
    monkeypatch.setattr("src.llm.current_model", lambda: "eingestellt")
    monkeypatch.setattr(quality, "logic_version", lambda: "abc12345")
    _labels()
    good = {f"https://example.org/{i}": s for i, s in enumerate([90, 80, 50, 20, 10])}
    bad = {f"https://example.org/{i}": s for i, s in enumerate([20, 30, 50, 80, 90])}
    result = quality.run_ab({}, {"modell": "modell-a"}, {"modell": ""}, evaluators={
        "a": lambda job: {"score": bad[job["url"]], "kriterien": {"aufgaben": {"wert": 5}}},
        "b": lambda job: {"score": good[job["url"]]},
    })
    assert result["a"]["modell"] == "modell-a" and result["b"]["modell"] == "eingestellt"
    assert result["vergleich"]["gemeinsam"] == 5
    assert result["vergleich"]["kennzahlen"]["paar_treffer"]["diff"] > 0
    assert result["a"]["zeilen"][0]["kriterien"] == {"aufgaben": 5}
    assert quality.load_ab()[-1]["logik"] == "abc12345"


def test_runs_store_version_and_rows_for_later_comparison(monkeypatch):
    monkeypatch.setattr("src.llm.current_model", lambda: "m")
    _labels()
    first = quality.run_check({}, evaluate=lambda job: {"score": 50})
    second = quality.run_check({}, evaluate=lambda job: {"score": 90 - 15 * int(job["url"][-1])})
    assert len(first["logik"]) == 8 and first["gewichtung"]["aufgaben"] == 40
    assert len(second["zeilen"]) == 5 and {"key", "rating", "score", "ko", "kriterien"} == set(second["zeilen"][0])
    comparison = quality.compare_runs(*quality.load_runs())
    assert comparison["kennzahlen"]["paar_treffer"]["b"] == 1.0
