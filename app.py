import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from src import db, documents, jobs, photo
from src.config import COUNTRY, OUTPUT_DIR, adzuna_configured, llm_configured
from src.generate import (
    analyze_match,
    build_letter_data,
    render_cv,
    render_letter,
    safe_filename,
    tailor_cv,
    write_letter,
)
from src.profile import (
    is_example_profile,
    load_profile,
    load_profile_text,
    save_generated_profile,
    save_profile_text,
    set_photo,
)

st.set_page_config(page_title="Bewerbungs-Tool", layout="wide")
db.init_db()
st.session_state.setdefault("upload_round", 0)

st.title("Bewerbungs-Tool")
LLM_OK = llm_configured()
if not LLM_OK:
    st.warning("Kein `LLM_API_KEY` in der `.env` gefunden – die KI-Funktionen sind deaktiviert.")
if notice := st.session_state.pop("notice", None):
    st.success(notice)

profile = load_profile()
PROFILE_READY = not is_example_profile(profile)
NAME = (profile.get("persoenlich") or {}).get("name", "")


# ---------------------------------------------------------------- Hilfsfunktionen
def download(label: str, path: str | None, key: str, col=st):
    if path and Path(path).exists():
        col.download_button(label, Path(path).read_bytes(), file_name=Path(path).name,
                            mime="application/pdf", key=key)


def check_job(url: str, text: str = "", meta: dict | None = None) -> None:
    """Stelle laden, mit dem Profil vergleichen und im Tracker speichern."""
    meta = meta or {}
    job = {"title": "", "company": "", "location": "", "description": text}
    if url and not text:
        with st.spinner("Lade Stellenanzeige ..."):
            try:
                job = jobs.fetch_job(url)
            except Exception as e:
                if not meta.get("description"):
                    st.error(f"Die Seite konnte nicht geladen werden ({e}). "
                             "Bitte kopiere den Anzeigentext ins Textfeld.")
                    return
    if len(job["description"]) < 200 and meta.get("description"):
        job["description"] = meta["description"]
    if len(job["description"]) < 150:
        st.error("Auf der Seite wurde kaum Text gefunden (manche Jobportale laden die Anzeige erst im Browser). "
                 "Bitte kopiere den Anzeigentext ins Textfeld.")
        return

    with st.spinner("KI prüft, ob die Stelle zu dir passt ..."):
        try:
            analysis = analyze_match(profile, job["description"])
        except Exception as e:
            st.error(f"Analyse fehlgeschlagen: {e}")
            return

    fields = {
        "title": meta.get("title") or analysis.get("titel") or job["title"] or "Ohne Titel",
        "company": meta.get("company") or job["company"] or analysis.get("firma", ""),
        "location": meta.get("location") or job["location"] or analysis.get("ort", ""),
        "url": url,
        "description": job["description"],
        "score": analysis["score"],
        "analysis": json.dumps(analysis, ensure_ascii=False),
    }
    source = meta.get("source") or ("Link" if url else "Text")
    external_id = meta.get("external_id") or url or None
    existing = db.find_application(source, external_id) if external_id else None
    if existing:
        db.update_application(existing["id"], **fields)
        app_id = existing["id"]
    else:
        app_id = db.add_application({"source": source, "external_id": external_id, **fields})
    st.session_state["current_app"] = app_id
    st.session_state["notice"] = (
        f"Stelle geprüft: {fields['title']} – {fields['company']} ({analysis['score']} % Passung). "
        "Details unter „2. Stelle prüfen & bewerben“."
    )
    st.rerun()


