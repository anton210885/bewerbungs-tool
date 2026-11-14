"""Seite «Stellen-Datenbank»: alle bekannten Stellen durchsuchen – nach Bedeutung statt nach Stichworten."""
import hashlib

import streamlit as st

from src import company_jobs, db, job_index, quality, task_search
from ui import state as S

SOURCE_HELP = "Tracker, Stellen von den Firmenseiten, gespeicherte Suchen und gesammelte Jobportal-Treffer"


def _signature(records: list[dict]) -> str:
    raw = "|".join(f"{r['key']}:{len(r['description'])}:{r['title']}" for r in records)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _index(records: list[dict]):
    """Index nur neu aufbauen, wenn sich die Stellen geändert haben."""
    signature = _signature(records)
    cached = st.session_state.get("jobdb_index")
    if cached and cached[0] == signature:
        return cached[1]
    with st.spinner("Stellen werden für die Suche vorbereitet (neue Anzeigen kosten einmalig unter 0.1 Rappen) ..."):
        index = job_index.build(records)
    if index is not None:
        st.session_state["jobdb_index"] = (signature, index)
    return index


def _open_in_tracker(app_id: int) -> None:
    st.session_state["current_app"] = app_id
    st.session_state["show_app_detail"] = True
    st.session_state["nav_page"] = "bewerben"
    st.session_state["notice"] = "Stelle im Reiter «2. Stelle prüfen & bewerben» geöffnet."


def _take_over(record: dict) -> None:
    app_id = db.add_application({
        "source": record["quelle"], "external_id": record["url"] or record["key"], "title": record["title"],
        "company": record["company"], "location": record["location"], "url": record["url"],
        "description": record["description"],
    })
    if record["quelle"] == "Firmenseite" or "Firmenseite" in record["quellen"]:
        company_jobs.set_status(company_jobs.load(), record["url"], "übernommen")
    if app_id:
        _open_in_tracker(app_id)
        st.session_state["notice"] = (f"„{record['title']}“ in den Tracker übernommen – unter «2. Stelle prüfen & "
                                      "bewerben» analysieren und bewerben.")


def _show_similar(key: str) -> None:
    st.session_state["jobdb_similar"] = key


def _label(r: dict) -> str:
    parts = [r["title"] or "Ohne Titel", r["company"], r["location"]]
    text = " · ".join(p for p in parts if p)
    if r.get("distanz_km") is not None:
        text += f" ({r['distanz_km']} km)"
    prefix = f"**{r['prozent']} %** · " if "prozent" in r else ""
    score = f" · Bewertung {r['score']} %" if r.get("score") is not None else ""
    return f"{prefix}{text}{score}"


def _item(r: dict, index, prefix: str) -> None:
    with st.expander(_label(r)):
        if r.get("passender_abschnitt"):
            st.markdown(f"**Passt am besten:** «{r['passender_abschnitt']}»")
        info = [f"Quelle: {', '.join(r['quellen'])}"]
        if r["status"]:
            info.append(f"Status: {r['status']}")
        if r["nur_titel"]:
            info.append("nur Titel bekannt, kein Anzeigentext")
        doubles = job_index.duplicates_of(index, r["key"])
        if doubles:
            info.append("auch unter: " + ", ".join(f"{d['company'] or '?'} ({d['quelle']})" for d in doubles))
        st.caption(" · ".join(info))
        if r["description"] and not r["nur_titel"]:
            st.write(r["description"][:600] + (" …" if len(r["description"]) > 600 else ""))
        c1, c2, c3 = st.columns(3)
        if r["url"]:
            c1.link_button("Anzeige öffnen", r["url"], width="stretch")
        c2.button("Ähnliche Stellen", key=f"{prefix}_sim_{r['key']}", on_click=_show_similar, args=(r["key"],),
                  width="stretch")
        if r.get("app_id"):
            c3.button("Im Tracker öffnen", key=f"{prefix}_open_{r['key']}", on_click=_open_in_tracker,
                      args=(r["app_id"],), width="stretch")
        else:
            c3.button("In den Tracker übernehmen", key=f"{prefix}_take_{r['key']}", on_click=_take_over,
                      args=(r,), width="stretch", disabled=r["nur_titel"],
                      help="Ohne Anzeigentext nicht möglich – Anzeige öffnen und den Text unter «Stelle prüfen» "
                           "einfügen." if r["nur_titel"] else None)


def _results(results: list[dict], index, prefix: str, empty: str) -> None:
    if not results:
        st.caption(empty)
    for r in results:
        _item(r, index, prefix)


