
import pandas as pd
import streamlit as st
import yaml

from src import documents, photo
from src.config import OUTPUT_DIR
from src.generate import base_cv_data
from src.profile import load_profile_text, save_generated_profile, save_profile_text
from ui import state as S
from ui import zeugnisse as zeugnis_analyse
from ui.helpers import _text, download, show_documents_overview, show_pdf_preview, styled_cv


def _auto_build_profile() -> None:
    """Erstellt nach dem Upload automatisch das Profil inkl. Aufgaben aus CV und Zeugnissen."""
    with st.status("Profil wird automatisch aus deinen Unterlagen erstellt ...", expanded=True) as status:
        try:
            st.write("Dokumente werden ausgewertet ...")
            profile = documents.profile_from_documents(on_progress=st.write)
            save_generated_profile(profile)
            if documents.active_documents("zeugnisse"):
                st.write("Aufgaben aus Arbeitszeugnissen werden den Stellen zugeordnet ...")
                profile, notes = documents.enrich_aufgaben(profile, on_progress=st.write)
                save_generated_profile(profile)
                extra = (" " + " ".join(notes)) if notes else ""
            else:
                extra = ""
            status.update(label="Profil erstellt", state="complete")
            n = sum(len(e.get("aufgaben") or []) for e in (profile.get("berufserfahrung") or []))
            st.session_state["notice"] = (
                f"Profil automatisch erstellt: {len(profile.get('berufserfahrung') or [])} Stellen, "
                f"{n} Aufgaben. Im Reiter „Mein Lebenslauf“ kannst du per Checkbox wählen, "
                f"was in den Lebenslauf soll.{extra}"
            )
        except Exception as e:
            status.update(label="Profil konnte nicht automatisch erstellt werden", state="error")
            st.error(f"{e} – Du kannst es unten manuell erstellen.")


