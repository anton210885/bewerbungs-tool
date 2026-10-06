from dataclasses import asdict

import streamlit as st

from src import jobs
from src.config import COUNTRY, adzuna_configured
from ui import state as S
from ui.helpers import (
    check_job,
)


def render() -> None:
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
        st.info("Für die automatische Suche in der Schweiz trage `ADZUNA_APP_ID` und `ADZUNA_APP_KEY` in die "
                "`.env` ein. Stellen von jobs.ch, jobup.ch oder LinkedIn prüfst du einfach per Link "
                "unter „2. Stelle prüfen & bewerben“.")

    if st.button("Suchen", type="primary", disabled=not (was and quellen)):
        results = []
        with st.spinner("Suche läuft ..."):
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
            if st.button("Passt sie zu mir?", key=f"check_{i}", disabled=not (S.LLM_OK and S.PROFILE_READY)):
                check_job(job.url, meta=asdict(job))