def show_analysis(analysis: dict) -> None:
    score = analysis.get("score", 0)
    c1, c2 = st.columns([1, 5])
    c1.metric("Passung", f"{score} %")
    fazit = analysis.get("fazit") or analysis.get("zusammenfassung", "")
    box = c2.success if score >= 70 else c2.warning if score >= 45 else c2.error
    box(fazit)
    if analysis.get("fazit") and analysis.get("zusammenfassung"):
        st.write(analysis["zusammenfassung"])
    a1, a2 = st.columns(2)
    a1.markdown("**Was passt**" + "".join(f"\n- {x}" for x in analysis.get("staerken", [])))
    a2.markdown("**Was fehlt**" + "".join(f"\n- {x}" for x in analysis.get("luecken", [])))
    if analysis.get("keywords"):
        st.markdown("**Wichtige Begriffe aus der Anzeige:** " + ", ".join(analysis["keywords"]))
    if analysis.get("empfehlung"):
        st.info(f"**Empfehlung:** {analysis['empfehlung']}")


def render_application(app_id: int) -> None:
    app = db.get_application(app_id)
    company = app["company"] or ""
    out_dir = OUTPUT_DIR / safe_filename(str(app_id), company, app["title"] or "")
    keep_status = "in Bearbeitung" if app["status"] == "gefunden" else app["status"]

    st.markdown(
        f"### {app['title']}\n**{company}** {('· ' + app['location']) if app['location'] else ''}"
        f"  ·  Status: {app['status']}" + (f"  ·  [Zur Anzeige]({app['url']})" if app["url"] else "")
    )

    with st.expander("Stellenbeschreibung"):
        desc = st.text_area("Text", app["description"] or "", height=300, key=f"desc_{app_id}",
                            label_visibility="collapsed")
        if desc != (app["description"] or ""):
            db.update_application(app_id, description=desc)
            app["description"] = desc

    # 1. Analyse
    st.subheader("1. Passt die Stelle zu mir?")
    analysis = json.loads(app["analysis"]) if app["analysis"] else None
    if analysis:
        show_analysis(analysis)
    if st.button("Neu analysieren" if analysis else "Analysieren",
                 disabled=not (app["description"] and LLM_OK), key=f"analyze_{app_id}"):
        with st.spinner("KI analysiert ..."):
            try:
                analysis = analyze_match(profile, app["description"])
                db.update_application(app_id, score=analysis["score"],
                                      analysis=json.dumps(analysis, ensure_ascii=False))
                st.rerun()
            except Exception as e:
                st.error(f"Analyse fehlgeschlagen: {e}")

    # 2. Unterlagen
    st.subheader("2. Lebenslauf und Bewerbungsschreiben erstellen")
    hinweise = st.text_area("Zusätzliche Hinweise für die KI (optional)", key=f"hint_{app_id}",
                            placeholder="z.B. Projekt X besonders hervorheben, Lohnvorstellung CHF 85'000, Pensum 80 %")
    default_recipient = "\n".join(filter(None, [company, app["location"]]))
    recipient = st.text_area("Empfängeradresse (eine Angabe pro Zeile)",
                             app["recipient"] or default_recipient, height=110, key=f"rec_{app_id}")
    if recipient != (app["recipient"] or default_recipient):
        db.update_application(app_id, recipient=recipient)

    can_generate = bool(app["description"] and LLM_OK and PROFILE_READY)
    b1, b2 = st.columns(2)
    if b1.button("Lebenslauf erstellen", disabled=not can_generate, width="stretch", key=f"cv_{app_id}"):
        with st.spinner("Lebenslauf wird angepasst ..."):
            try:
                cv = tailor_cv(profile, app["description"], analysis, hinweise)
                pdf = render_cv(cv, out_dir, safe_filename("Lebenslauf", NAME, company) + ".pdf")
                db.update_application(app_id, cv_json=json.dumps(cv, ensure_ascii=False),
                                      cv_pdf=str(pdf), status=keep_status)
                st.rerun()
            except Exception as e:
                st.error(f"Lebenslauf fehlgeschlagen: {e}")
    if b2.button("Bewerbungsschreiben erstellen", disabled=not can_generate, width="stretch",
                 key=f"letter_{app_id}"):
        with st.spinner("Bewerbungsschreiben wird geschrieben ..."):
            try:
                letter = write_letter(profile, app, analysis, hinweise)
                data = build_letter_data(profile, letter, recipient.splitlines())
                pdf = render_letter(data, out_dir, safe_filename("Bewerbungsschreiben", NAME, company) + ".pdf")
                db.update_application(app_id, letter_json=json.dumps(letter, ensure_ascii=False),
                                      letter_pdf=str(pdf), status=keep_status)
                st.rerun()
            except Exception as e:
                st.error(f"Bewerbungsschreiben fehlgeschlagen: {e}")
    download("Lebenslauf (PDF) herunterladen", app["cv_pdf"], f"dl_cv_{app_id}", b1)
    download("Bewerbungsschreiben (PDF) herunterladen", app["letter_pdf"], f"dl_letter_{app_id}", b2)

    # 3. Schreiben bearbeiten
    if app["letter_json"]:
        st.subheader("3. Bewerbungsschreiben prüfen und bearbeiten")
        st.caption("Lies das Schreiben immer selbst durch, bevor du es abschickst.")
        letter = json.loads(app["letter_json"])
        with st.form(f"edit_letter_{app_id}"):
            betreff = st.text_input("Betreff", letter["betreff"])
            anrede = st.text_input("Anrede", letter["anrede"])
            absaetze = st.text_area("Text (Absätze durch Leerzeile trennen)",
                                    "\n\n".join(letter["absaetze"]), height=400)
            gruss = st.text_input("Grussformel", letter["gruss"])
            if st.form_submit_button("Änderungen übernehmen und PDF neu erzeugen"):
                letter = {
                    "betreff": betreff, "anrede": anrede, "gruss": gruss,
                    "absaetze": [a.strip() for a in absaetze.split("\n\n") if a.strip()],
                }
                data = build_letter_data(profile, letter, recipient.splitlines())
                pdf = render_letter(data, out_dir, Path(app["letter_pdf"]).name)
                db.update_application(app_id, letter_json=json.dumps(letter, ensure_ascii=False),
                                      letter_pdf=str(pdf))
                st.success("PDF aktualisiert.")

    # 4. Dossier
    if app["cv_pdf"] and app["letter_pdf"]:
        st.subheader("4. Bewerbungsdossier (ein PDF)")
        st.caption("Bewerbungsschreiben, Lebenslauf, Arbeitszeugnisse und Diplome in einer Datei – "
                   "so wird in der Schweiz meistens beworben. Word-Dateien können nicht eingebunden werden.")
        attachments = [str(p) for p in documents.dossier_attachments()]
        selected = st.multiselect("Beilagen", attachments, default=attachments,
                                  format_func=lambda s: Path(s).name, key=f"att_{app_id}")
        dossier_path = out_dir / (safe_filename("Bewerbungsdossier", NAME, company) + ".pdf")
        d1, d2 = st.columns(2)
        if d1.button("Dossier erstellen", type="primary", width="stretch", key=f"dossier_{app_id}"):
            try:
                documents.build_dossier([Path(app["letter_pdf"]), Path(app["cv_pdf"]), *map(Path, selected)],
                                        dossier_path)
                st.rerun()
            except Exception as e:
                st.error(f"Dossier fehlgeschlagen: {e}")
        download("Dossier herunterladen", str(dossier_path), f"dl_dossier_{app_id}", d2)


