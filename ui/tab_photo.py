import io
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

from src import documents, photo, settings
from src.generate import safe_filename
from src.profile import set_photo
from ui import state as S
from ui.helpers import cv_photo_candidates_cached


@st.cache_data(show_spinner=False, max_entries=200)
def _bytes_preview(data: bytes, side: int) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=200)
def _file_preview(path: str, mtime: float, side: int) -> bytes:
    return _bytes_preview(Path(path).read_bytes(), side)


def _preview(path: Path, side: int = 480) -> bytes:
    """Kleine JPEG-Vorschau statt des vollen PNG; neu nur, wenn sich die Datei ändert."""
    return _file_preview(str(path), path.stat().st_mtime, side)


@st.cache_data(show_spinner=False, max_entries=50)
def _blend_preview(a: bytes, b: bytes, amount: float) -> bytes:
    img_a = Image.open(io.BytesIO(a)).convert("RGB")
    img_b = ImageOps.fit(Image.open(io.BytesIO(b)).convert("RGB"), img_a.size)
    buf = io.BytesIO()
    Image.blend(img_a, img_b, amount).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _cv_candidates() -> None:
    candidates = cv_photo_candidates_cached(
        tuple((str(p), p.stat().st_mtime) for p in documents.list_documents("lebenslauf")))
    if not candidates:
        st.caption("In deinen hochgeladenen Lebensläufen wurde kein Foto gefunden. Lade deinen Lebenslauf "
                   "(Word oder PDF) unter „1. Meine Unterlagen“ hoch oder oben direkt ein Foto.")
    else:
        st.caption("Diese Bilder wurden aus deinen Lebensläufen herausgeholt. Übernimm eines als Original – "
                   "danach kannst du es unten mit KI bearbeiten und speichern.")
        cand_cols = st.columns(4)
        for i, (source, img_bytes) in enumerate(candidates):
            with cand_cols[i % 4]:
                w, h = Image.open(io.BytesIO(img_bytes)).size
                st.image(_bytes_preview(img_bytes, 300), caption=f"aus {source} ({w}×{h} px)", width="stretch")
                if min(w, h) < 600:
                    st.caption("Niedrige Auflösung – „Professionell aufwerten“ macht es schärfer.")
                if st.button("Als Original übernehmen", key=f"cand_{i}", width="stretch"):
                    st.session_state["photo_current"] = str(photo.save_original(img_bytes))
                    st.session_state["notice"] = "Foto aus dem Lebenslauf übernommen – du kannst es jetzt bearbeiten."
                    st.rerun()


