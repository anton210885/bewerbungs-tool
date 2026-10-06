import streamlit as st

from src import db
from ui import state, tab_check, tab_cv, tab_docs, tab_photo, tab_search, tab_tracker

st.set_page_config(page_title="Bewerbungs-Tool", layout="wide")
db.init_db()
st.session_state.setdefault("upload_round", 0)
state.refresh()

st.title("Bewerbungs-Tool")
if not state.LLM_OK:
    st.warning("Kein `LLM_API_KEY` in der `.env` gefunden – die KI-Funktionen sind deaktiviert.")
if notice := st.session_state.pop("notice", None):
    st.success(notice)

TABS = {
    "1. Meine Unterlagen": tab_docs,
    "Mein Lebenslauf": tab_cv,
    "Bewerbungsfoto": tab_photo,
    "2. Stelle prüfen & bewerben": tab_check,
    "Stellensuche": tab_search,
    "Tracker": tab_tracker,
}
for tab, module in zip(st.tabs(list(TABS)), TABS.values()):
    with tab:
        module.render()
