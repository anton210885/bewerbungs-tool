import json
from pathlib import Path

import streamlit as st

from src import documents, settings, word
from src.generate import (
    CV_FONTS,
    CV_PHOTO_SIZES,
    CV_SECTIONS,
    CV_SIZES,
    CV_SPACING,
    CV_TEMPLATES,
    DEFAULT_CV_OPTIONS,
    base_cv_data,
    design_from_wish,
    safe_filename,
)
from ui import state as S
from ui.helpers import DOCX_MIME, _photo_stamp, template_preview


def render() -> None:
    if not S.PROFILE_READY:
        st.info("Erstelle zuerst im Reiter „1. Meine Unterlagen“ dein Profil – danach siehst du hier deinen Lebenslauf.")
    else:
        base_data = base_cv_data(S.profile)
        base_json = json.dumps(base_data, ensure_ascii=False, sort_keys=True)
        stamp = _photo_stamp(base_data)
        options_json = json.dumps(S.CV_OPTIONS, sort_keys=True)
        thumb_json = json.dumps({**S.CV_OPTIONS, "max_seiten": 0}, sort_keys=True)
        wkey = abs(hash((S.CV_TEMPLATE, S.CV_ACCENT, options_json))) % 10**8

        st.markdown("**1. Design wählen** – alle Vorlagen zeigen bereits deine eigenen Daten. "
                    "Design und Gestaltung gelten auch für alle Lebensläufe, die für einzelne Stellen "
                    "erstellt werden.")
        for row_start in range(0, len(CV_TEMPLATES), 3):
            cols = st.columns(3)
            for col, key in zip(cols, list(CV_TEMPLATES)[row_start:row_start + 3]):
                tpl = CV_TEMPLATES[key]
                with col, st.container(border=True):
                    try:
                        thumbs = template_preview(key, tpl["farbe"], base_json, 45, stamp, thumb_json)[1]
                        st.image(thumbs[0], width="stretch")
                    except Exception as e:
                        st.error(f"Vorschau fehlgeschlagen: {e}")
                    active = key == S.CV_TEMPLATE
                    if st.button(("✓ " if active else "") + tpl["name"], key=f"tpl_{key}", width="stretch",
                                 type="primary" if active else "secondary"):
                        settings.set_cv_style(key)
                        st.rerun()

        st.divider()
        st.markdown("**2. Gestalten** – beschreibe deine Wünsche in eigenen Worten oder stelle sie unten "
                    "direkt ein. Jede Änderung siehst du sofort in der Vorschau.")
        with st.container(border=True):
            wish = st.text_area(
                "Design-Wünsche in eigenen Worten",
                settings.load().get("design_wunsch", ""),
                height=90,
                placeholder="z.B. Maximal 2 Seiten. Keine Lücke zwischen meinem Namen und den persönlichen "
                            "Daten. Foto etwas kleiner, Farbe dunkelgrün, insgesamt kompakter.",
            )
            if st.button("Wünsche von KI umsetzen", type="primary", disabled=not (S.LLM_OK and wish.strip())):
                with st.spinner("KI setzt deine Design-Wünsche um ..."):
                    try:
                        result = design_from_wish(wish, S.CV_TEMPLATE, S.CV_ACCENT, S.CV_OPTIONS)
                        stored = settings.load()
                        stored["design_wunsch"] = wish
                        settings.save(stored)
                        if result["vorlage"] or result["akzent"]:
                            settings.set_cv_style(result["vorlage"] or S.CV_TEMPLATE,
                                                  result["akzent"] or (None if result["vorlage"] else S.CV_ACCENT))
                        settings.set_cv_options({**S.CV_OPTIONS, **result["optionen"]})
                        st.session_state["design_result"] = result
                        st.rerun()
                    except Exception as e:
                        st.error(f"Umsetzen fehlgeschlagen: {e}")
            if design_result := st.session_state.get("design_result"):
                if design_result["erklaerung"]:
                    st.success("**Umgesetzt:**" + "".join(f"\n- {x}" for x in design_result["erklaerung"]))
                if design_result["nicht_moeglich"]:
                    st.warning("**Nicht automatisch möglich:**"
                               + "".join(f"\n- {x}" for x in design_result["nicht_moeglich"]))

            st.caption("Einstellungen")
            g1, g2, g3 = st.columns(3)
            schrift = g1.selectbox("Schriftart", list(CV_FONTS), index=list(CV_FONTS).index(S.CV_OPTIONS["schrift"])
                                   if S.CV_OPTIONS["schrift"] in CV_FONTS else 0, key=f"opt_font_{wkey}")
            groesse = g2.radio("Textgrösse", list(CV_SIZES), horizontal=True,
                               index=list(CV_SIZES).index(S.CV_OPTIONS["groesse"])
                               if S.CV_OPTIONS["groesse"] in CV_SIZES else 1, key=f"opt_size_{wkey}")
            accent = g3.color_picker("Akzentfarbe", S.CV_ACCENT, key=f"opt_accent_{wkey}")
            h1, h2, h3 = st.columns(3)
            abstand = h1.radio("Abstände", list(CV_SPACING), horizontal=True,
                               index=list(CV_SPACING).index(S.CV_OPTIONS["abstand"])
                               if S.CV_OPTIONS["abstand"] in CV_SPACING else 1, key=f"opt_space_{wkey}")
            fotogroesse = h2.radio("Fotogrösse", list(CV_PHOTO_SIZES), horizontal=True,
                                   index=list(CV_PHOTO_SIZES).index(S.CV_OPTIONS["fotogroesse"])
                                   if S.CV_OPTIONS["fotogroesse"] in CV_PHOTO_SIZES else 1, key=f"opt_fsize_{wkey}")
            seiten_optionen = [0, 1, 2, 3, 4]
            max_seiten = h3.selectbox("Maximale Seitenzahl", seiten_optionen,
                                      index=seiten_optionen.index(int(S.CV_OPTIONS["max_seiten"]))
                                      if int(S.CV_OPTIONS["max_seiten"]) in seiten_optionen else 0,
                                      format_func=lambda n: "Keine Begrenzung" if n == 0 else f"max. {n} Seite(n)",
                                      key=f"opt_pages_{wkey}",
                                      help="Wird automatisch eingehalten: erst Abstände, dann Foto und Schrift, "
                                           "dann weniger Stichpunkte.")
            g4, g5, g6 = st.columns(3)
            foto = g4.toggle("Foto anzeigen", S.CV_OPTIONS["foto"], key=f"opt_foto_{wkey}")
            im_kopf = g4.toggle("Persönliche Angaben im Kopf (neben Name)", S.CV_OPTIONS["angaben_im_kopf"],
                                key=f"opt_head_{wkey}", help="Keine Lücke zwischen Name/Foto und den persönlichen Daten")
            max_punkte = g5.slider("Stichpunkte pro Stelle (max.)", 1, 10, int(S.CV_OPTIONS["max_punkte"]),
                                   key=f"opt_pts_{wkey}", help="Weniger Stichpunkte = kürzerer Lebenslauf")
            abschnitte = st.multiselect("Diese Abschnitte anzeigen (Berufserfahrung wird immer angezeigt)",
                                        list(CV_SECTIONS), default=[a for a in S.CV_OPTIONS["abschnitte"]
                                                                    if a in CV_SECTIONS],
                                        format_func=CV_SECTIONS.get, key=f"opt_sec_{wkey}")
            new_options = {"schrift": schrift, "groesse": groesse, "foto": foto, "abschnitte": abschnitte,
                           "max_punkte": max_punkte, "abstand": abstand, "fotogroesse": fotogroesse,
                           "angaben_im_kopf": im_kopf, "max_seiten": max_seiten}
            if new_options != S.CV_OPTIONS:
                settings.set_cv_options(new_options)
                st.rerun()
            if accent.lower() != S.CV_ACCENT.lower():
                settings.set_cv_style(S.CV_TEMPLATE, accent)
                st.rerun()
            if g6.button("Alles zurücksetzen", width="stretch",
                         disabled=new_options == DEFAULT_CV_OPTIONS
                         and S.CV_ACCENT.lower() == CV_TEMPLATES[S.CV_TEMPLATE]["farbe"].lower()):
                settings.set_cv_options(None)
                settings.set_cv_style(S.CV_TEMPLATE)
                st.session_state.pop("design_result", None)
                st.rerun()

        st.markdown(f"**3. Dein Lebenslauf im Design „{CV_TEMPLATES[S.CV_TEMPLATE]['name']}“** – "
                    "genau dieses Dokument wird heruntergeladen bzw. gespeichert.")
        preview_col, action_col = st.columns([3, 1])
        try:
            pdf_bytes, pages, used_options, fit_notes = template_preview(S.CV_TEMPLATE, S.CV_ACCENT, base_json, 90,
                                                                         stamp, options_json)
            docx_bytes = word.build_cv_docx(base_data, template=S.CV_TEMPLATE, accent=S.CV_ACCENT, options=used_options)
            with preview_col:
                if fit_notes:
                    st.info(f"Damit der Lebenslauf auf max. {S.CV_OPTIONS['max_seiten']} Seite(n) passt, wurde "
                            "automatisch angepasst:" + "".join(f"\n- {n}" for n in fit_notes))
                for page in pages:
                    st.image(page, width="stretch")
            with action_col:
                st.caption(f"{len(pages)} Seite(n)")
                file_name = safe_filename("Lebenslauf", S.NAME)
                st.download_button("Als PDF herunterladen", pdf_bytes, file_name=file_name + ".pdf",
                                   mime="application/pdf", type="primary", width="stretch")
                st.download_button("Als Word herunterladen (.docx)", docx_bytes, file_name=file_name + ".docx",
                                   mime=DOCX_MIME, width="stretch")
                st.caption("Die Word-Datei kannst du frei weiterbearbeiten. Sie übernimmt Farbe, Schrift und "
                           "Abschnitte, hat aber ein einfacheres Layout als das PDF.")
                target = Path(settings.get_save_dir()) / "Allgemein"
                if st.button("PDF + Word im Bewerbungsordner speichern", width="stretch"):
                    target.mkdir(parents=True, exist_ok=True)
                    (target / (file_name + ".pdf")).write_bytes(pdf_bytes)
                    (target / (file_name + ".docx")).write_bytes(docx_bytes)
                    st.success(f"Gespeichert in {target}")
                st.caption(f"Speicherort: `{target}`")
                applied = documents.load_applied_improvements()
                if applied:
                    with st.expander(f"Übernommene Verbesserungen ({len(applied)})"):
                        for point in applied:
                            st.caption(f"• {point}")
                st.caption("Inhalt ändern: im Reiter „1. Meine Unterlagen“ (KI-Analyse, Ergänzungen oder Profil "
                           "bearbeiten). Das Foto änderst du im Reiter „Bewerbungsfoto“.")
        except Exception as e:
            st.error(f"Lebenslauf konnte nicht erstellt werden: {e}")
