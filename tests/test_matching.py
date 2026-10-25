from src import matching

PROFILE = {
    "sprachen": [{"sprache": "Deutsch", "niveau": "Muttersprache"}, {"sprache": "Englisch", "niveau": "B2"}],
    "berufserfahrung": [{"position": "Data Engineer", "von": "01/2020", "bis": "12/2021"},
                        {"position": "Entwickler", "von": "06/2021", "bis": "12/2022"}],
    "zielprofil": {"senioritaet": ["junior", "mid"], "pensum_min": 80, "arbeitsmodell": ["hybrid", "remote"],
                   "max_reisetaetigkeit": 20, "no_go": ["1st-Level-Support"]},
}


def test_experience_years_merges_overlaps_and_prefers_explicit_value():
    assert matching.erfahrung_jahre(PROFILE) == 3.0
    assert matching.erfahrung_jahre({**PROFILE, "zielprofil": {"relevante_erfahrung_jahre": "4"}}) == 4.0


def test_zielprofil_falls_back_to_wishes_and_validates_weights():
    ziel = matching.zielprofil({"wuensche": {"wunschberufe": ["Data Engineer", ""], "pensum": "80-100%"},
                                "zielprofil": {"gewichtung": {"aufgaben": 60, "muss": "x", "fremd": 5}}})
    assert ziel["rollen"] == ["Data Engineer"]
    assert ziel["pensum_min"] == 80
    assert ziel["gewichtung"] == {**matching.GEWICHTUNG, "aufgaben": 60}


def test_ko_criteria_are_checked_in_code():
    ziel = matching.zielprofil(PROFILE)
    anf = {"titel": "1st-Level-Support Engineer", "pensum_min": 50, "pensum_max": 60, "senioritaet": "Senior",
           "min_jahre_erfahrung": 8, "arbeitsmodell": "vor_ort", "reisetaetigkeit_prozent": "40 %",
           "sprachen": [{"sprache": "French", "muss": True}, {"sprache": "Englisch", "muss": True},
                        {"sprache": "Italienisch", "muss": False}],
           "no_go_treffer": []}
    ko = " ".join(matching.ko_kriterien(PROFILE, ziel, anf))
    for expected in ("Pensum", "8 Jahre", "Arbeitsmodell", "Reisetätigkeit", "French",
                     "No-Go: 1st-Level-Support"):
        assert expected in ko
    assert "Englisch" not in ko and "Italienisch" not in ko
    assert "Seniorität" not in ko, "ein Senior-Titel allein ist kein K.-o."


def test_senior_title_only_lowers_seniority_value():
    ziel = matching.zielprofil(PROFILE)  # Ziel: junior, mid; Profil: 3 Jahre
    assert matching.ko_kriterien(PROFILE, ziel, {"senioritaet": "senior", "min_jahre_erfahrung": 4}) == []
    assert matching.senioritaet_wert(PROFILE, ziel, {"senioritaet": "senior", "min_jahre_erfahrung": 4}) == 4.5
    assert matching.senioritaet_wert(PROFILE, ziel, {"senioritaet": "mid", "min_jahre_erfahrung": 4}) == 7.5
    assert matching.senioritaet_wert(PROFILE, ziel, {"senioritaet": "senior"}) == 7.0
    assert matching.senioritaet_wert(PROFILE, ziel, {"senioritaet": "mid"}) == 10.0
    assert matching.senioritaet_wert(PROFILE, ziel, {}) is None


def test_no_ko_when_ad_is_silent():
    assert matching.ko_kriterien(PROFILE, matching.zielprofil(PROFILE), {"sprachen": []}) == []


def test_extract_keeps_only_listed_no_go_hits(monkeypatch):
    monkeypatch.setattr(matching, "chat_json", lambda *a, **kw: {"no_go_treffer": ["schichtarbeit", "Erfunden"],
                                                                 "muss": "kein Array"})
    result = matching.extract_requirements("Anzeige", ["Schichtarbeit"])
    assert result["no_go_treffer"] == ["Schichtarbeit"]
    assert result["muss"] == []