tab_docs, tab_photo, tab_check, tab_search, tab_tracker = st.tabs(
    ["1. Meine Unterlagen", "Bewerbungsfoto", "2. Stelle prüfen & bewerben", "Stellensuche", "Tracker"]
)


# ---------------------------------------------------------------- 1. Meine Unterlagen
with tab_docs:
    st.caption("Lade deinen Lebenslauf, deine Arbeitszeugnisse und Diplome hoch (PDF, Word oder Foto/Scan). "
               "Die KI erstellt daraus dein Profil – die Grundlage für jede Bewerbung.")
    for col, (kat, label) in zip(st.columns(3), documents.KATEGORIEN.items()):
        with col:
            st.markdown(f"**{label}**")
            files = st.file_uploader(label, type=documents.UPLOAD_TYPES, accept_multiple_files=True,
                                     key=f"up_{kat}_{st.session_state.upload_round}",
                                     label_visibility="collapsed")
            if files:
                for f in files:
                    documents.save_upload(kat, f.name, f.getvalue())
                st.session_state.upload_round += 1
                st.rerun()
            for path in documents.list_documents(kat):
                c_name, c_del = st.columns([6, 1])
                c_name.write(path.name)
                if c_del.button("✕", key=f"del_{kat}_{path.name}", help="Löschen"):
                    documents.delete_document(path)
                    st.rerun()

    st.markdown("**Ergänzungen & Wünsche**")
    ergaenzungen = st.text_area(
        "Ergänzungen & Wünsche",
        documents.load_ergaenzungen(),
        height=160,
        label_visibility="collapsed",
        placeholder=(
            "Was nicht in deinen Unterlagen steht und was du dir wünschst, z.B.:\n"
            "- Seit 2024 Weiterbildung zum Sachbearbeiter Rechnungswesen (Abschluss 2025)\n"
            "- Gute Kenntnisse in Excel-Pivot und Power BI\n"
            "- Wunsch: Einkauf oder Logistik, Pensum 80-100 %, Raum Zürich/Winterthur, ab Januar 2027\n"
            "- Lohnvorstellung CHF 80'000"
        ),
    )
    if ergaenzungen != documents.load_ergaenzungen():
        documents.save_ergaenzungen(ergaenzungen)
        st.caption("Gespeichert. Klicke auf „Profil erstellen“, damit die Ergänzungen ins Profil übernommen werden.")

    st.divider()
    if PROFILE_READY:
        st.success(f"Profil vorhanden: **{NAME}**. Nach neuen Unterlagen oder Ergänzungen einfach neu erstellen.")
    else:
        st.info("Noch kein eigenes Profil. Lade mindestens deinen Lebenslauf hoch und klicke dann auf „Profil erstellen“.")

    p1, p2 = st.columns(2)
    if p1.button("Profil aus meinen Unterlagen erstellen", type="primary", width="stretch",
                 disabled=not (LLM_OK and documents.has_documents())):
        with st.status("Unterlagen werden ausgewertet ...", expanded=True) as status:
            try:
                save_generated_profile(documents.profile_from_documents(on_progress=st.write))
                status.update(label="Profil erstellt", state="complete")
                st.session_state["notice"] = "Dein Profil wurde erstellt. Bitte kurz unten prüfen."
                st.rerun()
            except Exception as e:
                status.update(label="Fehler", state="error")
                st.error(f"Profil konnte nicht erstellt werden: {e}")
    if p2.button("Lebenslauf von KI analysieren lassen", width="stretch",
                 disabled=not (LLM_OK and PROFILE_READY)):
        with st.status("Lebenslauf wird analysiert ...", expanded=True) as status:
            try:
                documents.analyze_cv(profile, on_progress=st.write)
                status.update(label="Analyse fertig", state="complete")
                st.rerun()
            except Exception as e:
                status.update(label="Fehler", state="error")
                st.error(f"Analyse fehlgeschlagen: {e}")

    if cv_analysis := documents.load_cv_analysis():
        st.subheader("Analyse deines Lebenslaufs")
        n1, n2 = st.columns([1, 5])
        note = cv_analysis.get("note", 0)
        n1.metric("Note", f"{note}/10")
        (n2.success if note >= 8 else n2.warning if note >= 5 else n2.error)(cv_analysis.get("zusammenfassung", ""))
        st.caption(f"Erstellt am {cv_analysis.get('erstellt', '')}")
        s1, s2 = st.columns(2)
        s1.markdown("**Stärken**" + "".join(f"\n- {x}" for x in cv_analysis.get("staerken", [])))
        s2.markdown("**Schwächen**" + "".join(f"\n- {x}" for x in cv_analysis.get("schwaechen", [])))
        if cv_analysis.get("luecken"):
            st.markdown("**Lücken / fehlende Angaben**" + "".join(f"\n- {x}" for x in cv_analysis["luecken"]))
        if cv_analysis.get("verbesserungen"):
            st.markdown("**Verbesserungsvorschläge**")
            for v in cv_analysis["verbesserungen"]:
                text = f"**{v.get('bereich', '')}:** {v.get('vorschlag', '')}"
                if v.get("beispiel"):
                    text += f"\n\n> {v['beispiel']}"
                st.markdown(text)
        b1, b2 = st.columns(2)
        if cv_analysis.get("passende_berufe"):
            b1.markdown("**Passende Berufe**" + "".join(f"\n- {x}" for x in cv_analysis["passende_berufe"]))
        if cv_analysis.get("suchbegriffe"):
            b2.markdown("**Suchbegriffe für Jobportale**" + "".join(f"\n- {x}" for x in cv_analysis["suchbegriffe"]))
        st.caption("Tipp: Was dir an Angaben fehlt, kannst du oben unter „Ergänzungen & Wünsche“ eintragen "
                   "und dann das Profil neu erstellen.")

    with st.expander("Profil ansehen und bearbeiten"):
        st.caption("Hier kannst du einzelne Angaben direkt korrigieren. Achtung: Beim Neu-Erstellen des Profils "
                   "werden direkte Änderungen überschrieben – Ergänzungen besser oben ins Feld schreiben.")
        profil_text = st.text_area("profile.yaml", load_profile_text(), height=600, label_visibility="collapsed")
        if st.button("Profil speichern"):
            try:
                save_profile_text(profil_text)
                st.success("Profil gespeichert.")
            except yaml.YAMLError as e:
                st.error(f"Fehler im Profil: {e}")