def render() -> None:
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
    box = st.expander("Foto aus meinem Lebenslauf übernehmen", expanded=not versions, key="photo_cv_exp",
                      on_change="rerun")
    if box.open:
        with box:
            _cv_candidates()
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
            st.image(_preview(current), width="stretch")
            meta = photo.load_meta(current)
            similarity = meta.get("aehnlichkeit")
            if similarity is not None:
                if similarity >= photo.MIN_SIMILARITY:
                    st.success(f"Ähnlichkeit mit dem Original: {similarity}/10")
                else:
                    st.error(f"Ähnlichkeit mit dem Original nur {similarity}/10 – {meta.get('aehnlichkeit_fazit', '')} "
                             "Ein Bewerbungsfoto muss dir klar ähnlich sehen. Besser mit „Gesicht unverändert "
                             "lassen“ neu bearbeiten.")
            elif "original" not in current.name and S.LLM_OK:
                if st.button("Ähnlichkeit mit Original prüfen", width="stretch"):
                    with st.spinner("KI vergleicht mit dem Original ..."):
                        try:
                            photo.check_similarity(current)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Prüfung fehlgeschlagen: {e}")
            if st.button("Als Bewerbungsfoto verwenden", type="primary", width="stretch"):
                photo.use_as_application_photo(current)
                set_photo(photo.FINAL_REL)
                st.session_state["notice"] = "Foto übernommen – es erscheint ab jetzt in deinen Lebensläufen."
                st.rerun()
            st.download_button("Diese Version herunterladen", current.read_bytes,
                               file_name=f"Bewerbungsfoto_{safe_filename(S.NAME) or 'ich'}_{current.stem[:15]}.png",
                               mime="image/png", width="stretch")
            photo_target = Path(settings.get_save_dir()) / "Bewerbungsfoto"
            if st.button("Im Bewerbungsordner speichern", key="save_photo", width="stretch"):
                photo_target.mkdir(parents=True, exist_ok=True)
                saved_photo = photo_target / f"Bewerbungsfoto_{current.stem}.png"
                saved_photo.write_bytes(current.read_bytes())
                st.success(f"Gespeichert: {saved_photo}")
            st.caption(f"Ordner: `{photo_target}`")
            if st.button("Foto von KI bewerten lassen", width="stretch", disabled=not S.LLM_OK):
                with st.spinner("KI bewertet dein Foto ..."):
                    try:
                        st.session_state["photo_review"] = {"path": str(current), **photo.review(current)}
                    except Exception as e:
                        st.error(f"Bewertung fehlgeschlagen: {e}")

        with right:
            st.markdown("**Mit KI bearbeiten**")
            face_lock = st.toggle("Gesicht unverändert lassen (empfohlen)", value=True, key="face_lock",
                                  help="Nur Licht, Hintergrund, Kleidung und Ausschnitt werden verändert. Gesicht, "
                                       "Lächeln und Frisur bleiben exakt wie im Original.")
            preset_options = [p for p in photo.PRESETS if not (face_lock and p in photo.EDITABLE_PRESETS)]
            presets = st.multiselect("Was soll verbessert werden?", preset_options,
                                     default=["Professionell aufwerten"])
            if face_lock:
                st.caption("Frisur- und Gesichtsretusche sind ausgeblendet. Schalte „Gesicht unverändert lassen“ "
                           "aus, wenn du das bewusst möchtest.")
            custom = st.text_input("Eigener Wunsch (optional)",
                                   placeholder="z.B. Spiegelung in der Brille entfernen, Hintergrund dunkelblau")
            models = photo.available_models()
            if not models:
                st.warning("Fotobearbeitung gibt es nur mit Venice oder OpenAI (Einstellungen → API & KI).")
            photo_model = st.selectbox("KI-Modell", list(models), format_func=models.get)
            auto_check = st.checkbox("Danach automatisch prüfen, ob ich noch gleich aussehe", value=True,
                                     disabled=not S.LLM_OK)
            if st.button("Foto bearbeiten", type="primary",
                         disabled=not (S.LLM_OK and photo_model and (presets or custom.strip()))):
                with st.spinner("KI bearbeitet dein Foto (ca. 10–60 Sekunden) ..."):
                    try:
                        new_path = photo.edit(current, photo.build_prompt(presets, custom, face_lock), photo_model)
                        st.session_state["photo_current"] = str(new_path)
                    except Exception as e:
                        st.error(f"Bearbeitung fehlgeschlagen: {e}")
                        new_path = None
                if new_path and auto_check:
                    with st.spinner("KI prüft die Ähnlichkeit mit dem Original ..."):
                        try:
                            photo.check_similarity(new_path)
                        except Exception:
                            pass  # lässt sich links per Knopf nachholen
                if new_path:
                    st.rerun()
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

        if len(versions) >= 2:
            st.divider()
            st.subheader("Vorher / Nachher vergleichen")
            originals = [v for v in versions if "original" in v.name]
            default_b = current if current in versions else versions[0]
            older_originals = [v for v in originals if v.name < default_b.name and v != default_b]
            default_a = (older_originals or [v for v in originals if v != default_b]
                         or [v for v in versions if v != default_b])[0]
            k1, k2 = st.columns(2)
            ver_a = k1.selectbox("Bild A (vorher)", versions, index=versions.index(default_a),
                                 format_func=photo.version_label, key=f"cmp_a_{default_a.name}")
            ver_b = k2.selectbox("Bild B (nachher)", versions, index=versions.index(default_b),
                                 format_func=photo.version_label, key=f"cmp_b_{default_b.name}")
            c_a, c_b, c_mix = st.columns(3)
            c_a.image(_preview(ver_a, 400), caption="A – " + photo.version_label(ver_a), width="stretch")
            c_b.image(_preview(ver_b, 400), caption="B – " + photo.version_label(ver_b), width="stretch")
            with c_mix:
                amount = st.slider("Überblenden A ↔ B", 0, 100, 50, step=5,
                                   help="Schiebe hin und her, um die Unterschiede zu sehen.")
                st.image(_blend_preview(_preview(ver_a, 400), _preview(ver_b, 400), amount / 100),
                         caption=f"{100 - amount}% A / {amount}% B",
                         width="stretch")

            if st.button("Vergleich von KI analysieren lassen", type="primary",
                         disabled=not S.LLM_OK or ver_a == ver_b):
                with st.spinner("KI vergleicht die beiden Fotos ..."):
                    try:
                        st.session_state["photo_compare"] = {"a": str(ver_a), "b": str(ver_b),
                                                             **photo.compare(ver_a, ver_b)}
                    except Exception as e:
                        st.error(f"Vergleich fehlgeschlagen: {e}")
            cmp = st.session_state.get("photo_compare")
            if cmp and cmp["a"] == str(ver_a) and cmp["b"] == str(ver_b):
                m1, m2, m3 = st.columns(3)
                m1.metric("Note A (vorher)", f"{cmp['note_a']}/10")
                m2.metric("Note B (nachher)", f"{cmp['note_b']}/10", delta=cmp["note_b"] - cmp["note_a"])
                m3.metric("Ähnlichkeit mit dir", f"{cmp['aehnlichkeit']}/10")
                sim_box = st.success if cmp["aehnlichkeit"] >= 8 else st.warning if cmp["aehnlichkeit"] >= 6 else st.error
                sim_box(f"**Erkennbarkeit:** {cmp.get('aehnlichkeit_fazit', '')}")
                d1, d2 = st.columns(2)
                d1.markdown("**Besser auf B**" + "".join(f"\n- {x}" for x in cmp.get("besser", [])))
                d2.markdown("**Schlechter auf B**" + ("".join(f"\n- {x}" for x in cmp.get("schlechter", []))
                                                      or "\n- nichts"))
                if cmp.get("ki_fehler"):
                    st.warning("**Sichtbare KI-Fehler auf B:**" + "".join(f"\n- {x}" for x in cmp["ki_fehler"]))
                winner = ver_b if cmp["empfehlung"] == "B" else ver_a
                st.info(f"**Empfehlung: Bild {cmp['empfehlung']}** ({photo.version_label(winner)}) – "
                        f"{cmp.get('begruendung', '')}")
                if cmp.get("naechste_schritte"):
                    st.markdown("**Ideen für die nächste Bearbeitung**"
                                + "".join(f"\n- {x}" for x in cmp["naechste_schritte"]))
                w1, w2 = st.columns(2)
                if w1.button(f"Bild {cmp['empfehlung']} als Bewerbungsfoto verwenden", width="stretch"):
                    photo.use_as_application_photo(winner)
                    set_photo(photo.FINAL_REL)
                    st.session_state["notice"] = "Foto übernommen – es erscheint ab jetzt in deinen Lebensläufen."
                    st.rerun()
                if w2.button(f"Bild {cmp['empfehlung']} weiter bearbeiten", width="stretch"):
                    st.session_state["photo_current"] = str(winner)
                    st.rerun()

        if photo.final_path().exists():
            st.markdown("**Aktuelles Bewerbungsfoto im Lebenslauf**")
            st.image(_preview(photo.final_path(), 300), width=150)

        st.markdown("**Alle Versionen**")
        grid = st.columns(5)
        for i, version in enumerate(versions):
            with grid[i % 5]:
                label = "Original" if "original" in version.name else "Bearbeitet"
                if (sim := photo.load_meta(version).get("aehnlichkeit")) is not None:
                    label += f" · Ähnlichkeit {sim}/10" + (" ⚠" if sim < photo.MIN_SIMILARITY else "")
                st.image(_preview(version, 240), caption=label + (" (ausgewählt)" if version == current else ""),
                         width="stretch")
                v1, v2 = st.columns(2)
                if v1.button("Auswählen", key=f"sel_{version.name}", width="stretch"):
                    st.session_state["photo_current"] = str(version)
                    st.rerun()
                if v2.button("Löschen", key=f"delv_{version.name}", width="stretch"):
                    photo.delete_version(version)
                    st.rerun()
