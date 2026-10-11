import json
from pathlib import Path

import streamlit as st

from src import cv_builder, documents, settings, word
from src.generate import (
    CV_FONTS,
    CV_PHOTO_SIZES,
    CV_SECTIONS,
    CV_SIZES,
    CV_SPACING,
    CV_TEMPLATES,
    DEFAULT_CV_OPTIONS,
    design_from_wish,
    safe_filename,
    translate_cv,
)
from ui import state as S
from ui.helpers import DOCX_MIME, _photo_stamp, styled_cv, template_preview


def _builder() -> dict:
    """Checkbox-Auswahl: Aufgaben und Hobbies. Adresse, Ausbildung, Weiterbildung bleiben fix."""
    st.markdown("**1. Inhalt zusammenstellen** – Adresse, Ausbildung und Weiterbildung sind immer dabei. "
                "Aufgaben und Hobbies wählst du selbst per Checkbox.")
    sel = cv_builder.load_selection(S.profile)
    stellen = cv_builder.stellen_aufgaben(S.profile)
    hobby_list = cv_builder.hobbies(S.profile)

    p = S.profile.get("persoenlich") or {}
    with st.expander("Immer enthalten (fix)", expanded=False):
        st.markdown(
            f"**{p.get('name', '')}** · {p.get('strasse', '')}, {p.get('plz', '')} {p.get('ort', '')}  \n"
            f"{p.get('telefon', '')} · {p.get('email', '')}"
        )
        for a in S.profile.get("ausbildung") or []:
            st.caption(f"Ausbildung: {a.get('abschluss', '')} – {a.get('institution', '')} "
                       f"({a.get('von', '')}–{a.get('bis', '') or 'heute'})")
        for z in S.profile.get("zertifikate") or []:
            name = z.get("name", z) if isinstance(z, dict) else z
            jahr = f" ({z.get('jahr')})" if isinstance(z, dict) and z.get("jahr") else ""
            st.caption(f"Weiterbildung / Zertifikat: {name}{jahr}")

    new_sel = {
        "aufgaben": {},
        "erfolge": {},
        "hobbies": [],
        "kurzprofil": st.checkbox("Kurzprofil anzeigen", value=sel.get("kurzprofil", True), key="cv_kurz"),
    }
    if S.profile.get("kurzprofil") and new_sel["kurzprofil"]:
        st.caption(S.profile["kurzprofil"][:280] + ("…" if len(S.profile["kurzprofil"]) > 280 else ""))

    st.markdown("**Berufserfahrung – Aufgaben wählen**")
    st.caption("Quelle: **CV** = aus dem Lebenslauf, **Zeugnis** = aus dem Arbeitszeugnis, "
               "**CV+Zeugnis** = in beiden belegt.")
    for s in stellen:
        i = str(s["index"])
        zeit = f"{s['von']} – {s['bis'] or 'heute'}"
        with st.expander(f"{s['position']} · {s['firma']} ({zeit}) – "
                         f"{len(s['aufgaben'])} Aufgaben", expanded=s["index"] < 3):
            chosen_e, chosen_a = [], []
            if s["erfolge"]:
                st.markdown("*Erfolge*")
                for j, item in enumerate(s["erfolge"]):
                    q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                    label = f"{item['text']}" + (f"  ·  `{q}`" if q else "")
                    if st.checkbox(label, value=j in sel.get("erfolge", {}).get(i, []),
                                   key=f"cv_e_{i}_{j}"):
                        chosen_e.append(j)
            if s["aufgaben"]:
                st.markdown("*Aufgaben*")
                for j, item in enumerate(s["aufgaben"]):
                    q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                    label = f"{item['text']}" + (f"  ·  `{q}`" if q else "")
                    if st.checkbox(label, value=j in sel.get("aufgaben", {}).get(i, []),
                                   key=f"cv_a_{i}_{j}"):
                        chosen_a.append(j)
            if not s["aufgaben"] and not s["erfolge"]:
                st.caption("Keine Aufgaben hinterlegt – unter „Meine Unterlagen“ Profil neu erstellen.")
            c1, c2 = st.columns(2)
            if c1.button("Alle", key=f"all_{i}", width="stretch"):
                new_sel["erfolge"][i] = list(range(len(s["erfolge"])))
                new_sel["aufgaben"][i] = list(range(len(s["aufgaben"])))
                cv_builder.save_selection({**sel, "erfolge": {**sel.get("erfolge", {}), i: new_sel["erfolge"][i]},
                                           "aufgaben": {**sel.get("aufgaben", {}), i: new_sel["aufgaben"][i]}})
                st.rerun()
            if c2.button("Keine", key=f"none_{i}", width="stretch"):
                new_sel["erfolge"][i] = []
                new_sel["aufgaben"][i] = []
                cv_builder.save_selection({**sel, "erfolge": {**sel.get("erfolge", {}), i: []},
                                           "aufgaben": {**sel.get("aufgaben", {}), i: []}})
                st.rerun()
            new_sel["erfolge"][i] = chosen_e
            new_sel["aufgaben"][i] = chosen_a

    if hobby_list:
        st.markdown("**Hobbies / Interessen**")
        cols = st.columns(min(3, len(hobby_list)))
        for j, hobby in enumerate(hobby_list):
            if cols[j % len(cols)].checkbox(hobby, value=j in sel.get("hobbies", []), key=f"cv_h_{j}"):
                new_sel["hobbies"].append(j)

    n_tasks = sum(len(v) for v in new_sel["aufgaben"].values()) + sum(len(v) for v in new_sel["erfolge"].values())
    st.caption(f"Ausgewählt: **{n_tasks}** Aufgaben/Erfolge, **{len(new_sel['hobbies'])}** Hobbies.")

    if new_sel != sel:
        cv_builder.save_selection(new_sel)
    return new_sel


