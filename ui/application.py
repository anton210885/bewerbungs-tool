"""Eine Bewerbung: Analyse, Unterlagen, Prüfung, Dossier, Speichern und Gesprächsvorbereitung."""
import json
from pathlib import Path

import streamlit as st

from src import config, cv_builder, db, documents, interview, review, settings, word
from src.generate import (
    CV_TEMPLATES,
    analyze_match,
    build_letter_data,
    render_letter,
    safe_filename,
    suggest_aufgaben,
    tailor_cv,
    translate_cv,
    write_letter,
)
from ui import state as S
from ui.helpers import _lines, download, show_analysis, show_pdf_preview, styled_cv


def styled_letter(data: dict, out_dir: Path, filename: str) -> Path:
    """Bewerbungsschreiben passend zum Lebenslauf-Design als PDF und zusätzlich als Word-Datei."""
    style = {"template": S.CV_TEMPLATE, "accent": S.CV_ACCENT, "options": S.CV_OPTIONS}
    pdf = render_letter(data, out_dir, filename, **style)
    word.save_letter_docx(data, pdf.with_suffix(".docx"), **style)
    return pdf


def _step_state(app: dict, analysis, dossier_path: Path, app_id: int) -> list[tuple[str, str, bool]]:
    return [
        ("analyse", "Passung", bool(analysis)),
        ("cv", "Lebenslauf", bool(app.get("cv_json"))),
        ("letter", "Schreiben", bool(app.get("letter_json"))),
        ("check", "Prüfen", bool(app.get("review_json"))),
        ("dossier", "Dossier", dossier_path.exists()),
        ("save", "Speichern", bool(st.session_state.get(f"saved_{app_id}"))),
    ]


