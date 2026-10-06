"""Gemeinsame Bausteine der Oberfläche."""
import json
import re
from pathlib import Path

import streamlit as st

from src import db, documents, jobs, settings, word
from src.config import DATA_DIR, OUTPUT_DIR
from src.generate import (
    CV_TEMPLATES,
    analyze_match,
    build_letter_data,
    render_cv_fitted,
    render_letter,
    safe_filename,
    tailor_cv,
    write_letter,
)
from ui import state as S

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def download(label: str, path: str | None, key: str, col=st):
    if path and Path(path).exists():
        mime = DOCX_MIME if Path(path).suffix == ".docx" else "application/pdf"
        col.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, mime=mime, key=key)


def show_pdf_preview(path: str) -> None:
    for page in documents.pdf_to_images(Path(path), dpi=90):
        st.image(page, width="stretch")


def styled_cv(data: dict, out_dir: Path, filename: str) -> Path:
    """Erstellt den Lebenslauf im gewählten Design als PDF und zusätzlich als Word-Datei daneben."""
    pdf, used_options, _ = render_cv_fitted(data, out_dir, filename, template=S.CV_TEMPLATE, accent=S.CV_ACCENT,
                                            options=S.CV_OPTIONS)
    word.save_cv_docx(data, pdf.with_suffix(".docx"), template=S.CV_TEMPLATE, accent=S.CV_ACCENT,
                      options=used_options)
    return pdf


def _photo_stamp(data: dict) -> float:
    foto = Path(data.get("foto") or "")
    foto = foto if foto.is_absolute() else DATA_DIR / foto
    return foto.stat().st_mtime if data.get("foto") and foto.exists() else 0.0


@st.cache_data(show_spinner=False, max_entries=60)
def template_preview(template: str, accent: str, data_json: str, dpi: int, photo_stamp: float,
                     options_json: str):
    data = json.loads(data_json)
    pdf, used_options, notes = render_cv_fitted(data, OUTPUT_DIR / "vorlagen" / f"{template}_{dpi}",
                                                "vorschau.pdf", template=template, accent=accent,
                                                options=json.loads(options_json))
    return pdf.read_bytes(), documents.pdf_to_images(pdf, dpi=dpi), used_options, notes


@st.cache_data(show_spinner=False, max_entries=20)
def cv_photo_candidates_cached(files: tuple) -> list[tuple[str, bytes]]:
    return documents.cv_photo_candidates()


@st.cache_data(show_spinner=False, max_entries=200)
def _doc_thumb(path_str: str, mtime: float) -> bytes | None:
    return documents.document_thumbnail(Path(path_str))


def _document_card(path: Path) -> None:
    info = documents.document_info(path)
    summary = documents.load_summary(path) or {}
    excluded = documents.is_excluded(path)
    key = f"{path.parent.name}_{path.name}"
    with st.container(border=True):
        c_img, c_txt, c_act = st.columns([1, 5, 1.4])
        thumb = _doc_thumb(str(path), path.stat().st_mtime)
        if thumb:
            c_img.image(thumb, width="stretch")
        else:
            c_img.markdown(f"**{path.suffix.upper().lstrip('.')}**")
        with c_txt:
            st.markdown(f"**{summary.get('titel') or path.name}**"
                        + ("  ·  :orange[nicht verwendet]" if excluded else ""))
            meta = [path.name, f"hochgeladen {info['hochgeladen']}",
                    f"{info['seiten']} Seite(n)" if info["seiten"] else "", f"{info['groesse_kb']} KB"]
            st.caption("  ·  ".join(m for m in meta if m))
            if summary:
                facts = [f"**{summary.get('typ', '')}**", summary.get("aussteller", ""),
                         summary.get("zeitraum", ""),
                         f"Stand {summary['stand']}" if summary.get("stand") else ""]
                st.markdown("  ·  ".join(f for f in facts if f and f != "****"))
                if summary.get("bewertung"):
                    st.markdown(f"**Bewertung:** {summary['bewertung']}")
                if summary.get("kernaussagen"):
                    st.markdown("".join(f"\n- {x}" for x in summary["kernaussagen"]))
                if hinweise := [h for h in summary.get("hinweise", []) if h]:
                    st.warning("**Auffällig:**" + "".join(f"\n- {x}" for x in hinweise))
            else:
                st.caption("Noch kein Steckbrief – oben auf „Steckbriefe erstellen“ klicken.")
        with c_act:
            use = st.toggle("Verwenden", not excluded, key=f"use_{key}",
                            help="Fliesst ins Profil, in die Lebenslauf-Analyse und ins Dossier ein.")
            if use == excluded:
                documents.set_excluded(path, not use)
                st.rerun()
            if st.button("Löschen", key=f"del_{key}", width="stretch"):
                documents.delete_document(path)
                st.rerun()


