import streamlit as st

from src import batch, db
from ui import state as S
from ui.application import render_application
from ui.helpers import check_job, show_analysis, store_job


def render() -> None:
    if not S.PROFILE_READY:
        st.warning("Lade zuerst unter â€ž1. Meine Unterlagenâ€œ deinen Lebenslauf hoch und erstelle dein Profil.")

    mode = st.radio("Was mÃ¶chtest du prÃ¼fen?", ["Eine Stelle", "Viele Stellen (Ãœbersichtsseite)"],
                    horizontal=True, key="check_mode")

    if mode == "Eine Stelle":
        with st.form("check", clear_on_submit=True):
            url = st.text_input("Link zur Stellenanzeige",
                                placeholder="https://www.jobs.ch/de/stellenangebote/detail/...")
            text = st.text_area("Oder Anzeigentext einfÃ¼gen (falls der Link nicht funktioniert)", height=100)
            checked = st.form_submit_button("Passt diese Stelle zu mir?", type="primary",
                                            disabled=not (S.LLM_OK and S.PROFILE_READY))
        if checked:
            if url.strip() or text.strip():
                check_job(url.strip(), text.strip())
            else:
                st.error("Bitte einen Link oder den Anzeigentext eingeben.")
    else:
        st.caption("FÃ¼ge den Link einer Seite mit vielen Stellen ein, z.B. eine Suchergebnisseite von jobs.ch. "
                   "Die KI sucht die vielversprechendsten heraus, prÃ¼ft sie im Detail und zeigt dir die besten.")
        with st.form("batch"):
            page_url = st.text_input("Link zur Ãœbersichtsseite",
                                     placeholder="https://www.jobs.ch/de/stellenangebote/?term=sachbearbeiter")
            n1, n2 = st.columns(2)
            top_n = n1.slider("Wie viele Stellen anzeigen?", 3, 10, 10)
            detail_n = n2.slider("Wie viele davon im Detail prÃ¼fen?", 5, 25, 15,
                                 help="Mehr = grÃ¼ndlicher, aber teurer (ca. 3 Rappen pro geprÃ¼fte Stelle).")
            go = st.form_submit_button("Passende Stellen finden", type="primary",
                                       disabled=not (S.LLM_OK and S.PROFILE_READY))
        if go and page_url.strip():
            with st.status("Suche passende Stellen ...", expanded=True) as status:
                try:
                    st.write("Lese die Ãœbersichtsseite ...")
                    found = batch.extract_jobs(page_url.strip())
                    if not found:
                        raise ValueError("Auf der Seite wurden keine Stellenanzeigen erkannt.")
                    st.write(f"{len(found)} Stellen gefunden. KI wÃ¤hlt die vielversprechendsten aus ...")
                    chosen = batch.preselect(S.profile, found, max(detail_n, top_n))
                    st.write(f"{len(chosen)} Stellen werden im Detail geprÃ¼ft ...")
                    results, errors = batch.evaluate(S.profile, chosen, on_progress=st.write)
                    st.session_state["batch_results"] = {
                        "results": results[:top_n], "errors": errors, "found": len(found), "checked": len(chosen),
                    }
                    status.update(label=f"Fertig â€“ deine Top {len(results[:top_n])}", state="complete")
                except Exception as e:
                    status.update(label="Fehler", state="error")
                    st.error(f"Das hat nicht geklappt: {e}")

        if batch_data := st.session_state.get("batch_results"):
            results = batch_data["results"]
            st.markdown(f"#### Deine Top {len(results)}")
            st.caption(f"{batch_data['found']} Stellen auf der Seite gefunden, {batch_data['checked']} im Detail geprÃ¼ft.")
            if batch_data["errors"]:
                with st.expander(f"{len(batch_data['errors'])} Stellen konnten nicht geprÃ¼ft werden"):
                    for err in batch_data["errors"]:
                        st.write(err)
            if results and st.button("Alle in den Tracker Ã¼bernehmen"):
                for r in results:
                    store_job(r["url"], r, r["analysis"])
                st.session_state["notice"] = f"{len(results)} Stellen in den Tracker Ã¼bernommen."
                st.rerun()
            for i, r in enumerate(results):
                score = r["analysis"].get("score", 0)
                where = f" Â· {r['location']}" if r["location"] else ""
                with st.expander(f"{score} %  Â·  {r['title']} â€“ {r['company'] or '?'}{where}", expanded=i == 0):
                    show_analysis(r["analysis"])
                    st.markdown(f"[Zur Anzeige]({r['url']})")
                    if st.button("Ãœbernehmen und bewerben", type="primary", key=f"batch_take_{i}"):
                        st.session_state["current_app"] = store_job(r["url"], r, r["analysis"])
                        st.session_state["notice"] = (f"â€ž{r['title']}â€œ Ã¼bernommen â€“ unten kannst du jetzt Lebenslauf "
                                                      "und Bewerbungsschreiben erstellen.")
                        st.rerun()

    apps = db.list_applications()
    if apps:
        st.divider()
        labels = {
            a["id"]: f'{a["title"]} â€“ {a["company"] or "?"}' + (f'  ({a["score"]} %)' if a["score"] is not None else "")
            for a in apps
        }
        if st.session_state.get("current_app") not in labels:
            st.session_state["current_app"] = apps[0]["id"]
        current = st.selectbox("GeprÃ¼fte Stellen", list(labels), format_func=labels.get, key="current_app")
        render_application(current)

