import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from src import db, documents, jobs
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
    if b1.button("Lebenslauf erstellen", disabled=not can_generate, use_container_width=True, key=f"cv_{app_id}"):
        with st.spinner("Lebenslauf wird angepasst ..."):
            try:
                cv = tailor_cv(profile, app["description"], analysis, hinweise)
                pdf = render_cv(cv, out_dir, safe_filename("Lebenslauf", NAME, company) + ".pdf")
                db.update_application(app_id, cv_json=json.dumps(cv, ensure_ascii=False),
                                      cv_pdf=str(pdf), status=keep_status)
                st.rerun()
            except Exception as e:
                st.error(f"Lebenslauf fehlgeschlagen: {e}")
    if b2.button("Bewerbungsschreiben erstellen", disabled=not can_generate, use_container_width=True,
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
        if d1.button("Dossier erstellen", type="primary", use_container_width=True, key=f"dossier_{app_id}"):
            try:
                documents.build_dossier([Path(app["letter_pdf"]), Path(app["cv_pdf"]), *map(Path, selected)],
                                        dossier_path)
                st.rerun()
            except Exception as e:
                st.error(f"Dossier fehlgeschlagen: {e}")
        download("Dossier herunterladen", str(dossier_path), f"dl_dossier_{app_id}", d2)


tab_docs, tab_check, tab_search, tab_tracker = st.tabs(
    ["1. Meine Unterlagen", "2. Stelle prüfen & bewerben", "Stellensuche", "Tracker"]
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

    st.divider()
    if PROFILE_READY:
        st.success(f"Profil vorhanden: **{NAME}**. Wenn du neue Unterlagen hochlädst, kannst du es neu erstellen.")
    else:
        st.info("Noch kein eigenes Profil. Lade mindestens deinen Lebenslauf hoch und klicke dann auf den Knopf.")
    if st.button("Profil aus meinen Unterlagen erstellen", type="primary",
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

    with st.expander("Profil ansehen und bearbeiten"):
        st.caption("Hier kannst du Angaben korrigieren oder ergänzen, z.B. Verfügbarkeit, Pensum und "
                   "Lohnvorstellung unter `weitere_infos`.")
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
            use_container_width=True,
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