def render_application(app_id: int) -> None:
    app = db.get_application(app_id)
    company = app["company"] or ""
    out_dir = config.output_dir() / safe_filename(str(app_id), company, app["title"] or "")
    keep_status = "in Bearbeitung" if app["status"] == "gefunden" else app["status"]
    dossier_path = out_dir / (safe_filename("Bewerbungsdossier", S.NAME, company) + ".pdf")
    analysis = json.loads(app["analysis"]) if app["analysis"] else None
    steps = _step_state(app, analysis, dossier_path, app_id)
    done_n = sum(1 for *_, ok in steps if ok)
    next_step = next((label for _, label, ok in steps if not ok), None)

    st.markdown(
        f"### {app['title']}\n**{company}** {('· ' + app['location']) if app['location'] else ''}"
        f"  ·  Status: {app['status']}" + (f"  ·  [Zur Anzeige]({app['url']})" if app["url"] else "")
    )
    st.progress(done_n / len(steps))
    st.caption(" → ".join(("✅ " if ok else "⬜ ") + label for _, label, ok in steps))
    if next_step:
        st.info(f"**Nächster Schritt:** {next_step}")
    elif app["status"] not in ("beworben", "Gespräch", "Zusage", "Absage"):
        st.success("Alle Schritte erledigt – unten kannst du die Bewerbung abschliessen.")

    with st.expander("Stellenbeschreibung"):
        desc = st.text_area("Text", app["description"] or "", height=300, key=f"desc_{app_id}",
                            label_visibility="collapsed")
        if desc != (app["description"] or ""):
            db.update_application(app_id, description=desc)
            app["description"] = desc

    # 1. Analyse
    st.subheader("1. Passt die Stelle zu mir?")
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
    st.caption("Adresse, Ausbildung und Weiterbildung bleiben fix. Unten siehst du alle Aufgaben aus dem Profil – "
               "die KI markiert passende als **Vorschlag**. Du entscheidest per Checkbox.")
    suggest_key = f"aufgaben_vorschlaege_{app_id}"
    desc_hash = abs(hash((app.get("description") or "")[:2000])) % 10**8

    s1, s2 = st.columns(2)
    # Kein Auto-LLM beim Öffnen – nur auf Klick (spart Zeit und Kosten)
    sug_label = "Vorschlag aktualisieren" if suggest_key in st.session_state else "KI-Vorschlag holen"
    if s1.button(sug_label, disabled=not can_generate, key=f"sug_{app_id}_{desc_hash}"):
        with st.spinner("KI schlägt passende Aufgaben vor ..."):
            try:
                st.session_state[suggest_key] = suggest_aufgaben(S.profile, app["description"], analysis)
                st.rerun()
            except Exception as e:
                st.error(f"Vorschlag fehlgeschlagen: {e}")
    if s2.button("Allgemeine Auswahl laden", key=f"load_sel_{app_id}",
                 help="Übernimmt die Checkbox-Auswahl aus „Mein Lebenslauf“."):
        st.session_state.pop(suggest_key, None)
        st.session_state[f"use_general_{app_id}"] = True
        st.rerun()

    suggestions = st.session_state.get(suggest_key) or {}
    suggested_texts: dict[int, dict[str, dict]] = {}
    for block in suggestions.get("vorschlaege") or []:
        idx = block.get("stellen_index")
        if not isinstance(idx, int):
            continue
        suggested_texts[idx] = {
            str(item.get("text") or "").strip(): item for item in block.get("aufgaben") or []
        }
    if suggestions.get("zusammenfassung"):
        st.info(f"**Vorschlag der KI:** {suggestions['zusammenfassung']}")

    gewaehlt: list[dict] = []
    general = cv_builder.load_selection(S.profile) if st.session_state.get(f"use_general_{app_id}") else None
    for s in cv_builder.stellen_aufgaben(S.profile):
        idx = s["index"]
        sug = suggested_texts.get(idx, {})
        zeit = f"{s['von']} – {s['bis'] or 'heute'}"
        with st.expander(f"{s['position']} · {s['firma']} ({zeit})", expanded=bool(sug) or idx < 2):
            for kind, items in (("erfolge", s["erfolge"]), ("aufgaben", s["aufgaben"])):
                for j, item in enumerate(items):
                    text = item["text"]
                    meta = sug.get(text)
                    q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                    default = True if meta else (
                        j in (general or {}).get(kind, {}).get(str(idx), []) if general else False
                    )
                    badge = ""
                    if meta:
                        badge = f" · **Vorschlag** (Passung {meta.get('passung', '–')}/10)"
                        why = meta.get("warum") or ""
                    else:
                        why = ""
                    label = f"{text}" + (f"  · `{q}`" if q else "") + badge
                    if why:
                        label += f"  \n:gray[{why}]"
                    if st.checkbox(label, value=default, key=f"task_{app_id}_{kind}_{idx}_{j}_{desc_hash}"):
                        gewaehlt.append({"stellen_index": idx, "stelle": s["position"],
                                         "firma": s["firma"], "text": text})
    st.caption(f"**{len(gewaehlt)}** Aufgabe(n)/Erfolg(e) ausgewählt.")

    cv_label = "Neuen Lebenslauf erstellen" if app["cv_json"] else "Lebenslauf aus Auswahl erstellen"
    if st.button(cv_label, type="primary" if not app["cv_json"] else "secondary",
                 disabled=not can_generate, key=f"cv_{app_id}"):
        with st.spinner("Lebenslauf wird erstellt ..."):
            try:
                cv = tailor_cv(S.profile, app["description"], analysis, hinweise, gewaehlt or None)
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
            r1, r2 = st.columns(2)
            if r1.button(f"Im Design „{CV_TEMPLATES[S.CV_TEMPLATE]['name']}“ neu gestalten",
                         key=f"restyle_{app_id}", width="stretch",
                         help="Design wählst du im Reiter „Mein Lebenslauf“. Der Inhalt bleibt gleich."):
                styled_cv(cv, out_dir, Path(app["cv_pdf"]).name)
                st.rerun()
            if r2.button("Auf Englisch übersetzen", key=f"cv_en_{app_id}", width="stretch",
                         disabled=not S.LLM_OK,
                         help="Erstellt eine englische Version dieses Lebenslaufs (PDF + Word)."):
                with st.spinner("KI übersetzt den Lebenslauf ..."):
                    try:
                        en = translate_cv(cv)
                        pdf = styled_cv(en, out_dir, safe_filename("CV", S.NAME, company, "EN") + ".pdf")
                        st.session_state[f"cv_en_{app_id}"] = {"json": en, "pdf": str(pdf)}
                        st.rerun()
                    except Exception as e:
                        st.error(f"Übersetzung fehlgeschlagen: {e}")
            with st.expander("PDF-Vorschau", expanded=False):
                show_pdf_preview(app["cv_pdf"])
            if en_state := st.session_state.get(f"cv_en_{app_id}"):
                st.success("Englische Version bereit")
                with st.expander("PDF-Vorschau (EN)", expanded=False):
                    show_pdf_preview(en_state["pdf"])
                download("CV (English, PDF)", en_state["pdf"], f"dl_cv_en_{app_id}")
                download("CV (English, Word)", str(Path(en_state["pdf"]).with_suffix(".docx")),
                         f"dl_cv_en_docx_{app_id}")
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
                pdf = styled_letter(data, out_dir, safe_filename("Bewerbungsschreiben", S.NAME, company) + ".pdf")
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
            c_cap, c_design = st.columns([2, 3])
            c_cap.caption("Vorschau")
            if c_design.button("Im aktuellen Design neu gestalten", key=f"restyle_letter_{app_id}", width="stretch",
                               help="Farbe und Schrift wie beim Lebenslauf (Reiter „Mein Lebenslauf“)."):
                styled_letter(build_letter_data(S.profile, letter, recipient.splitlines()), out_dir,
                              Path(app["letter_pdf"]).name)
                st.rerun()
            with st.expander("PDF-Vorschau", expanded=False):
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
                    pdf = styled_letter(data, out_dir, Path(app["letter_pdf"]).name)
                    db.update_application(app_id, letter_json=json.dumps(letter, ensure_ascii=False),
                                          letter_pdf=str(pdf))
                    st.rerun()

    cv = json.loads(app["cv_json"]) if app["cv_json"] else None
    letter = json.loads(app["letter_json"]) if app["letter_json"] else None
    if cv or letter:
        render_checks(app, analysis, cv, letter)

    # 4. Dossier
    if app["cv_pdf"] and app["letter_pdf"]:
        st.subheader("4. Bewerbungsdossier (ein PDF)")
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
                st.rerun()
            except Exception as e:
                st.error(f"Dossier fehlgeschlagen: {e}")
    else:
        selected = []

    # 5. Speichern + Abschliessen
    style = {"template": S.CV_TEMPLATE, "accent": S.CV_ACCENT, "options": S.CV_OPTIONS}
    cv_docx = letter_docx = None
    if cv and app["cv_pdf"]:
        cv_docx = Path(app["cv_pdf"]).with_suffix(".docx")
        if not cv_docx.exists():
            word.save_cv_docx(cv, cv_docx, **style)
    if letter and app["letter_pdf"]:
        letter_docx = Path(app["letter_pdf"]).with_suffix(".docx")
        if not letter_docx.exists():
            word.save_letter_docx(build_letter_data(S.profile, letter, recipient.splitlines()), letter_docx, **style)
    files = {
        "Lebenslauf": app["cv_pdf"],
        "Lebenslauf (Word)": str(cv_docx) if cv_docx else None,
        "Bewerbungsschreiben": app["letter_pdf"],
        "Bewerbungsschreiben (Word)": str(letter_docx) if letter_docx else None,
        "Bewerbungsdossier": str(dossier_path),
    }
    files = {label: Path(p) for label, p in files.items() if p and Path(p).exists()}
    if files:
        st.subheader("5. Speichern")
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

        can_finish = bool(app.get("cv_pdf") and app.get("letter_pdf") and Path(app["cv_pdf"]).exists()
                          and Path(app["letter_pdf"]).exists())
        st.markdown("#### Bewerbung abschliessen")
        st.caption("Erstellt ggf. das Dossier, speichert alle Dateien und setzt den Status auf «beworben».")
        if st.button("Bewerbung abschliessen", type="primary", key=f"finish_{app_id}",
                     disabled=not can_finish, width="stretch"):
            try:
                if not dossier_path.exists():
                    atts = [Path(p) for p in (selected or [str(p) for p in documents.dossier_attachments()])]
                    documents.build_dossier([Path(app["letter_pdf"]), Path(app["cv_pdf"]), *atts], dossier_path)
                # Dateiliste nach Dossier aktualisieren
                files["Bewerbungsdossier"] = dossier_path
                copied = settings.copy_files(list(files.values()), target)
                db.update_application(app_id, status="beworben")
                st.session_state[f"saved_{app_id}"] = str(target)
                st.session_state["notice"] = (
                    f"Bewerbung abgeschlossen: {len(copied)} Datei(en) in «{target}», Status «beworben»."
                )
                st.rerun()
            except Exception as e:
                st.error(f"Abschliessen fehlgeschlagen: {e}")

    render_interview(app, analysis)


