import streamlit as st

from src import backup, models


def _model_section() -> None:
    st.subheader("KI-Modell")
    available = models.list_models()
    current = models.current_model()
    if not available:
        st.caption(f"Aktuell: `{current}` (Liste der Modelle nicht verfügbar)")
        return
    by_id = {m["id"]: m for m in available}
    choices = [m for m in models.RECOMMENDED if m in by_id]
    if current not in choices:
        choices.append(current)
    show_all = st.toggle("Alle Modelle anzeigen", key="all_models")
    if show_all:
        only_private = st.toggle("Nur private Modelle", value=True, key="only_private")
        choices = sorted({current, *(m["id"] for m in available if not only_private or m["privacy"] == "private")})

    def label(model_id: str) -> str:
        info = by_id.get(model_id)
        if not info:
            return model_id
        lock = "🔒 " if info["privacy"] == "private" else ""
        return lock + models.RECOMMENDED.get(model_id, info["name"])

    chosen = st.selectbox("Modell für Texte und Analysen", choices, index=choices.index(current),
                          format_func=label, key=f"model_{current}")
    if chosen != current:
        models.set_model(chosen)
        st.rerun()
    if info := by_id.get(current):
        (st.success if info["privacy"] == "private" else st.info)(
            models.PRIVACY_LABELS.get(info["privacy"], info["privacy"]))
        st.caption(f"Preis: ${info['preis_in']} / ${info['preis_out']} pro 1 Mio. Tokens (Eingabe/Ausgabe)"
                   + ("" if info["vision"] else f"  ·  Bilder liest `{models.current_vision_model()}`"))
    st.caption("🔒 = privat. Für Lebenslauf und Zeugnisse empfohlen, wenn dir Datenschutz wichtig ist.")


def _backup_section() -> None:
    st.subheader("Sicherung")
    days = backup.days_since_last_backup()
    if days is None:
        st.warning("Noch keine Sicherung erstellt. Deine Daten liegen nur auf diesem Computer.")
    elif days >= backup.REMIND_AFTER_DAYS:
        st.warning(f"Letzte Sicherung vor {days} Tagen.")
    else:
        st.caption(f"Letzte Sicherung: vor {days} Tag(en)" if days else "Letzte Sicherung: heute")
    st.caption("Enthält Profil, Unterlagen, Fotos, Tracker und Einstellungen.")
    if st.button("Sicherung im Bewerbungsordner speichern", width="stretch"):
        try:
            path = backup.save_backup_to_folder()
            st.success(f"Gespeichert: {path}")
        except Exception as e:
            st.error(f"Sicherung fehlgeschlagen: {e}")
    if st.button("Sicherung als Download vorbereiten", width="stretch"):
        st.session_state["backup_zip"] = backup.create_backup()
    if zip_bytes := st.session_state.get("backup_zip"):
        st.download_button("Sicherung herunterladen (.zip)", zip_bytes, file_name=backup.backup_filename(),
                           mime="application/zip", type="primary", width="stretch")
    with st.expander("Sicherung wiederherstellen"):
        upload = st.file_uploader("Sicherung (.zip)", type=["zip"], key="restore_zip")
        if upload and st.button("Jetzt wiederherstellen", type="primary", width="stretch"):
            try:
                previous = backup.restore_backup(upload.getvalue())
                st.session_state["notice"] = (f"Sicherung wiederhergestellt. Der vorherige Stand liegt in "
                                              f"`{previous.name}`.")
                st.rerun()
            except Exception as e:
                st.error(f"Wiederherstellen fehlgeschlagen: {e}")


def render() -> None:
    with st.sidebar:
        st.header("Einstellungen")
        _model_section()
        st.divider()
        _backup_section()