# ---------------------------------------------------------------- 2. Stelle prüfen & bewerben
with tab_check:
    if not PROFILE_READY:
        st.warning("Lade zuerst unter „1. Meine Unterlagen“ deinen Lebenslauf hoch und erstelle dein Profil.")

    with st.form("check", clear_on_submit=True):
        url = st.text_input("Link zur Stellenanzeige", placeholder="https://www.jobs.ch/de/stellenangebote/detail/...")
        text = st.text_area("Oder Anzeigentext einfügen (falls der Link nicht funktioniert)", height=100)
        checked = st.form_submit_button("Passt diese Stelle zu mir?", type="primary",
                                        disabled=not (LLM_OK and PROFILE_READY))
    if checked:
        if url.strip() or text.strip():
            check_job(url.strip(), text.strip())
        else:
            st.error("Bitte einen Link oder den Anzeigentext eingeben.")

    apps = db.list_applications()
    if apps:
        st.divider()
        labels = {
            a["id"]: f'{a["title"]} – {a["company"] or "?"}' + (f'  ({a["score"]} %)' if a["score"] is not None else "")
            for a in apps
        }
        if st.session_state.get("current_app") not in labels:
            st.session_state["current_app"] = apps[0]["id"]
        current = st.selectbox("Geprüfte Stellen", list(labels), format_func=labels.get, key="current_app")
        render_application(current)


