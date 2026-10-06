
import pandas as pd
import streamlit as st
import yaml

from src import documents, photo
from src.config import OUTPUT_DIR
from src.generate import base_cv_data
from src.profile import load_profile_text, save_generated_profile, save_profile_text
from ui import state as S
from ui.helpers import _text, show_documents_overview, show_pdf_preview, styled_cv


def render() -> None:
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
                    saved = documents.save_upload(kat, f.name, f.getvalue())
                    if kat == "lebenslauf" and not photo.list_versions():
                        if found := documents.extract_images(saved):
                            photo.save_original(found[0])
                            st.session_state["notice"] = ("Das Foto aus deinem Lebenslauf wurde in den Reiter "
                                                          "„Bewerbungsfoto“ übernommen.")
                    if S.LLM_OK:
                        with st.spinner(f"KI erstellt einen Steckbrief zu {f.name} ..."):
                            try:
                                documents.summarize_document(saved)
                            except Exception:
                                pass  # Steckbrief kann später über die Übersicht nachgeholt werden
                st.session_state.upload_round += 1
                st.rerun()
            count = len(documents.list_documents(kat))
            st.caption(f"{count} Dokument(e) hochgeladen" if count else "Noch nichts hochgeladen")

    show_documents_overview()

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
        st.success(f"Profil vorhanden: **{S.NAME}**. Nach neuen Unterlagen oder Ergänzungen einfach neu erstellen.")
    else:
        st.info("Noch kein eigenes Profil. Lade mindestens deinen Lebenslauf hoch und klicke dann auf „Profil erstellen“.")

    p1, p2 = st.columns(2)
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
    if p2.button("Lebenslauf von KI analysieren lassen", width="stretch",
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
        st.info("Deinen fertigen Lebenslauf (Vorschau, Design wählen, Download) findest du im Reiter "
                "**„Mein Lebenslauf“** oben.")

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
            if st.button(f"Ausgewählte Punkte von KI umsetzen ({len(gewaehlt)})", type="primary",
                         disabled=not (S.LLM_OK and (gewaehlt or eigene.strip()))):
                with st.status("KI verbessert deinen Lebenslauf ...", expanded=True) as status:
                    try:
                        proposal = documents.improve_profile(S.profile, gewaehlt, eigene)
                        st.write("Vorschau wird erstellt ...")
                        pdf = styled_cv(base_cv_data(proposal["profil"]), OUTPUT_DIR / "basis",
                                        "Lebenslauf_Vorschlag.pdf")
                        st.session_state["profile_proposal"] = {**proposal, "pdf": str(pdf)}
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

    if proposal := st.session_state.get("profile_proposal"):
        st.subheader("Vorschlag: dein verbesserter Lebenslauf")
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