STATUS_ICONS = {"unverändert": "⚪", "umformuliert": "🔵", "neu formuliert": "🟠"}


def render_checks(app: dict, analysis: dict | None, cv: dict | None, letter: dict | None) -> None:
    app_id = app["id"]
    st.subheader("3. Unterlagen prüfen")
    t_changes, t_keywords, t_facts = st.tabs(["Was hat die KI geändert?", "Stichwort-Abgleich", "Faktencheck"])

    with t_changes:
        if not cv:
            st.caption("Erstelle zuerst den Lebenslauf.")
        else:
            changes = review.cv_changes(S.profile, cv)
            st.caption("Links steht, was in deinem Profil steht, rechts die Version für diese Stelle. "
                       "⚪ unverändert · 🔵 umformuliert · 🟠 neu formuliert – 🟠 bitte besonders genau prüfen.")
            k1, k2 = st.columns(2)
            k1.markdown("**Kurzprofil – bisher**")
            k1.write(changes["kurzprofil_alt"] or "–")
            k2.markdown("**Kurzprofil – für diese Stelle**")
            k2.write(changes["kurzprofil_neu"] or "–")
            for pos in changes["positionen"]:
                counts = {s: sum(b["status"] == s for b in pos["neu"]) for s in STATUS_ICONS}
                flag = f"  ·  🟠 {counts['neu formuliert']}" if counts["neu formuliert"] else ""
                with st.expander(f"{pos['titel']} – {pos['untertitel']}{flag}"):
                    p1, p2 = st.columns(2)
                    p1.markdown("**Im Profil**" + ("".join(f"\n- {x}" for x in pos["original"]) or "\n- –"))
                    p2.markdown("**Im Lebenslauf**" + ("".join(f"\n- {STATUS_ICONS[b['status']]} {b['text']}"
                                                               for b in pos["neu"]) or "\n- –"))
            if changes["weggelassene_kenntnisse"]:
                st.caption("Für diese Stelle weggelassene Kenntnisse: " + ", ".join(changes["weggelassene_kenntnisse"]))

    with t_keywords:
        keywords = (analysis or {}).get("keywords") or []
        if not keywords:
            st.caption("Keine Begriffe aus der Anzeige vorhanden – bitte oben „Neu analysieren“.")
        else:
            cov = review.keyword_coverage(keywords, cv, letter, S.profile)
            m1, m2 = st.columns([1, 4])
            m1.metric("Abdeckung", f"{cov['prozent']} %")
            box = m2.success if cov["prozent"] >= 75 else m2.warning if cov["prozent"] >= 50 else m2.error
            box("Viele Firmen filtern Bewerbungen zuerst automatisch nach diesen Begriffen aus dem Inserat. "
                "Ab etwa 75 % bist du gut aufgestellt.")
            st.markdown("**✅ Vorhanden:** " + (", ".join(cov["gefunden"]) or "–"))
            if cov["im_profil"]:
                st.warning("**Steht in deinem Profil, fehlt aber in den Unterlagen:** " + ", ".join(cov["im_profil"])
                           + "  \nTipp: Schreibe diese Begriffe in „Zusätzliche Hinweise für die KI“ und erstelle "
                             "den Lebenslauf neu.")
            if cov["fehlt"]:
                st.info("**Kommt in deinem Profil nicht vor:** " + ", ".join(cov["fehlt"])
                        + "  \nNur ergänzen, wenn du es wirklich kannst (z.B. unter „Ergänzungen & Wünsche“).")

    with t_facts:
        st.caption("Die KI prüft jede Aussage in Lebenslauf und Bewerbungsschreiben gegen dein Profil und meldet "
                   "Erfundenes oder Übertriebenes. So kannst du im Gespräch alles belegen.")
        saved = json.loads(app["review_json"]) if app.get("review_json") else None
        current_hash = str(abs(hash((app["cv_json"] or "") + (app["letter_json"] or ""))) % 10**10)
        if saved and saved.get("hash") != current_hash:
            st.caption("Die Unterlagen wurden seit dem letzten Faktencheck geändert.")
        if st.button("Faktencheck starten" if not saved else "Faktencheck wiederholen", key=f"factcheck_{app_id}",
                     disabled=not S.LLM_OK, type="primary" if not saved else "secondary"):
            with st.spinner("KI prüft alle Aussagen ..."):
                try:
                    result = review.fact_check(S.profile, cv, letter)
                    db.update_application(app_id, review_json=json.dumps({**result, "hash": current_hash},
                                                                         ensure_ascii=False))
                    st.rerun()
                except Exception as e:
                    st.error(f"Faktencheck fehlgeschlagen: {e}")
        if saved:
            problems = saved.get("probleme") or []
            (st.success if not problems else st.warning)(saved.get("fazit", ""))
            for p in problems:
                with st.container(border=True):
                    st.markdown(f"**{p.get('dokument', '')}:** „{p.get('aussage', '')}“")
                    st.markdown(f"⚠ {p.get('problem', '')}")
                    if p.get("vorschlag"):
                        st.markdown(f"✏️ Besser: {p['vorschlag']}")
            if problems:
                st.caption("Ändere die Stellen oben in den Bearbeitungsfeldern von Lebenslauf bzw. Schreiben.")