# ---------------------------------------------------------------- Bewerbungsfoto
with tab_photo:
    st.caption("Lade ein Foto von dir hoch, z.B. ein Handyfoto vor einer ruhigen Wand. Die KI kann Licht, "
               "Hintergrund und Kleidung verbessern – dein Gesicht soll dabei unverändert bleiben, denn ein "
               "Bewerbungsfoto muss dir ähnlich sehen.")
    photo_upload = st.file_uploader("Foto hochladen", type=["jpg", "jpeg", "png"],
                                    key=f"photo_up_{st.session_state.upload_round}")
    if photo_upload:
        st.session_state["photo_current"] = str(photo.save_original(photo_upload.getvalue()))
        st.session_state.upload_round += 1
        st.rerun()

    versions = photo.list_versions()
    if not versions:
        st.info("Noch kein Foto hochgeladen.")
    else:
        if st.session_state.get("photo_current") not in [str(v) for v in versions]:
            st.session_state["photo_current"] = str(versions[0])
        current = Path(st.session_state["photo_current"])

        left, right = st.columns([1, 2])
        with left:
            st.markdown("**Ausgewählte Version**")
            st.image(str(current), width="stretch")
            if st.button("Als Bewerbungsfoto verwenden", type="primary", width="stretch"):
                photo.use_as_application_photo(current)
                set_photo(photo.FINAL_REL)
                st.session_state["notice"] = "Foto übernommen – es erscheint ab jetzt in deinen Lebensläufen."
                st.rerun()
            if st.button("Foto von KI bewerten lassen", width="stretch", disabled=not LLM_OK):
                with st.spinner("KI bewertet dein Foto ..."):
                    try:
                        st.session_state["photo_review"] = {"path": str(current), **photo.review(current)}
                    except Exception as e:
                        st.error(f"Bewertung fehlgeschlagen: {e}")

        with right:
            st.markdown("**Mit KI bearbeiten**")
            presets = st.multiselect("Was soll verbessert werden?", list(photo.PRESETS),
                                     default=["Professionell aufwerten"])
            custom = st.text_input("Eigener Wunsch (optional)",
                                   placeholder="z.B. Spiegelung in der Brille entfernen, Haare etwas ordentlicher")
            photo_model = st.selectbox("KI-Modell", list(photo.MODELS), format_func=photo.MODELS.get)
            if st.button("Foto bearbeiten", type="primary", disabled=not (LLM_OK and (presets or custom.strip()))):
                with st.spinner("KI bearbeitet dein Foto (ca. 10–60 Sekunden) ..."):
                    try:
                        new_path = photo.edit(current, photo.build_prompt(presets, custom), photo_model)
                        st.session_state["photo_current"] = str(new_path)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Bearbeitung fehlgeschlagen: {e}")
            st.caption("Jede Bearbeitung wird als neue Version gespeichert. Mit „Auswählen“ unten kannst du eine "
                       "Version weiter bearbeiten.")

            review = st.session_state.get("photo_review")
            if review and review.get("path") == str(current):
                note = review.get("note", 0)
                r1, r2 = st.columns([1, 4])
                r1.metric("Note", f"{note}/10")
                (r2.success if note >= 8 else r2.warning if note >= 5 else r2.error)(review.get("fazit", ""))
                st.markdown("**Gut**" + "".join(f"\n- {x}" for x in review.get("positiv", [])))
                st.markdown("**Verbessern**" + "".join(f"\n- {x}" for x in review.get("verbesserungen", [])))
                if review.get("empfohlene_bearbeitungen"):
                    st.markdown("**Empfohlene Bearbeitungen:** " + ", ".join(review["empfohlene_bearbeitungen"]))

        if photo.FINAL_PATH.exists():
            st.markdown("**Aktuelles Bewerbungsfoto im Lebenslauf**")
            st.image(str(photo.FINAL_PATH), width=150)

        st.markdown("**Alle Versionen**")
        grid = st.columns(5)
        for i, version in enumerate(versions):
            with grid[i % 5]:
                label = "Original" if "original" in version.name else "Bearbeitet"
                st.image(str(version), caption=label + (" (ausgewählt)" if version == current else ""),
                         width="stretch")
                v1, v2 = st.columns(2)
                if v1.button("Auswählen", key=f"sel_{version.name}", width="stretch"):
                    st.session_state["photo_current"] = str(version)
                    st.rerun()
                if v2.button("Löschen", key=f"delv_{version.name}", width="stretch"):
                    photo.delete_version(version)
                    st.rerun()


