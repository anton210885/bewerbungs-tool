import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from src import db, jobs
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
from src.profile import load_profile, load_profile_text, save_profile_text

st.set_page_config(page_title="Bewerbungs-Tool", layout="wide")
db.init_db()

st.title("Bewerbungs-Tool")
LLM_OK = llm_configured()
if not LLM_OK:
    st.warning("Kein `LLM_API_KEY` in der `.env` gefunden – die KI-Funktionen sind deaktiviert.")

tab_profil, tab_suche, tab_bewerbung, tab_tracker = st.tabs(
    ["Profil", "Stellensuche", "Bewerbung erstellen", "Tracker"]
)


def download(label: str, path: str | None, key: str, col=st):
    if path and Path(path).exists():
        col.download_button(label, Path(path).read_bytes(), file_name=Path(path).name,
                            mime="application/pdf", key=key)


# ---------------------------------------------------------------- Profil
with tab_profil:
    st.caption(
        "Dein Masterprofil mit allem, was du gemacht hast. Die KI wählt pro Stelle das Passende "
        "aus und formuliert um, erfindet aber nichts dazu."
    )
    profil_text = st.text_area("profile.yaml", load_profile_text(), height=650, label_visibility="collapsed")
    if st.button("Profil speichern", type="primary"):
        try:
            save_profile_text(profil_text)
            st.success("Profil gespeichert.")
        except yaml.YAMLError as e:
            st.error(f"Fehler im YAML: {e}")


# ---------------------------------------------------------------- Stellensuche
with tab_suche:
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
        st.info("Für die Schweizer Stellensuche trage `ADZUNA_APP_ID` und `ADZUNA_APP_KEY` in die `.env` ein. "
                "Stellen von jobs.ch, jobup.ch, LinkedIn oder job-room.ch kannst du unten per Link hinzufügen.")

    if st.button("Suchen", type="primary", disabled=not was):
        results = []
        with st.spinner("Suche läuft..."):
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
            if st.button("Zum Tracker hinzufügen", key=f"add_{i}"):
                job_dict = asdict(job)
                job_dict.pop("published")
                if not job_dict["description"]:
                    try:
                        job_dict["description"] = jobs.fetch_url_text(job.url)
                    except Exception:
                        pass
                if db.add_application(job_dict):
                    st.success("Hinzugefügt – weiter unter „Bewerbung erstellen“.")
                else:
                    st.info("Diese Stelle ist bereits im Tracker.")

    st.divider()
    st.subheader("Stelle manuell hinzufügen")
    st.caption("Für jobs.ch, jobup.ch, job-room.ch, LinkedIn, Firmenwebseiten usw.: Link und/oder Anzeigentext einfügen.")
    with st.form("manual", clear_on_submit=True):
        m1, m2, m3 = st.columns(3)
        m_title = m1.text_input("Stellentitel")
        m_company = m2.text_input("Firma")
        m_location = m3.text_input("Ort")
        m_url = st.text_input("Link zur Anzeige")
        m_desc = st.text_area("Anzeigentext (leer lassen = vom Link laden)", height=200)
        submitted = st.form_submit_button("Hinzufügen")
    if submitted:
        if not (m_title or m_url):
            st.error("Bitte mindestens Titel oder Link angeben.")
        else:
            if not m_desc and m_url:
                try:
                    m_desc = jobs.fetch_url_text(m_url)
                except Exception as e:
                    st.warning(f"Text konnte nicht geladen werden ({e}). Bitte später manuell einfügen.")
            db.add_application({
                "source": "Manuell", "title": m_title or "Ohne Titel", "company": m_company,
                "location": m_location, "url": m_url, "description": m_desc,
            })
            st.success("Hinzugefügt – weiter unter „Bewerbung erstellen“.")