def render_interview(app: dict, analysis: dict | None) -> None:
    app_id = app["id"]
    st.subheader("6. Vorstellungsgespräch vorbereiten")
    prep = json.loads(app["interview_json"]) if app.get("interview_json") else None
    t_prep, t_practice = st.tabs(["Fragen & Antworten", "Übungsgespräch"])

    with t_prep:
        if st.button("Neu vorbereiten" if prep else "Vorbereitung erstellen", key=f"prep_{app_id}",
                     disabled=not (S.LLM_OK and app["description"]), type="secondary" if prep else "primary"):
            with st.spinner("KI bereitet dich auf das Gespräch vor ..."):
                try:
                    result = interview.prepare(S.profile, app, analysis)
                    db.update_application(app_id, interview_json=json.dumps(result, ensure_ascii=False))
                    st.rerun()
                except Exception as e:
                    st.error(f"Vorbereitung fehlgeschlagen: {e}")
        if prep:
            st.info(prep.get("einschaetzung", ""))
            for i, q in enumerate(prep.get("fragen", []), start=1):
                with st.expander(f"{i}. {q.get('frage', '')}  ·  {q.get('kategorie', '')}"):
                    st.markdown(f"**Warum diese Frage:** {q.get('warum', '')}")
                    st.markdown(f"**So antwortest du gut:** {q.get('tipp', '')}")
                    if q.get("beispiel"):
                        st.success(f"**Beispiel aus deinem Lebenslauf:** {q['beispiel']}")
            if prep.get("stolpersteine"):
                st.markdown("**Heikle Punkte – und wie du sie ansprichst**")
                for s in prep["stolpersteine"]:
                    st.warning(f"**{s.get('thema', '')}:** {s.get('antwort', '')}")
            c1, c2 = st.columns(2)
            c1.markdown("**Deine Fragen an die Firma**" + "".join(f"\n- {x}" for x in prep.get("eigene_fragen", [])))
            c2.markdown("**Vor dem Gespräch erledigen**" + "".join(f"\n- {x}" for x in prep.get("vorbereitung", [])))

    with t_practice:
        key = f"practice_{app_id}"
        messages = st.session_state.setdefault(key, [])
        st.caption("Die KI spielt die Personalverantwortliche, stellt Fragen und gibt dir nach jeder Antwort "
                   "kurzes Feedback.")
        if not messages:
            if st.button("Übungsgespräch starten", type="primary", key=f"start_{app_id}", disabled=not S.LLM_OK):
                with st.spinner("Die Personalverantwortliche kommt ..."):
                    try:
                        messages.append({"role": "assistant", "content": interview.interviewer(S.profile, app, [])})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Start fehlgeschlagen: {e}")
            return
        for m in messages:
            with st.chat_message("assistant" if m["role"] == "assistant" else "user"):
                st.markdown(m["content"])
        with st.form(f"answer_{app_id}_{len(messages)}", clear_on_submit=True):
            answer = st.text_area("Deine Antwort", height=120)
            a1, a2, a3 = st.columns(3)
            send = a1.form_submit_button("Antworten", type="primary", width="stretch")
            finish = a2.form_submit_button("Gespräch beenden & auswerten", width="stretch")
            reset = a3.form_submit_button("Neu beginnen", width="stretch")
        if reset:
            st.session_state[key] = []
            st.rerun()
        if (send and answer.strip()) or finish:
            with st.spinner("..."):
                try:
                    if send:
                        messages.append({"role": "user", "content": answer.strip()})
                        messages.append({"role": "assistant",
                                         "content": interview.interviewer(S.profile, app, messages)})
                    else:
                        messages.append({"role": "assistant", "content": "**Auswertung**\n\n"
                                         + interview.summarize_interview(S.profile, app, messages)})
                    st.rerun()
                except Exception as e:
                    st.error(f"Das hat nicht geklappt: {e}")