# ---------------------------------------------------------------- Stellensuche
with tab_search:
    c1, c2, c3 = st.columns([2, 2, 1])
    was = c1.text_input("Was (Beruf, Stichwort)")
    wo = c2.text_input("Wo (Ort oder PLZ)")
    umkreis = c3.number_input("Umkreis (km)", 0, 200, 25, step=5)
    BA = "Bundesagentur für Arbeit (Deutschland)"
    ADZUNA = f"Adzuna ({COUNTRY.upper()})"
    quellen_default = [ADZUNA] if adzuna_configured() else []
    if COUNTRY == "de":
        quellen_default.insert(0, BA)
    quellen = st.multiselect("Quellen", [ADZUNA, BA], default=quellen_default)
    if COUNTRY == "ch" and not adzuna_configured():
        st.info("Für die automatische Suche in der Schweiz trage `ADZUNA_APP_ID` und `ADZUNA_APP_KEY` in die "
                "`.env` ein. Stellen von jobs.ch, jobup.ch oder LinkedIn prüfst du einfach per Link "
                "unter „2. Stelle prüfen & bewerben“.")

    if st.button("Suchen", type="primary", disabled=not (was and quellen)):
        results = []
        with st.spinner("Suche läuft ..."):
            for quelle in quellen:
                search = jobs.search_ba if quelle == BA else jobs.search_adzuna
                try:
                    results += search(was, wo, int(umkreis))
                except Exception as e:
                    st.error(f"{quelle}: {e}")
        st.session_state["results"] = results

    results = st.session_state.get("results", [])
    if results:
        st.caption(f"{len(results)} Treffer")
    for i, job in enumerate(results):
        with st.expander(f"{job.title} – {job.company} ({job.location})"):
            st.caption(f"{job.source} · {job.published}")
            if job.description:
                st.write(job.description)
            st.markdown(f"[Zur Anzeige]({job.url})")
            if st.button("Passt sie zu mir?", key=f"check_{i}", disabled=not (LLM_OK and PROFILE_READY)):
                check_job(job.url, meta=asdict(job))