def render() -> None:
    st.caption("Lade deinen Lebenslauf und deine Arbeitszeugnisse hoch. "
               "Danach erstellt die KI automatisch dein Profil und ordnet die Aufgaben jeder Stelle zu "
               "(aus Lebenslauf und Zeugnissen). Im Reiter „Mein Lebenslauf“ wählst du per Checkbox, "
               "was in den Lebenslauf soll.")
    uploaded_any = False
    for col, (kat, label) in zip(st.columns(3), documents.KATEGORIEN.items()):
        with col:
            st.markdown(f"**{label}**")
            files = st.file_uploader(label, type=documents.UPLOAD_TYPES, accept_multiple_files=True,
                                     key=f"up_{kat}_{st.session_state.upload_round}",
                                     label_visibility="collapsed")
            if files:
                uploaded_any = True
                for f in files:
                    saved = documents.save_upload(kat, f.name, f.getvalue())
                    if kat == "lebenslauf" and not photo.list_versions():
                        if found := documents.extract_images(saved):
                            photo.save_original(found[0])
                    if S.LLM_OK:
                        with st.spinner(f"KI erstellt einen Steckbrief zu {f.name} ..."):
                            try:
                                documents.summarize_document(saved)
                            except Exception:
                                pass
            count = len(documents.list_documents(kat))
            st.caption(f"{count} Dokument(e) hochgeladen" if count else "Noch nichts hochgeladen")

    if uploaded_any:
        if S.LLM_OK and documents.active_documents("lebenslauf"):
            st.session_state["auto_profile_after_upload"] = True
        st.session_state.upload_round += 1
        st.rerun()

    if st.session_state.pop("auto_profile_after_upload", False) and S.LLM_OK:
        _auto_build_profile()
        st.rerun()

    show_documents_overview()
    zeugnis_analyse.render()

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
    if S.PROFILE_READY:
        n_exp = len(S.profile.get("berufserfahrung") or [])
        n_tasks = sum(len(e.get("aufgaben") or []) for e in (S.profile.get("berufserfahrung") or []))
        st.success(f"Profil vorhanden: **{S.NAME}** · {n_exp} Stellen · {n_tasks} Aufgaben. "
                   "Nach neuen Unterlagen wird es automatisch neu erstellt – oder unten manuell.")
    else:
        st.info("Noch kein Profil. Lade mindestens deinen Lebenslauf hoch – das Profil wird automatisch erstellt.")

    p1, p2, p3 = st.columns(3)
    if p1.button("Profil aus meinen Unterlagen erstellen", type="primary", width="stretch",
                 disabled=not (S.LLM_OK and documents.has_documents())):
        with st.status("Unterlagen werden ausgewertet ...", expanded=True) as status:
            try:
                save_generated_profile(documents.profile_from_documents(on_progress=st.write))
                status.update(label="Profil erstellt", state="complete")
                st.session_state["notice"] = "Dein Profil wurde erstellt. Bitte kurz unten prüfen."
                st.rerun()
            except Exception as e:
                status.update(label="Fehler", state="error")
                st.error(f"Profil konnte nicht erstellt werden: {e}")
    if p2.button("Alle Aufgaben aus Zeugnissen ergänzen", width="stretch",
                 disabled=not (S.LLM_OK and S.PROFILE_READY and documents.has_documents()),
                 help="Liest Lebenslauf und Zeugnisse nochmals und füllt pro Stelle möglichst alle Tätigkeiten."):
        with st.status("Aufgaben werden ergänzt ...", expanded=True) as status:
            try:
                updated, notes = documents.enrich_aufgaben(S.profile, on_progress=st.write)
                save_generated_profile(updated)
                status.update(label="Aufgaben ergänzt", state="complete")
                st.session_state["notice"] = ("Aufgabenkatalog aktualisiert. "
                                             + (" ".join(notes) if notes else "Bitte unten prüfen."))
                st.rerun()
            except Exception as e:
                status.update(label="Fehler", state="error")
                st.error(f"Ergänzen fehlgeschlagen: {e}")
    if p3.button("Lebenslauf von KI analysieren lassen", width="stretch",
                 disabled=not (S.LLM_OK and S.PROFILE_READY)):
        with st.status("Lebenslauf wird analysiert ...", expanded=True) as status:
            try:
                documents.analyze_cv(S.profile, on_progress=st.write)
                status.update(label="Analyse fertig", state="complete")
                st.rerun()
            except Exception as e:
                status.update(label="Fehler", state="error")
                st.error(f"Analyse fehlgeschlagen: {e}")

    if S.PROFILE_READY:
        st.info("Lebenslauf per Checkbox zusammenstellen: Reiter **„Mein Lebenslauf“**.")

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
            st.markdown("**Verbesserungsvorschläge** – hake an, was die KI in deinem Lebenslauf umsetzen soll. "
                        "Den Text kannst du direkt in der Tabelle ändern oder unten eigene Zeilen hinzufügen.")
            vorschlaege = pd.DataFrame([
                {"Umsetzen": False, "Bereich": v.get("bereich", ""), "Vorschlag": v.get("vorschlag", ""),
                 "Beispiel": v.get("beispiel", "")}
                for v in cv_analysis["verbesserungen"]
            ])
            auswahl = st.data_editor(
                vorschlaege,
                hide_index=True,
                width="stretch",
                num_rows="dynamic",
                key=f"improve_{cv_analysis.get('erstellt', '')}",
                column_config={
                    "Umsetzen": st.column_config.CheckboxColumn("Umsetzen", default=True, width="small"),
                    "Bereich": st.column_config.TextColumn("Bereich", width="small"),
                    "Vorschlag": st.column_config.TextColumn("Vorschlag", width="large"),
                    "Beispiel": st.column_config.TextColumn("Beispiel-Formulierung", width="large"),
                },
            )
            eigene = st.text_area("Eigene Anweisung (optional)", key="improve_extra",
                                  placeholder="z.B. Kurzprofil stärker auf Einkauf ausrichten, Stichpunkte kürzer")
            gewaehlt = []
            for row in auswahl.to_dict("records"):
                if row.get("Umsetzen") != True:  # neue, leere Zeilen liefern NaN statt False
                    continue
                bereich, vorschlag, beispiel = (_text(row.get(k)) for k in ("Bereich", "Vorschlag", "Beispiel"))
                if vorschlag:
                    gewaehlt.append(f"{bereich + ': ' if bereich else ''}{vorschlag}"
                                    + (f" (Beispiel: {beispiel})" if beispiel else ""))
            from src import cv_original

            original_docx = cv_original.original_cv_docx()
            mode_help = (
                "«Original-Word»: KI ändert nur Texte in deiner hochgeladenen .docx – Layout bleibt. "
                "«Tool-Design»: neuer Lebenslauf im Design dieses Tools (Format ändert sich)."
            )
            if original_docx:
                improve_mode = st.radio(
                    "Wie umsetzen?",
                    ["Original-Word behalten (Layout bleibt)", "Im Tool-Design neu erzeugen"],
                    horizontal=True,
                    key="improve_mode",
                    help=mode_help,
                )
                st.caption(f"Original: `{original_docx.name}`")
            else:
                improve_mode = "Im Tool-Design neu erzeugen"
                if cv_original.original_cv_pdf_only():
                    st.warning("Dein Lebenslauf ist nur als **PDF** hochgeladen. "
                               "Layout-erhaltende KI-Änderungen gehen nur mit **Word (.docx)**. "
                               "Lade die Word-Version hoch – oder nutze das Tool-Design (neues Format).")
                else:
                    st.caption("Kein Word-Lebenslauf gefunden → Umsetzung im Tool-Design.")

            if st.button(f"Ausgewählte Punkte von KI umsetzen ({len(gewaehlt)})", type="primary",
                         disabled=not (S.LLM_OK and (gewaehlt or eigene.strip()))):
                with st.status("KI verbessert deinen Lebenslauf ...", expanded=True) as status:
                    try:
                        if improve_mode.startswith("Original-Word") and original_docx:
                            st.write("Texte im Original-Word werden angepasst (Layout bleibt) ...")
                            patched = cv_original.improve_original_docx(original_docx, gewaehlt, eigene)
                            st.session_state["original_cv_proposal"] = patched
                            st.session_state.pop("profile_proposal", None)
                            status.update(label="Word-Vorschlag fertig", state="complete")
                        else:
                            proposal = documents.improve_profile(S.profile, gewaehlt, eigene)
                            st.write("Vorschau im Tool-Design wird erstellt ...")
                            pdf = styled_cv(base_cv_data(proposal["profil"]), OUTPUT_DIR / "basis",
                                            "Lebenslauf_Vorschlag.pdf")
                            st.session_state["profile_proposal"] = {**proposal, "pdf": str(pdf)}
                            st.session_state.pop("original_cv_proposal", None)
                            status.update(label="Vorschlag fertig", state="complete")
                        st.rerun()
                    except Exception as e:
                        status.update(label="Fehler", state="error")
                        st.error(f"Umsetzen fehlgeschlagen: {e}")
        b1, b2 = st.columns(2)
        if cv_analysis.get("passende_berufe"):
            b1.markdown("**Passende Berufe**" + "".join(f"\n- {x}" for x in cv_analysis["passende_berufe"]))
        if cv_analysis.get("suchbegriffe"):
            b2.markdown("**Suchbegriffe für Jobportale**" + "".join(f"\n- {x}" for x in cv_analysis["suchbegriffe"]))
        st.caption("Tipp: Was dir an Angaben fehlt, kannst du oben unter „Ergänzungen & Wünsche“ eintragen "
                   "und dann das Profil neu erstellen.")

    if orig := st.session_state.get("original_cv_proposal"):
        st.subheader("Vorschlag: Original-Word angepasst")
        st.success("Layout deiner Word-Datei bleibt erhalten – nur ausgewählte Texte wurden geändert.")
        st.markdown("**Änderungen**" + "".join(f"\n- {x}" for x in (orig.get("zusammenfassung") or [])))
        if orig.get("offene_fragen"):
            st.warning("**Offene Fragen:**" + "".join(f"\n- {x}" for x in orig["offene_fragen"]))
        download("Verbesserter Lebenslauf (Word)", orig["docx"], "dl_orig_cv_proposal")
        o1, o2, o3 = st.columns(3)
        if o1.button("Als neuen Lebenslauf speichern", type="primary", width="stretch",
                     help="Kopiert die angepasste Word-Datei zu deinen Unterlagen."):
            from pathlib import Path as _Path
            data = _Path(orig["docx"]).read_bytes()
            saved = documents.save_upload("lebenslauf", _Path(orig["docx"]).name, data)
            documents.add_applied_improvements(orig.get("punkte", []))
            st.session_state.pop("original_cv_proposal")
            st.session_state["notice"] = (
                f"Gespeichert als «{saved.name}» (Layout wie Original). "
                "Optional: danach «Profil aus meinen Unterlagen erstellen», damit das Profil dazu passt."
            )
            st.rerun()
        if o2.button("Nur herunterladen & behalten", width="stretch"):
            documents.add_applied_improvements(orig.get("punkte", []))
            st.info("Datei oben per Download speichern. Vorschlag bleibt sichtbar.")
        if o3.button("Verwerfen", width="stretch", key="orig_discard"):
            st.session_state.pop("original_cv_proposal")
            st.rerun()

    if proposal := st.session_state.get("profile_proposal"):
        st.subheader("Vorschlag: dein verbesserter Lebenslauf (Tool-Design)")
        st.caption("Hinweis: Das ist ein neues Layout dieses Tools – nicht das Format deiner Originaldatei.")
        prev_col, info_col = st.columns(2)
        with prev_col:
            st.caption("Vorschau (allgemeiner Lebenslauf, noch nicht übernommen)")
            show_pdf_preview(proposal["pdf"])
        with info_col:
            st.markdown("**Was die KI geändert hat**"
                        + "".join(f"\n- {x}" for x in proposal.get("aenderungen", [])))
            if proposal.get("offene_fragen"):
                st.warning("**Dafür braucht die KI noch Infos von dir:**"
                           + "".join(f"\n- {x}" for x in proposal["offene_fragen"]))
                st.caption("Beantworte die Fragen oben im Feld „Ergänzungen & Wünsche“ und erstelle danach "
                           "das Profil neu.")
            c_ok, c_no = st.columns(2)
            if c_ok.button("Übernehmen", type="primary", width="stretch"):
                save_generated_profile(proposal["profil"])
                documents.add_applied_improvements(proposal.get("punkte", []))
                st.session_state.pop("profile_proposal")
                st.session_state["notice"] = ("Verbesserungen übernommen. Alle neuen Lebensläufe und "
                                              "Bewerbungsschreiben basieren jetzt darauf.")
                st.rerun()
            if c_no.button("Verwerfen", width="stretch"):
                st.session_state.pop("profile_proposal")
                st.rerun()

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
