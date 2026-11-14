from datetime import datetime

import streamlit as st

from src import searches
from ui import state as S


def _schedule_controls() -> None:
    if not searches.SCHEDULING_AVAILABLE:
        st.caption("Die tägliche automatische Suche gibt es nur unter Windows. Gespeicherte Suchen kannst du "
                   "hier jederzeit von Hand starten.")
        return
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
    st.caption("Für Karriere- oder Suchseiten, die du regelmässig prüfen willst und deren Anbieter automatisiertes "
               "Abrufen erlaubt. Bei jedem Lauf bewertet die KI nur Stellen, die du noch nicht gesehen hast; die "
               "besten erscheinen unter «Stellen ansehen».")
    saved = searches.list_searches()
    with st.expander("Neue Suche speichern", expanded=not saved):
        with st.form("new_search", clear_on_submit=True):
            name = st.text_input("Name", placeholder="z.B. Data Engineer Aargau")
            url = st.text_input("Adresse der Suchergebnisseite",
                                placeholder="https://karriere.beispiel.ch/offene-stellen")
            n1, n2 = st.columns(2)
            top_n = n1.slider("Beste Treffer behalten", 3, 10, 5)
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
        st.session_state["saved_search_done"] = errors
        st.rerun()
    if due:
        b2.info(f"{len(due)} Suche(n) seit über 24 Stunden nicht mehr ausgeführt.")
    if "saved_search_done" in st.session_state:
        from ui.tab_discovery import found_message
        results = searches.load_results()
        found_message(sum(len(r.get("ergebnisse", [])) for r in results.values()),
                      st.session_state.pop("saved_search_done"), "saved")
    _schedule_controls()

    results = searches.load_results()
    for s in saved:
        res = results.get(s["id"])
        last = (datetime.fromisoformat(s["letzte_suche"]).strftime("%d.%m. %H:%M")
                if s.get("letzte_suche") else "noch nie")
        with st.expander(f"{s['name']}  ·  zuletzt: {last}"):
            st.caption(s["url"])
            if res:
                st.caption(f"Letzter Lauf: {res['neu_gefunden']} neue Stellen, die besten "
                           f"{len(res['ergebnisse'])} stehen unter «Stellen ansehen».")
                for error in res.get("fehler", []):
                    st.warning(error)
            r1, r2 = st.columns(2)
            if r1.button("Nur diese Suche ausführen", key=f"run_{s['id']}",
                         disabled=not (S.LLM_OK and S.PROFILE_READY)):
                with st.status(f"{s['name']} ...", expanded=True):
                    try:
                        searches.run_search(S.profile, s, on_progress=st.write)
                        st.session_state["saved_search_done"] = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Suche fehlgeschlagen: {e}")
            if r2.button("Suche löschen", key=f"del_search_{s['id']}"):
                searches.delete_search(s["id"])
                st.rerun()


def render() -> None:
    from ui import tab_companies, tab_discovery
    st.subheader("Stellen holen")
    st.caption("Hier stellst du ein, wo das Tool nach Stellen sucht. Alles Gefundene landet an einem Ort: "
               "unter «Stellen ansehen».")
    portals, firms, saved = st.tabs(["Jobportale", "Firmen in der Umgebung", "Gespeicherte Suchen"])
    with portals:
        tab_discovery.render()
    with firms:
        tab_companies.render()
    with saved:
        _saved_searches()