def test_extract_drops_values_the_ad_does_not_mention(monkeypatch):
    invented = {"pensum_min": 100, "pensum_max": 100, "arbeitsmodell": "vor_ort", "senioritaet": "null",
                "reisetaetigkeit_prozent": 50, "min_jahre_erfahrung": 5}
    monkeypatch.setattr(matching, "chat_json", lambda *a, **kw: dict(invented))
    result = matching.extract_requirements("Data Engineer in Suhr. Sehr gute SQL-Kenntnisse.")
    assert all(result[key] is None for key in invented)
    result = matching.extract_requirements("Pensum 80-100 %, 2 Tage Homeoffice, mind. 5 Jahre Erfahrung.")
    assert result["pensum_max"] == 100 and result["arbeitsmodell"] == "vor_ort"
    assert result["min_jahre_erfahrung"] == 5 and result["reisetaetigkeit_prozent"] is None


def test_must_requirements_need_evidence():
    checks = [{"erfuellt": "ja", "beleg": "Python seit 2020"}, {"erfuellt": "ja", "beleg": ""},
              {"erfuellt": "nein"}, "kaputt"]
    assert matching.muss_wert(checks) == 5.0
    assert matching.muss_wert([]) is None


def test_weighted_score_skips_unrated_criteria():
    kriterien = {"aufgaben": {"wert": 8.0, "gewicht": 40}, "muss": {"wert": None, "gewicht": 30},
                 "wuensche": {"wert": 5.0, "gewicht": 20}, "senioritaet": {"wert": 10.0, "gewicht": 0}}
    assert matching.gesamtscore(kriterien) == 70


def _fake_llm(responses):
    calls = []

    def fake(system, user, **kwargs):
        calls.append(system)
        return responses[len(calls) - 1]
    return fake, calls


def test_analyze_skips_second_call_on_ko(monkeypatch):
    fake, calls = _fake_llm([{"titel": "Senior Engineer", "keywords": ["Python"],
                              "sprachen": [{"sprache": "Französisch", "muss": True}]}])
    monkeypatch.setattr(matching, "chat_json", fake)
    result = matching.analyze(PROFILE, "Anzeige", skip_on_ko=True)
    assert len(calls) == 1
    assert result["score"] == 0 and result["ko"]
    assert result["titel"] == "Senior Engineer" and result["keywords"] == ["Python"]


def test_analyze_computes_score_and_caps_on_ko(monkeypatch):
    anf = {"titel": "Data Engineer", "min_jahre_erfahrung": 3, "muss": ["Python", "SQL"], "arbeitsmodell": "hybrid"}
    bewertung = {"aufgaben": {"bewertung": 9, "begruendung": "passt"}, "wuensche": {"bewertung": "7"},
                 "muss": [{"anforderung": "Python", "erfuellt": "ja", "beleg": "Data Engineer 2020"},
                          {"anforderung": "SQL", "erfuellt": "teilweise", "beleg": ""}],
                 "fazit": "Ja", "luecken": ["Wunsch: Lohn"]}
    fake, _ = _fake_llm([anf, bewertung])
    monkeypatch.setattr(matching, "chat_json", fake)
    result = matching.analyze(PROFILE, "Hybrid, mindestens 3 Jahre Erfahrung")
    # 9*40 + 7.5*30 + 7*20 + 10*10 = 825 → 83
    assert result["score"] == 83
    assert result["kriterien"]["muss"]["wert"] == 7.5
    assert result["luecken"] == ["Wunsch: Lohn"]

    fake, _ = _fake_llm([{**anf, "arbeitsmodell": "vor_ort"}, bewertung])
    monkeypatch.setattr(matching, "chat_json", fake)
    result = matching.analyze(PROFILE, "Hybrid, mindestens 3 Jahre Erfahrung")
    assert result["score"] == matching.KO_MAX_SCORE
    assert result["luecken"][0].startswith("K.-o.:")