def _cv_comparison(docs: list[Path]) -> None:
    st.markdown(f"**Deine {len(docs)} Lebensläufe im Vergleich**")
    cmp = documents.load_cv_comparison(docs)
    if st.button("Neu vergleichen" if cmp else "Lebensläufe von KI vergleichen lassen", key="cmp_cvs",
                 type="secondary" if cmp else "primary", disabled=not S.LLM_OK):
        with st.spinner("KI vergleicht deine Lebensläufe ..."):
            try:
                documents.compare_cvs(docs)
                st.rerun()
            except Exception as e:
                st.error(f"Vergleich fehlgeschlagen: {e}")
    if not cmp:
        return
    st.info(cmp.get("zusammenfassung", ""))
    st.caption(f"Erstellt am {cmp.get('erstellt', '')}")
    entries = cmp.get("dokumente", [])
    for col, d in zip(st.columns(max(1, len(entries))), entries):
        with col, st.container(border=True):
            st.markdown(f"**{d.get('datei', '')}**  \nStand: {d.get('stand') or 'unbekannt'}")
            st.markdown("Stärken" + "".join(f"\n- {x}" for x in d.get("staerken", [])))
            st.markdown("Schwächen" + "".join(f"\n- {x}" for x in d.get("schwaechen", [])))
    for item in cmp.get("nur_in", []):
        if item.get("inhalte"):
            st.markdown(f"**Steht nur in {item.get('datei', '')}:**" + "".join(f"\n- {x}" for x in item["inhalte"]))
    if cmp.get("widersprueche"):
        st.warning("**Widersprüche zwischen den Lebensläufen:**"
                   + "".join(f"\n- **{w.get('thema', '')}:** {w.get('details', '')}" for w in cmp["widersprueche"]))
    if cmp.get("empfehlung"):
        st.success(f"**Empfehlung:** {cmp['empfehlung']}")
    st.caption("Tipp: Einen veralteten Lebenslauf kannst du oben mit „Verwenden“ ausschalten. Widersprüche "
               "klärst du am besten im Feld „Ergänzungen & Wünsche“ und erstellst danach das Profil neu.")


def show_documents_overview() -> None:
    all_docs = {k: documents.list_documents(k) for k in documents.KATEGORIEN}
    if not any(all_docs.values()):
        return
    st.subheader("Übersicht deiner Unterlagen")
    missing = [p for docs in all_docs.values() for p in docs if documents.load_summary(p) is None]
    o1, o2 = st.columns([3, 1])
    o1.caption("Zu jedem Dokument erstellt die KI einen kurzen Steckbrief. Mit „Verwenden“ legst du fest, ob ein "
               "Dokument ins Profil, die Analyse und das Dossier einfliesst – z.B. einen veralteten Lebenslauf "
               "ausschalten.")
    if missing and o2.button(f"Steckbriefe erstellen ({len(missing)})", disabled=not S.LLM_OK, width="stretch"):
        progress = st.progress(0.0)
        failed = []
        for i, path in enumerate(missing):
            progress.progress(i / len(missing), text=f"KI liest {path.name} ...")
            try:
                documents.summarize_document(path)
            except Exception as e:
                failed.append(f"{path.name}: {e}")
        if failed:
            st.error("Nicht geklappt:" + "".join(f"\n- {f}" for f in failed))
        else:
            st.rerun()
    for kat, label in documents.KATEGORIEN.items():
        docs = all_docs[kat]
        if not docs:
            continue
        used = sum(not documents.is_excluded(p) for p in docs)
        with st.expander(f"{label}: {len(docs)} Dokument(e), davon {used} verwendet", expanded=kat == "lebenslauf"):
            for path in docs:
                _document_card(path)
            if kat == "lebenslauf" and len(docs) >= 2:
                _cv_comparison(docs)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _lines(text: str) -> list[str]:
    return [re.sub(r"^\s*[-•*]\s*", "", line).strip() for line in text.splitlines() if line.strip()]


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
            analysis = analyze_match(S.profile, job["description"])
        except Exception as e:
            st.error(f"Analyse fehlgeschlagen: {e}")
            return

    app_id = store_job(url, job, analysis, meta)
    st.session_state["current_app"] = app_id
    st.session_state["notice"] = (
        f"Stelle geprüft: {job.get('title') or analysis.get('titel')} ({analysis['score']} % Passung). "
        "Details unter „2. Stelle prüfen & bewerben“."
    )
    st.rerun()


