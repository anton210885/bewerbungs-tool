import pytest

from src import quality

TEXT = "Du entwickelst Datenpipelines in Azure und betreust SQL-Datenbanken für unsere Kunden. " * 3


def row(rating, score, ko=False, damals=None):
    return {"rating": quality.RATINGS[rating], "score": score, "ko": ko, "score_damals": damals, "title": rating}


def test_set_label_needs_text_and_valid_rating():
    assert not quality.set_label({"url": "u", "description": "zu kurz"}, {}, "passt")
    assert not quality.set_label({"url": "u", "description": TEXT}, {}, "super")
    assert quality.load_labels() == {}


def test_manual_label_beats_automatic():
    job = {"url": "https://example.org/job?utm_source=x", "title": "Data Engineer", "description": TEXT}
    assert quality.set_label(job, {"score": 72, "ko": []}, "passt", "Firmenseite", automatic=True)
    assert quality.set_label(job, {"score": 72}, "teilweise", "Firmenseite")
    assert not quality.set_label(job, {"score": 72}, "passt_nicht", "Firmenseite", automatic=True)
    label = quality.get_label(job["url"], TEXT)
    assert label["rating"] == "teilweise" and not label["automatisch"] and label["score_damals"] == 72


def test_text_without_url_gets_stable_key_and_can_be_removed():
    job = {"url": "", "title": "Eingefügt", "description": TEXT}
    quality.set_label(job, {"score": 40}, "passt_nicht")
    key = quality.job_key("", TEXT)
    assert key.startswith("text:") and key in quality.load_labels()
    quality.remove_label(key)
    assert quality.load_labels() == {}


def test_spearman_and_pair_accuracy():
    assert quality.spearman([10, 20, 30], [0, 0.5, 1]) == pytest.approx(1.0)
    assert quality.spearman([30, 20, 10], [0, 0.5, 1]) == pytest.approx(-1.0)
    assert quality.spearman([1, 2], [0, 1]) is None
    assert quality.spearman([5, 5, 5], [0, 0.5, 1]) is None
    rows = [row("passt", 80), row("passt_nicht", 30), row("teilweise", 30)]
    # Paare: passt>nicht richtig, passt>teilweise richtig, teilweise vs nicht gleich (halb)
    assert quality.pair_accuracy(rows) == pytest.approx(2.5 / 3)


def test_metrics_finds_wrong_ko_and_outliers():
    rows = ([row("passt", 85, damals=80), row("passt", 75, damals=70), row("passt", 15, ko=True)]
            + [row("teilweise", 55)] * 3 + [row("passt_nicht", 30)] * 4 + [row("passt_nicht", 70)])
    m = quality.metrics(rows)
    assert m["n"] == 11 and m["genug"]
    assert m["nach_einschaetzung"]["passt"] == {"anzahl": 3, "mittel": 58}
    assert m["falsche_ko"] == 1
    assert m["top_passt"] == pytest.approx(2 / 5) and m["top_brauchbar"] == pytest.approx(4 / 5)
    assert m["schwankung"] == 5
    assert {(r["score"], r["rating"]) for r in m["ausreisser"]} == {(15, 1.0), (70, 0.0)}
    assert m["ausreisser"][0]["score"] == 15, "grösster Abstand zuerst"


def test_metrics_need_enough_and_different_ratings():
    assert not quality.metrics([row("passt", 80)] * 12)["genug"]
    assert not quality.metrics([row("passt", 80), row("passt_nicht", 20)])["genug"]


def test_run_check_reevaluates_and_keeps_history(monkeypatch):
    monkeypatch.setattr("src.llm.current_model", lambda: "test-modell")
    for i, (rating, auto) in enumerate([("passt", False), ("passt_nicht", False), ("passt", True)]):
        quality.set_label({"url": f"https://example.org/{i}", "title": f"Stelle {i}", "description": TEXT + str(i)},
                          {"score": 50}, rating, automatic=auto)
    scores = {"https://example.org/0": 90, "https://example.org/1": 20, "https://example.org/2": 60}

    def fake_evaluate(job):
        return {"score": scores[job["url"]], "ko": [], "fazit": "ok"}

    run = quality.run_check({}, include_automatic=False, evaluate=fake_evaluate)
    assert run["kennzahlen"]["n"] == 2 and run["modell"] == "test-modell" and run["fehler"] == []
    assert run["kennzahlen"]["paar_treffer"] == 1.0
    run = quality.run_check({}, include_automatic=True, evaluate=fake_evaluate)
    assert run["kennzahlen"]["n"] == 3
    assert len(quality.load_runs()) == 2


def test_run_check_reports_errors_without_stopping(monkeypatch):
    monkeypatch.setattr("src.llm.current_model", lambda: "m")
    quality.set_label({"url": "https://example.org/a", "title": "A", "description": TEXT}, {}, "passt")
    quality.set_label({"url": "https://example.org/b", "title": "B", "description": TEXT + "b"}, {}, "passt_nicht")

    def flaky(job):
        if job["url"].endswith("b"):
            raise RuntimeError("Zeitüberschreitung")
        return {"score": 70}

    run = quality.run_check({}, evaluate=flaky)
    assert run["kennzahlen"]["n"] == 1 and run["fehler"] == ["B: Zeitüberschreitung"]