def _similar_section(index, key: str, show_hidden: bool) -> None:
    position = index.position(key)
    if position is None:
        st.session_state.pop("jobdb_similar", None)
        return
    base = index.records[position]
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"#### Ähnlich wie: {base['title']} – {base['company'] or '?'}")
    c2.button("Zurück zur Suche", on_click=lambda: st.session_state.pop("jobdb_similar", None), width="stretch")
    results = job_index.similar(index, key, limit=15, show_hidden=show_hidden)
    _results(results, index, "sim", "Keine deutlich ähnlichen Stellen in der Datenbank.")


def _duplicates(index) -> None:
    groups = job_index.duplicate_groups(index)
    with st.expander(f"Doppelte Stellen ({len(groups)})"):
        st.caption("Dieselbe Anzeige mit gleichem Titel unter verschiedenen Adressen oder Firmennamen, z.B. bei "
                   "jobs.ch und auf der Firmenseite. In den Suchergebnissen steht bei jeder «auch unter: …».")
        for group in groups:
            st.markdown(f"- **{group[0]['title']}**: " + " · ".join(
                f"[{r['company'] or '?'} ({r['quelle']})]({r['url']})" if r["url"] else f"{r['company']} ({r['quelle']})"
                for r in group))
        if not groups:
            st.write("Keine gefunden.")


def render() -> None:
    st.subheader("Stellen-Datenbank")
    st.caption("Alle Stellen, die das Tool schon kennt, an einem Ort – durchsuchbar nach Bedeutung: «Automatisierung "
               "mit Skripten» findet auch «PowerShell-Workflows für den Betrieb». Neue Stellen kommen über die "
               "Stellensuche, die Firmenseiten und gespeicherte Suchen dazu.")
    records = job_index.collect()
    if not records:
        st.info("Noch keine Stellen gespeichert. Hole zuerst Stellen über die Stellensuche oder die Firmenseiten.")
        return
    counts = {}
    for r in records:
        for source in r["quellen"]:
            counts[source] = counts.get(source, 0) + 1
    hidden = sum(r["ausgeblendet"] for r in records)
    st.markdown(f"**{len(records)} Stellen** ({' · '.join(f'{k} {v}' for k, v in counts.items())})"
             + (f", davon {hidden} ausgeblendet (verworfen oder zu weit weg)" if hidden else ""), help=SOURCE_HELP)

    if not task_search.embedding_model():
        st.warning("Die Bedeutungssuche braucht einen Embedding-Zugang (OpenAI oder Venice) unter Einstellungen.")
        return
    index = _index(records)
    if index is None:
        st.error("Die Stellen konnten nicht vorbereitet werden (Embedding-Anbieter nicht erreichbar). "
                 "Später nochmals versuchen.")
        return

    show_hidden = st.checkbox("Auch verworfene und zu weit entfernte Stellen zeigen", key="jobdb_hidden")
    if st.session_state.get("jobdb_similar"):
        _similar_section(index, st.session_state["jobdb_similar"], show_hidden)
        return

    with st.form("jobdb_search"):
        query = st.text_input("Wonach suchst du?", key="jobdb_query",
                              placeholder="z.B. Automatisierung mit Python und PowerShell im Datenbankumfeld")
        st.form_submit_button("Suchen", type="primary")
    liked = [v for v in quality.load_labels().values() if v["rating"] == "passt"]
    if liked and st.button(f"Stellen wie meine 👍 ({len(liked)})", key="jobdb_like",
                           help="Sucht Stellen, die deinen mit «passt» eingeschätzten Stellen am ähnlichsten sind."):
        st.session_state["jobdb_mode"] = "like"
    if query.strip():
        if st.session_state.get("jobdb_last_query") != query:
            st.session_state["jobdb_mode"] = "query"
            st.session_state["jobdb_last_query"] = query

    mode = st.session_state.get("jobdb_mode")
    if mode == "like" and liked:
        st.markdown(f"#### Ähnlich wie deine {len(liked)} 👍-Stellen")
        exclude = {quality.job_key(v["url"], v["description"]) for v in liked}
        results = job_index.like_examples(index, [v["description"][:job_index.JOB_TEXT] for v in liked],
                                          show_hidden=show_hidden, exclude=exclude)
        _results(results, index, "like", "Keine ähnlichen Stellen gefunden.")
    elif query.strip():
        results = job_index.search(index, query, show_hidden=show_hidden)
        st.markdown(f"#### {len(results)} Treffer")
        _results(results, index, "q", "Nichts Passendes. Andere Worte versuchen oder die Anfrage allgemeiner fassen.")
        st.caption("Prozent = Ähnlichkeit der Bedeutung mit deiner Anfrage, keine Bewertung der Passung zu deinem "
                   "Profil. Dafür die Stelle in den Tracker übernehmen und analysieren.")
    _duplicates(index)
