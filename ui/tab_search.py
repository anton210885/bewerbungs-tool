from dataclasses import asdict
from datetime import datetime

import streamlit as st

from src import jobs, searches
from src.config import COUNTRY, adzuna_configured
from ui import state as S
from ui.helpers import check_job, show_analysis, store_job


def _schedule_controls() -> None:
    scheduled = searches.scheduled_time()
    c1, c2, c3 = st.columns([2, 1, 1])
    if scheduled:
        c1.success(f"Automatische Suche ist eingerichtet (täglich, {scheduled}). Der Computer muss dafür "
                   "eingeschaltet sein – die App selbst muss nicht laufen.")
        if c3.button("Ausschalten", width="stretch"):
            searches.unschedule()
            st.rerun()
    else:
        c1.caption("Auf Wunsch sucht der Computer jeden Tag automatisch (Windows-Aufgabenplanung). Die neuen "
                   "Treffer erscheinen dann hier.")
        time_ = c2.time_input("Uhrzeit", value=datetime.strptime("08:00", "%H:%M").time(), step=1800,
                              label_visibility="collapsed")
        if c3.button("Täglich automatisch suchen", width="stretch"):
            try:
                searches.schedule_daily(time_.strftime("%H:%M"))
                st.rerun()
            except Exception as e:
                st.error(f"Einrichten fehlgeschlagen: {e}")


def _saved_searches() -> None:
    st.subheader("Gespeicherte Suchen")
    st.caption("Speichere die Adresse einer Suchergebnisseite (z.B. jobs.ch mit deinen Suchbegriffen und Region). "
               "Bei jeder Suche prüft die KI nur Stellen, die du noch nicht gesehen hast, und zeigt dir die besten.")
    saved = searches.list_searches()
    with st.expander("Neue Suche speichern", expanded=not saved):
        with st.form("new_search", clear_on_submit=True):
            name = st.text_input("Name", placeholder="z.B. Data Engineer Aargau")
            url = st.text_input("Adresse der Suchergebnisseite",
                                placeholder="https://www.jobs.ch/de/stellenangebote/?term=data%20engineer&location=aarau")
            n1, n2 = st.columns(2)
            top_n = n1.slider("Beste Treffer anzeigen", 3, 10, 5)
            detail_n = n2.slider("Neue Stellen im Detail prüfen (max.)", 5, 25, 10,
                                 help="Mehr = gründlicher, aber teurer (ca. 3 Rappen pro geprüfte Stelle).")
            if st.form_submit_button("Speichern", type="primary") and url.strip().startswith("http"):
                searches.add_search(name, url, top_n, detail_n)
                st.rerun()
    if not saved:
        return

    due = [s for s in saved if searches.is_due(s)]
    b1, b2 = st.columns([1, 3])
    if b1.button(f"Alle Suchen jetzt ausführen ({len(saved)})", type="primary" if due else "secondary",
                 disabled=not (S.LLM_OK and S.PROFILE_READY), width="stretch"):
        with st.status("Suche nach neuen Stellen ...", expanded=True) as status:
            errors = searches.run_all(S.profile, on_progress=st.write)
            status.update(label="Fertig" if not errors else "Fertig, mit Fehlern",
                          state="complete" if not errors else "error")
            for err in errors:
                st.error(err)
        st.rerun()
    if due:
        b2.info(f"{len(due)} Suche(n) seit über 24 Stunden nicht mehr ausgeführt.")
    _schedule_controls()

    results = searches.load_results()
    for s in saved:
        res = results.get(s["id"])
        last = (datetime.fromisoformat(s["letzte_suche"]).strftime("%d.%m. %H:%M")
                if s.get("letzte_suche") else "noch nie")
        hits = len(res["ergebnisse"]) if res else 0
        with st.expander(f"{s['name']}  ·  zuletzt: {last}  ·  {hits} Treffer", expanded=hits > 0):
            st.caption(s["url"])
            r1, r2 = st.columns([1, 1])
            if r1.button("Nur diese Suche ausführen", key=f"run_{s['id']}", disabled=not (S.LLM_OK and S.PROFILE_READY)):
                with st.status(f"{s['name']} ...", expanded=True):
                    try:
                        searches.run_search(S.profile, s, on_progress=st.write)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Suche fehlgeschlagen: {e}")
            if r2.button("Suche löschen", key=f"del_search_{s['id']}"):
                searches.delete_search(s["id"])
                st.rerun()
            if not res:
                continue
            st.caption(f"Letzter Lauf: {res['neu_gefunden']} neue Stellen gefunden, beste {hits} angezeigt.")
            for i, r in enumerate(res["ergebnisse"]):
                score = r["analysis"].get("score", 0)
                with st.container(border=True):
                    st.markdown(f"**{score} %  ·  {r['title']}** – {r['company'] or '?'}"
                                + (f" · {r['location']}" if r.get("location") else "") + f"  ·  [Anzeige]({r['url']})")
                    show_analysis(r["analysis"])
                    a1, a2 = st.columns(2)
                    if a1.button("Übernehmen und bewerben", type="primary", key=f"take_{s['id']}_{i}"):
                        st.session_state["current_app"] = store_job(r["url"], r, r["analysis"])
                        searches.remove_result(s["id"], r["url"])
                        st.session_state["notice"] = (f"„{r['title']}“ übernommen – weiter unter „2. Stelle prüfen "
                                                      "& bewerben“.")
                        st.rerun()
                    if a2.button("Interessiert mich nicht", key=f"skip_{s['id']}_{i}"):
                        searches.remove_result(s["id"], r["url"])
                        st.rerun()


def _portal_search() -> None:
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
        st.info("Für diese Suche in der Schweiz trage `ADZUNA_APP_ID` und `ADZUNA_APP_KEY` in die `.env` ein. "
                "Einfacher: oben eine jobs.ch-Suche speichern.")

    if st.button("Suchen", disabled=not (was and quellen)):
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


def render() -> None:
    _saved_searches()
    st.divider()
    with st.expander("Suche über Job-Schnittstellen (Adzuna / Arbeitsagentur)"):
        _portal_search()
