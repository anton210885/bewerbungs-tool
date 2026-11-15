"""Belegstellen (RAG): Abschnitte aus den Unterlagen zu den Anforderungen finden und der Bewertung mitgeben."""
from src import documents, evidence, matching
from tests.test_job_index import fake_api  # noqa: F401  (Fixture: Embeddings ohne Netz)

ZEUGNIS = ("=== Seite 1 ===\nHerr Muster automatisierte den Betrieb der Server mit Python und PowerShell. "
           "Er betreute die SQL-Datenbanken zuverlässig und baute neue Pipelines.\n\n"
           "Im Team war er sehr geschätzt. Er arbeitete stets pünktlich und freundlich mit allen zusammen.\n\n"
           "=== Seite 2 ===\nWir danken ihm und wünschen alles Gute.")


def _document(kategorie: str, name: str, text: str, extracted: bool = True):
    path = documents.save_upload(kategorie, name, b"%PDF")
    if extracted:
        documents._cache_path(path).write_text(text, encoding="utf-8")
    return path


def test_split_keeps_whole_sentences_without_page_marks():
    chunks = evidence.split(ZEUGNIS)
    assert chunks and all("=== Seite" not in c for c in chunks)
    assert all(c.endswith((".", "!", "?")) for c in chunks)
    assert all(len(c) <= 2 * evidence.CHUNK_CHARS for c in chunks)


def test_finds_the_matching_passage_and_names_the_source(fake_api):  # noqa: F811
    _document("zeugnisse", "Zeugnis Firma A.pdf", ZEUGNIS)
    _document("lebenslauf", "CV.pdf", "Ausbildung in der Pflege auf der Station mit Patienten im Schichtdienst.")
    _document("zeugnisse", "noch nicht ausgelesen.pdf", "", extracted=False)
    found = evidence.find(["Erfahrung mit Python-Automatisierung und SQL-Datenbanken"])
    assert found and found[0]["quelle"] == "Arbeitszeugnis Zeugnis Firma A"
    assert "PowerShell" in found[0]["text"]
    assert found[0]["zu"] == ["Erfahrung mit Python-Automatisierung und SQL-Datenbanken"]
    assert all("Pflege" not in f["text"] for f in found), "unpassende Auszüge fallen weg"


def test_no_documents_or_switched_off_means_no_evidence(fake_api):  # noqa: F811
    assert evidence.find(["Python"]) == []
    _document("zeugnisse", "Z.pdf", ZEUGNIS)
    with evidence.use_evidence(False):
        assert evidence.for_requirements({"muss": ["Python und SQL"]}) == []
    assert evidence.for_requirements({"muss": ["Python und SQL"]})


def test_analyze_passes_evidence_to_the_ai_and_returns_it(monkeypatch):
    belege = [{"text": "Er betreute die SQL-Datenbanken.", "quelle": "Arbeitszeugnis A", "zu": ["SQL"]}]
    monkeypatch.setattr(evidence, "for_requirements", lambda anf: belege)
    prompts = []

    def fake(system, user, **kw):
        prompts.append((system, user))
        if len(prompts) == 1:
            return {"titel": "Data Engineer", "muss": ["SQL"]}
        return {"aufgaben": {"bewertung": 8}, "wuensche": {"bewertung": 7},
                "muss": [{"anforderung": "SQL", "erfuellt": "ja", "beleg": "[Arbeitszeugnis A] SQL-Datenbanken"}]}
    monkeypatch.setattr(matching, "chat_json", fake)
    result = matching.analyze({"berufserfahrung": []}, "Anzeige")
    system, user = prompts[1]
    assert "BELEGSTELLEN" in system and "[Arbeitszeugnis A] «Er betreute die SQL-Datenbanken.»" in user
    assert result["belegstellen"] == belege
    assert result["kriterien"]["muss"]["wert"] == 10

    monkeypatch.setattr(evidence, "for_requirements", lambda anf: [])
    prompts.clear()
    matching.analyze({"berufserfahrung": []}, "Anzeige")
    assert "BELEGSTELLEN" not in prompts[1][0] + prompts[1][1]


def test_quality_variant_switches_evidence_per_thread(monkeypatch):
    from src import discovery, quality
    seen = []
    monkeypatch.setattr(discovery, "evaluate",
                        lambda profile, job, wishes="": seen.append(evidence.enabled()) or {"analysis": {}})
    quality.evaluator({}, belegstellen=False)({"description": "x"})
    quality.evaluator({})({"description": "x"})
    assert seen == [False, True]
    assert evidence.enabled(), "die Einstellung gilt nur während der Bewertung"
