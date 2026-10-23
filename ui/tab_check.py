import streamlit as st

from src import batch, db
from ui import state as S
from ui.application import render_application
from ui.helpers import check_job, show_analysis, store_job


def render() -> None:
    if not S.PROFILE_READY:
        st.warning("Lade zuerst unter «1. Meine Unterlagen» deinen Lebenslauf hoch und erstelle dein Profil.")

    mode = st.radio("Was möchtest du prüfen?", ["Eine Stelle", "Viele Stellen (Übersichtsseite)"],
                    horizontal=True, key="check_mode")

    if mode == "Eine Stelle":
        st.markdown("#### Neue Stelle prüfen")
        st.caption("Zuerst den Link einfügen und prüfen. Gespeicherte Stellen erscheinen erst danach unten.")
        with st.form("check", clear_on_submit=True):
            url = st.text_input("Link zur Stellenanzeige",
                                placeholder="https://www.jobs.ch/de/stellenangebote/detail/...")
            text = st.text_area(
                "Oder Anzeigentext einfügen (falls der Link nicht funktioniert)",
                height=140,
                placeholder="Gesamten Anzeigentext hier einfügen – besonders bei Firmenportalen mit Login/Cookies.",
            )
            checked = st.form_submit_button("Passt diese Stelle zu mir?", type="primary",
                                            disabled=not (S.LLM_OK and S.PROFILE_READY))
        if checked:
            if url.strip() or text.strip():
                check_job(url.strip(), text.strip())
            else:
                st.error("Bitte einen Link oder den Anzeigentext eingeben.")
    else:
        st.caption("Füge den Link einer Seite mit vielen Stellen ein, z.B. eine Suchergebnisseite von jobs.ch. "
                   "Die KI sucht die vielversprechendsten heraus, prüft sie im Detail und zeigt dir die besten.")
        with st.form("batch"):
            page_url = st.text_input("Link zur Übersichtsseite",
                                     placeholder="https://www.jobs.ch/de/stellenangebote/?term=sachbearbeiter")
            n1, n2 = st.columns(2)
            top_n = n1.slider("Wie viele Stellen anzeigen?", 3, 10, 10)
            detail_n = n2.slider("Wie viele davon im Detail prüfen?", 5, 25, 15,
                                 help="Mehr = gründlicher, aber teurer (ca. 3 Rappen pro geprüfte Stelle).")
            go = st.form_submit_button("Passende Stellen finden", type="primary",
                                       disabled=not (S.LLM_OK and S.PROFILE_READY))
        if go and page_url.strip():
            with st.status("Suche passende Stellen ...", expanded=True) as status:
                try:
                    st.write("Lese die Übersichtsseite ...")
                    found = batch.extract_jobs(page_url.strip())
                    if not found:
                        raise ValueError("Auf der Seite wurden keine Stellenanzeigen erkannt.")
                    st.write(f"{len(found)} Stellen gefunden. KI wählt die vielversprechendsten aus ...")
                    chosen = batch.preselect(S.profile, found, max(detail_n, top_n))
                    st.write(f"{len(chosen)} Stellen werden im Detail geprüft ...")
                    results, errors = batch.evaluate(S.profile, chosen, on_progress=st.write)
                    st.session_state["batch_results"] = {
                        "results": results[:top_n], "errors": errors, "found": len(found), "checked": len(chosen),
                    }
                    status.update(label=f"Fertig – deine Top {len(results[:top_n])}", state="complete")
                except Exception as e:
                    status.update(label="Fehler", state="error")
                    st.error(f"Das hat nicht geklappt: {e}")

        if batch_data := st.session_state.get("batch_results"):
            results = batch_data["results"]
            st.markdown(f"#### Deine Top {len(results)}")
            st.caption(f"{batch_data['found']} Stellen auf der Seite gefunden, {batch_data['checked']} im Detail geprüft.")
            if batch_data["errors"]:
                with st.expander(f"{len(batch_data['errors'])} Stellen konnten nicht geprüft werden"):
                    for err in batch_data["errors"]:
                        st.write(err)
            if results and st.button("Alle in den Tracker übernehmen"):
                for r in results:
                    store_job(r["url"], r, r["analysis"])
                st.session_state["notice"] = f"{len(results)} Stellen in den Tracker übernommen."
                st.rerun()
            for i, r in enumerate(results):
                score = r["analysis"].get("score", 0)
                where = f" · {r['location']}" if r["location"] else ""
                with st.expander(f"{score} %  ·  {r['title']} – {r['company'] or '?'}{where}", expanded=i == 0):
                    show_analysis(r["analysis"])
                    st.markdown(f"[Zur Anzeige]({r['url']})")
                    if st.button("Übernehmen und bewerben", type="primary", key=f"batch_take_{i}"):
                        st.session_state["current_app"] = store_job(r["url"], r, r["analysis"])
                        st.session_state["show_app_detail"] = True
                        st.session_state["notice"] = (
                            f"«{r['title']}» übernommen – Details werden unten angezeigt."
                        )
                        st.rerun()

    apps = db.list_applications()
    if not apps:
        return

    st.divider()
    labels = {
        a["id"]: f'{a["title"]} – {a["company"] or "?"}' + (f'  ({a["score"]} %)' if a["score"] is not None else "")
        for a in apps
    }
    if st.session_state.get("current_app") not in labels:
        st.session_state["current_app"] = apps[0]["id"]

    # Volle Bewerbungsansicht nur auf Wunsch / nach frischer Prüfung – nicht immer oben
    show_detail = bool(st.session_state.get("show_app_detail"))
    c1, c2 = st.columns([3, 1])
    with c1:
        current = st.selectbox(
            "Gespeicherte Stellen",
            list(labels),
            format_func=labels.get,
            key="current_app",
            help="Wähle eine Stelle und öffne sie, um Lebenslauf und Schreiben zu erstellen.",
        )
    with c2:
        st.write("")  # Ausrichtung zum Selectbox-Label
        st.write("")
        if show_detail:
            if st.button("Schliessen", key="hide_app_detail", width="stretch"):
                st.session_state["show_app_detail"] = False
                st.rerun()
        else:
            if st.button("Stelle öffnen", type="primary", key="show_app_detail_btn", width="stretch"):
                st.session_state["show_app_detail"] = True
                st.rerun()

    if show_detail:
        render_application(current)
    else:
        st.caption(f"{len(apps)} Stelle(n) gespeichert. Nach dem Prüfen eines neuen Links "
                   "öffnet sich die Detailansicht automatisch – oder oben «Stelle öffnen».")