# ---------------------------------------------------------------- Bewerbung erstellen
with tab_bewerbung:
    apps = db.list_applications()
    if not apps:
        st.info("Noch keine Stellen im Tracker. Füge zuerst unter „Stellensuche“ eine Stelle hinzu.")
    else:
        labels = {a["id"]: f'#{a["id"]}  {a["title"]} – {a["company"] or "?"}' for a in apps}
        app_id = st.selectbox("Stelle", list(labels), format_func=labels.get)
        app = db.get_application(app_id)
        profile = load_profile()
        out_dir = OUTPUT_DIR / safe_filename(str(app_id), app["company"] or "", app["title"] or "")
        name = (profile.get("persoenlich") or {}).get("name", "")

        if app["url"]:
            st.markdown(f"[Zur Anzeige]({app['url']})  ·  Status: **{app['status']}**")
        desc = st.text_area("Stellenbeschreibung", app["description"] or "", height=250, key=f"desc_{app_id}")
        if desc != (app["description"] or ""):
            db.update_application(app_id, description=desc)
            app["description"] = desc
        if app["url"] and st.button("Beschreibung neu vom Link laden"):
            try:
                db.update_application(app_id, description=jobs.fetch_url_text(app["url"]))
                st.session_state.pop(f"desc_{app_id}", None)
                st.rerun()
            except Exception as e:
                st.error(f"Laden fehlgeschlagen: {e}")

        # 1. Analyse
        st.subheader("1. Passung analysieren")
        if st.button("Analysieren", disabled=not (desc and LLM_OK)):
            with st.spinner("KI analysiert..."):
                try:
                    analysis = analyze_match(profile, desc)
                    db.update_application(app_id, score=analysis["score"],
                                          analysis=json.dumps(analysis, ensure_ascii=False))
                    st.rerun()
                except Exception as e:
                    st.error(f"Analyse fehlgeschlagen: {e}")
        analysis = json.loads(app["analysis"]) if app["analysis"] else None
        if analysis:
            st.metric("Passung", f"{analysis.get('score', 0)} %")
            st.write(analysis.get("zusammenfassung", ""))
            a1, a2 = st.columns(2)
            a1.markdown("**Stärken**\n" + "".join(f"\n- {x}" for x in analysis.get("staerken", [])))
            a2.markdown("**Lücken**\n" + "".join(f"\n- {x}" for x in analysis.get("luecken", [])))
            if analysis.get("keywords"):
                st.markdown("**Keywords:** " + ", ".join(analysis["keywords"]))
            if analysis.get("empfehlung"):
                st.info(analysis["empfehlung"])

        # 2. Unterlagen
        st.subheader("2. Unterlagen erstellen")
        hinweise = st.text_area("Zusätzliche Hinweise für die KI (optional)",
                                placeholder="z.B. Projekt X besonders hervorheben, Lohnvorstellung CHF 85'000, Pensum 80 %",
                                key=f"hint_{app_id}")
        default_recipient = "\n".join(filter(None, [app["company"], app["location"]]))
        recipient = st.text_area("Empfängeradresse (eine Angabe pro Zeile)",
                                 app["recipient"] or default_recipient, height=110, key=f"rec_{app_id}")
        if recipient != (app["recipient"] or default_recipient):
            db.update_application(app_id, recipient=recipient)

        b1, b2 = st.columns(2)
        if b1.button("Lebenslauf erstellen", disabled=not (desc and LLM_OK), use_container_width=True):
            with st.spinner("Lebenslauf wird angepasst..."):
                try:
                    cv = tailor_cv(profile, desc, analysis, hinweise)
                    pdf = render_cv(cv, out_dir, safe_filename("Lebenslauf", name, app["company"] or "") + ".pdf")
                    db.update_application(app_id, cv_json=json.dumps(cv, ensure_ascii=False), cv_pdf=str(pdf),
                                          status="in Bearbeitung" if app["status"] == "gefunden" else app["status"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Lebenslauf fehlgeschlagen: {e}")
        if b2.button("Anschreiben erstellen", disabled=not (desc and LLM_OK), use_container_width=True):
            with st.spinner("Anschreiben wird geschrieben..."):
                try:
                    letter = write_letter(profile, app, analysis, hinweise)
                    data = build_letter_data(profile, letter, recipient.splitlines())
                    pdf = render_letter(data, out_dir, safe_filename("Anschreiben", name, app["company"] or "") + ".pdf")
                    db.update_application(app_id, letter_json=json.dumps(letter, ensure_ascii=False),
                                          letter_pdf=str(pdf),
                                          status="in Bearbeitung" if app["status"] == "gefunden" else app["status"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Anschreiben fehlgeschlagen: {e}")

        download("Lebenslauf (PDF) herunterladen", app["cv_pdf"], f"dl_cv_{app_id}", b1)
        download("Anschreiben (PDF) herunterladen", app["letter_pdf"], f"dl_letter_{app_id}", b2)

        # 3. Anschreiben überarbeiten
        if app["letter_json"]:
            st.subheader("3. Anschreiben prüfen und bearbeiten")
            st.caption("Lies das Anschreiben immer selbst durch, bevor du es abschickst.")
            letter = json.loads(app["letter_json"])
            with st.form(f"edit_letter_{app_id}"):
                betreff = st.text_input("Betreff", letter["betreff"])
                anrede = st.text_input("Anrede", letter["anrede"])
                absaetze = st.text_area("Text (Absätze durch Leerzeile trennen)",
                                        "\n\n".join(letter["absaetze"]), height=400)
                gruss = st.text_input("Grußformel", letter["gruss"])
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


# ---------------------------------------------------------------- Tracker
with tab_tracker:
    apps = db.list_applications()
    if not apps:
        st.info("Noch keine Bewerbungen.")
    else:
        df = pd.DataFrame(apps)
        counts = df["status"].value_counts()
        cols = st.columns(len(db.STATUS_OPTIONS))
        for col, status in zip(cols, db.STATUS_OPTIONS):
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