# ---------------------------------------------------------------- Tracker
with tab_tracker:
    apps = db.list_applications()
    if not apps:
        st.info("Noch keine Bewerbungen.")
    else:
        df = pd.DataFrame(apps)
        counts = df["status"].value_counts()
        for col, status in zip(st.columns(len(db.STATUS_OPTIONS)), db.STATUS_OPTIONS):
            col.metric(status, int(counts.get(status, 0)))

        df = df[["id", "status", "score", "title", "company", "location", "source", "url", "notes", "updated_at"]]
        edited = st.data_editor(
            df,
            hide_index=True,
            width="stretch",
            disabled=["id", "score", "title", "company", "location", "source", "url", "updated_at"],
            column_config={
                "id": "ID",
                "status": st.column_config.SelectboxColumn("Status", options=db.STATUS_OPTIONS, required=True),
                "score": st.column_config.NumberColumn("Passung %"),
                "title": "Stelle",
                "company": "Firma",
                "location": "Ort",
                "source": "Quelle",
                "url": st.column_config.LinkColumn("Link", display_text="öffnen"),
                "notes": "Notizen",
                "updated_at": "Geändert",
            },
            key="tracker_editor",
        )
        t1, t2, t3 = st.columns([1, 2, 1])
        if t1.button("Änderungen speichern", type="primary"):
            for row in edited.to_dict("records"):
                notes = row["notes"] if isinstance(row["notes"], str) else None
                db.update_application(int(row["id"]), status=row["status"], notes=notes)
            st.success("Gespeichert.")
            st.rerun()
        del_id = t2.selectbox("Stelle löschen", [a["id"] for a in apps],
                              format_func=lambda i: next(f'#{a["id"]} {a["title"]}' for a in apps if a["id"] == i))
        if t3.button("Löschen"):
            db.delete_application(del_id)
            st.rerun()