def store_job(url: str, job: dict, analysis: dict, meta: dict | None = None) -> int:
    """Geprüfte Stelle im Tracker speichern (bzw. aktualisieren). Gibt die ID zurück."""
    meta = meta or {}
    fields = {
        "title": meta.get("title") or analysis.get("titel") or job.get("title") or "Ohne Titel",
        "company": meta.get("company") or job.get("company") or analysis.get("firma", ""),
        "location": meta.get("location") or job.get("location") or analysis.get("ort", ""),
        "url": url,
        "description": job.get("description", ""),
        "score": analysis["score"],
        "analysis": json.dumps(analysis, ensure_ascii=False),
    }
    source = meta.get("source") or ("Link" if url else "Text")
    external_id = meta.get("external_id") or url or None
    existing = db.find_application(source, external_id) if external_id else None
    if existing:
        db.update_application(existing["id"], **fields)
        return existing["id"]
    return db.add_application({"source": source, "external_id": external_id, **fields})


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
                 disabled=not (app["description"] and S.LLM_OK), key=f"analyze_{app_id}"):
        with st.spinner("KI analysiert ..."):
            try:
                analysis = analyze_match(S.profile, app["description"])
                db.update_application(app_id, score=analysis["score"],
                                      analysis=json.dumps(analysis, ensure_ascii=False))
                st.rerun()
            except Exception as e:
                st.error(f"Analyse fehlgeschlagen: {e}")

    # 2. Unterlagen
    st.subheader("2. Unterlagen erstellen")
    hinweise = st.text_area("Zusätzliche Hinweise für die KI (optional)", key=f"hint_{app_id}",
                            placeholder="z.B. Projekt X besonders hervorheben, Lohnvorstellung CHF 85'000, Pensum 80 %")
    default_recipient = "\n".join(filter(None, [company, app["location"]]))
    recipient = st.text_area("Empfängeradresse (eine Angabe pro Zeile)",
                             app["recipient"] or default_recipient, height=110, key=f"rec_{app_id}")
    if recipient != (app["recipient"] or default_recipient):
        db.update_application(app_id, recipient=recipient)
    can_generate = bool(app["description"] and S.LLM_OK and S.PROFILE_READY)

    # Lebenslauf
    st.markdown("#### Lebenslauf")
    cv_label = "Neuen Lebenslauf-Vorschlag erstellen" if app["cv_json"] else "Lebenslauf-Vorschlag erstellen"
    if st.button(cv_label, type="primary" if not app["cv_json"] else "secondary",
                 disabled=not can_generate, key=f"cv_{app_id}"):
        with st.spinner("KI passt deinen Lebenslauf an die Stelle an ..."):
            try:
                cv = tailor_cv(S.profile, app["description"], analysis, hinweise)
                pdf = styled_cv(cv, out_dir, safe_filename("Lebenslauf", S.NAME, company) + ".pdf")
                db.update_application(app_id, cv_json=json.dumps(cv, ensure_ascii=False),
                                      cv_pdf=str(pdf), status=keep_status)
                st.rerun()
            except Exception as e:
                st.error(f"Lebenslauf fehlgeschlagen: {e}")

    if app["cv_json"] and app["cv_pdf"] and Path(app["cv_pdf"]).exists():
        cv = json.loads(app["cv_json"])
        ver = abs(hash(app["cv_json"])) % 10**8
        preview_col, edit_col = st.columns(2)
        with preview_col:
            c_cap, c_design = st.columns([2, 3])
            c_cap.caption("Vorschau")
            if c_design.button(f"Im Design „{CV_TEMPLATES[S.CV_TEMPLATE]['name']}“ neu gestalten",
                               key=f"restyle_{app_id}", width="stretch",
                               help="Design wählst du im Reiter „Mein Lebenslauf“. Der Inhalt bleibt gleich."):
                styled_cv(cv, out_dir, Path(app["cv_pdf"]).name)
                st.rerun()
            show_pdf_preview(app["cv_pdf"])
        with edit_col:
            st.caption("Vorschlag der KI – ändere, was du anders haben möchtest (ein Stichpunkt pro Zeile).")
            with st.form(f"edit_cv_{app_id}_{ver}"):
                kurz = st.text_area("Kurzprofil", cv["kurzprofil"], height=130, key=f"cvk_{app_id}_{ver}")
                exp_texts = [
                    st.text_area(f"{e['titel']} · {e['untertitel']} ({e['zeitraum']})", "\n".join(e["punkte"]),
                                 height=130, key=f"cve_{app_id}_{ver}_{i}")
                    for i, e in enumerate(cv["berufserfahrung"])
                ]
                proj_texts = [
                    st.text_area(f"Projekt: {p['titel']}", "\n".join(p["punkte"]), height=100,
                                 key=f"cvp_{app_id}_{ver}_{i}")
                    for i, p in enumerate(cv["projekte"])
                ]
                kenn_texts = [
                    st.text_input(k["label"], k["text"], key=f"cvs_{app_id}_{ver}_{i}")
                    for i, k in enumerate(cv["kenntnisse"])
                ]
                if st.form_submit_button("Änderungen übernehmen", type="primary"):
                    cv["kurzprofil"] = kurz.strip()
                    for e, text in zip(cv["berufserfahrung"], exp_texts):
                        e["punkte"] = _lines(text)
                    for p, text in zip(cv["projekte"], proj_texts):
                        p["punkte"] = _lines(text)
                    cv["kenntnisse"] = [{"label": k["label"], "text": t.strip()}
                                        for k, t in zip(cv["kenntnisse"], kenn_texts) if t.strip()]
                    pdf = styled_cv(cv, out_dir, Path(app["cv_pdf"]).name)
                    db.update_application(app_id, cv_json=json.dumps(cv, ensure_ascii=False), cv_pdf=str(pdf))
                    st.rerun()

    # Bewerbungsschreiben
    st.markdown("#### Bewerbungsschreiben")
    letter_label = ("Neuen Vorschlag für das Bewerbungsschreiben erstellen" if app["letter_json"]
                    else "Vorschlag für das Bewerbungsschreiben erstellen")
    if st.button(letter_label, type="primary" if not app["letter_json"] else "secondary",
                 disabled=not can_generate, key=f"letter_{app_id}"):
        with st.spinner("KI schreibt dein Bewerbungsschreiben ..."):
            try:
                letter = write_letter(S.profile, app, analysis, hinweise)
                data = build_letter_data(S.profile, letter, recipient.splitlines())
                pdf = render_letter(data, out_dir, safe_filename("Bewerbungsschreiben", S.NAME, company) + ".pdf")
                db.update_application(app_id, letter_json=json.dumps(letter, ensure_ascii=False),
                                      letter_pdf=str(pdf), status=keep_status)
                st.rerun()
            except Exception as e:
                st.error(f"Bewerbungsschreiben fehlgeschlagen: {e}")

    if app["letter_json"] and app["letter_pdf"] and Path(app["letter_pdf"]).exists():
        letter = json.loads(app["letter_json"])
        ver = abs(hash(app["letter_json"] + recipient)) % 10**8
        preview_col, edit_col = st.columns(2)
        with preview_col:
            st.caption("Vorschau")
            show_pdf_preview(app["letter_pdf"])
        with edit_col:
            st.caption("Lies das Schreiben genau durch und passe es an, bevor du es verschickst.")
            with st.form(f"edit_letter_{app_id}_{ver}"):
                betreff = st.text_input("Betreff", letter["betreff"], key=f"lb_{app_id}_{ver}")
                anrede = st.text_input("Anrede", letter["anrede"], key=f"la_{app_id}_{ver}")
                absaetze = st.text_area("Text (Absätze durch Leerzeile trennen)", "\n\n".join(letter["absaetze"]),
                                        height=450, key=f"lt_{app_id}_{ver}")
                gruss = st.text_input("Grussformel", letter["gruss"], key=f"lg_{app_id}_{ver}")
                if st.form_submit_button("Änderungen übernehmen", type="primary"):
                    letter = {
                        "betreff": betreff, "anrede": anrede, "gruss": gruss,
                        "absaetze": [a.strip() for a in absaetze.split("\n\n") if a.strip()],
                    }
                    data = build_letter_data(S.profile, letter, recipient.splitlines())
                    pdf = render_letter(data, out_dir, Path(app["letter_pdf"]).name)
                    db.update_application(app_id, letter_json=json.dumps(letter, ensure_ascii=False),
                                          letter_pdf=str(pdf))
                    st.rerun()

    # 3. Dossier
    dossier_path = out_dir / (safe_filename("Bewerbungsdossier", S.NAME, company) + ".pdf")
    if app["cv_pdf"] and app["letter_pdf"]:
        st.subheader("3. Bewerbungsdossier (ein PDF)")
        st.caption("Bewerbungsschreiben, Lebenslauf, Arbeitszeugnisse und Diplome in einer Datei – "
                   "so wird in der Schweiz meistens beworben. Word-Dateien können nicht eingebunden werden.")
        attachments = [str(p) for p in documents.dossier_attachments()]
        selected = st.multiselect("Beilagen", attachments, default=attachments,
                                  format_func=lambda s: Path(s).name, key=f"att_{app_id}")
        if st.button("Dossier erstellen / aktualisieren", key=f"dossier_{app_id}"):
            try:
                documents.build_dossier([Path(app["letter_pdf"]), Path(app["cv_pdf"]), *map(Path, selected)],
                                        dossier_path)
                st.success("Dossier erstellt.")
            except Exception as e:
                st.error(f"Dossier fehlgeschlagen: {e}")

    # 4. Speichern
    cv_docx = None
    if app["cv_json"] and app["cv_pdf"]:
        cv_docx = Path(app["cv_pdf"]).with_suffix(".docx")
        if not cv_docx.exists():
            word.save_cv_docx(json.loads(app["cv_json"]), cv_docx, template=S.CV_TEMPLATE, accent=S.CV_ACCENT,
                              options=S.CV_OPTIONS)
    files = {
        "Lebenslauf": app["cv_pdf"],
        "Lebenslauf (Word)": str(cv_docx) if cv_docx else None,
        "Bewerbungsschreiben": app["letter_pdf"],
        "Bewerbungsdossier": str(dossier_path),
    }
    files = {label: Path(p) for label, p in files.items() if p and Path(p).exists()}
    if files:
        st.subheader("4. Speichern")
        save_dir = settings.get_save_dir()
        target = Path(save_dir) / safe_filename(company or "Firma", app["title"] or "")
        f1, f2 = st.columns([4, 1])
        f1.markdown(f"**Speicherort:** `{save_dir}`  \nUnterordner: `{target.name}`")
        if f2.button("Ordner wählen …", key=f"pick_{app_id}", width="stretch"):
            chosen = settings.pick_folder(save_dir)
            if chosen:
                settings.set_save_dir(chosen)
                st.rerun()
        to_save = st.multiselect("Welche Dateien speichern?", list(files), default=list(files), key=f"save_sel_{app_id}")
        s1, s2, s3 = st.columns(3)
        if s1.button("Im Ordner speichern", type="primary", width="stretch", key=f"save_{app_id}",
                     disabled=not to_save):
            try:
                copied = settings.copy_files([files[label] for label in to_save], target)
                st.session_state[f"saved_{app_id}"] = str(target)
                st.success(f"{len(copied)} Datei(en) gespeichert in {target}")
            except Exception as e:
                st.error(f"Speichern fehlgeschlagen: {e}")
        if st.session_state.get(f"saved_{app_id}") and s2.button("Ordner öffnen", width="stretch",
                                                                  key=f"open_{app_id}"):
            settings.open_folder(Path(st.session_state[f"saved_{app_id}"]))
        with s3.popover("Einzeln herunterladen", width="stretch"):
            for label, path in files.items():
                download(label, str(path), f"dl_{label}_{app_id}")