def render() -> None:
    if not S.PROFILE_READY:
        st.info("Lade zuerst im Reiter „1. Meine Unterlagen“ Lebenslauf und Zeugnisse hoch – "
                "das Profil wird automatisch erstellt.")
        return

    selection = _builder()
    base_data = cv_builder.build_cv_from_selection(S.profile, selection)
    base_json = json.dumps(base_data, ensure_ascii=False, sort_keys=True)
    stamp = _photo_stamp(base_data)
    options_json = json.dumps(S.CV_OPTIONS, sort_keys=True)
    thumb_json = json.dumps({**S.CV_OPTIONS, "max_seiten": 0}, sort_keys=True)
    wkey = abs(hash((S.CV_TEMPLATE, S.CV_ACCENT, options_json, base_json))) % 10**8

    st.divider()
    st.markdown("**2. Design wählen**")
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
    st.markdown("**3. Gestalten**")
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
                                  key=f"opt_pages_{wkey}")
        g4, g5, g6 = st.columns(3)
        foto = g4.toggle("Foto anzeigen", S.CV_OPTIONS["foto"], key=f"opt_foto_{wkey}")
        im_kopf = g4.toggle("Persönliche Angaben im Kopf (neben Name)", S.CV_OPTIONS["angaben_im_kopf"],
                            key=f"opt_head_{wkey}")
        max_punkte = g5.slider("Stichpunkte pro Stelle (max.)", 1, 10, int(S.CV_OPTIONS["max_punkte"]),
                               key=f"opt_pts_{wkey}")
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

    st.markdown(f"**4. Dein Lebenslauf im Design „{CV_TEMPLATES[S.CV_TEMPLATE]['name']}“**")
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
            target = Path(settings.get_save_dir()) / "Allgemein"
            if st.button("PDF + Word im Bewerbungsordner speichern", width="stretch"):
                target.mkdir(parents=True, exist_ok=True)
                (target / (file_name + ".pdf")).write_bytes(pdf_bytes)
                (target / (file_name + ".docx")).write_bytes(docx_bytes)
                st.success(f"Gespeichert in {target}")
            st.caption(f"Speicherort: `{target}`")
            st.divider()
            st.markdown("**Englisch**")
            if st.button("Lebenslauf auf Englisch übersetzen", width="stretch",
                         disabled=not S.LLM_OK, type="secondary"):
                with st.spinner("KI übersetzt deinen Lebenslauf ..."):
                    try:
                        from src.config import OUTPUT_DIR
                        en = translate_cv(base_data)
                        en_pdf = styled_cv(en, OUTPUT_DIR / "basis",
                                           safe_filename("CV", S.NAME, "EN") + ".pdf")
                        st.session_state["cv_en_general"] = {
                            "pdf": str(en_pdf),
                            "docx": str(en_pdf.with_suffix(".docx")),
                            "data": en,
                        }
                        st.rerun()
                    except Exception as e:
                        st.error(f"Übersetzung fehlgeschlagen: {e}")
            if en_state := st.session_state.get("cv_en_general"):
                st.caption("Englische Version")
                for page in documents.pdf_to_images(Path(en_state["pdf"]), dpi=70):
                    st.image(page, width="stretch")
                en_name = safe_filename("CV", S.NAME, "EN")
                st.download_button("English PDF", Path(en_state["pdf"]).read_bytes(),
                                   file_name=en_name + ".pdf", mime="application/pdf",
                                   width="stretch", key="dl_en_pdf")
                st.download_button("English Word", Path(en_state["docx"]).read_bytes(),
                                   file_name=en_name + ".docx", mime=DOCX_MIME,
                                   width="stretch", key="dl_en_docx")
    except Exception as e:
        st.error(f"Lebenslauf konnte nicht erstellt werden: {e}")
