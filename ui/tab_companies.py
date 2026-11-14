"""Stellen holen – Reiter «Firmen in der Umgebung»: Firmen, Karriereseiten, Stellen holen (Liste unter «Stellen ansehen»)."""
from datetime import datetime

import pandas as pd
import streamlit as st

from src import companies, company_jobs, discovery
from ui import state as S


def _search_form(data: dict) -> None:
    prefs = discovery.load_preferences(S.profile or {})
    c1, c2 = st.columns([2, 1])
    place = c1.text_input("Ort", value=data.get("ort") or prefs.get("location", ""), key="companies_place",
                          placeholder="z.B. Lenzburg")
    radius = c2.slider("Umkreis (km)", 5, companies.MAX_RADIUS_KM,
                       min(int(data.get("radius") or prefs.get("radius") or 20), companies.MAX_RADIUS_KM),
                       step=5, key="companies_radius")
    branchen = st.multiselect("Branchen", list(companies.BRANCHEN), key="companies_branches",
                              default=[b for b in data.get("branchen", companies.STANDARD_BRANCHEN)
                                       if b in companies.BRANCHEN])
    if st.button("Firmen suchen", type="primary" if not data["firmen"] else "secondary",
                 disabled=not place.strip() or not branchen):
        with st.spinner("Frage OpenStreetMap ab ..."):
            try:
                found = companies.find_companies(place.strip(), radius, branchen)
            except (ValueError, RuntimeError) as error:
                st.error(str(error))
                return
        data["firmen"], added = companies.merge(data["firmen"], found)
        data.update(ort=place.strip(), radius=radius, branchen=branchen, zentrum=None)
        companies.save(data)
        st.session_state["companies_message"] = (f"{len(found)} Firmen mit Webseite gefunden, davon {added} neu. "
                                                 "Jetzt die Karriereseiten suchen lassen.")
        st.rerun()


def _check_controls(data: dict) -> None:
    open_count = sum(1 for c in data["firmen"] if c.get("status") == "offen" and not c.get("ausgeblendet"))
    c1, c2 = st.columns([1, 1])
    recheck = c2.checkbox("Auch bereits geprüfte Firmen nochmals prüfen", key="companies_recheck")
    total = sum(1 for c in data["firmen"] if not c.get("ausgeblendet")) if recheck else open_count
    if c1.button(f"Karriereseiten suchen ({total})", type="primary" if open_count else "secondary",
                 disabled=total == 0, width="stretch"):
        bar = st.progress(0.0, text="Starte ...")

        def progress(done, count, company):
            bar.progress(done / count, text=f"{done} von {count}: {company['name']}")

        counts = companies.check_career_pages(data, recheck=recheck, on_progress=progress)
        st.session_state["companies_message"] = (
            f"Fertig: {counts['gefunden']} Karriereseiten gefunden, {counts['keine']} ohne Treffer, "
            f"{counts['fehler']} nicht erreichbar, {counts['gesperrt']} mit Abrufverbot.")
        st.rerun()


def _table(data: dict) -> None:
    status_labels = companies.STATUS
    c1, c2, c3 = st.columns(3)
    status_filter = c1.multiselect("Status", list(status_labels.values()), key="companies_status_filter",
                                   placeholder="alle")
    branches = sorted({c.get("branche") or "–" for c in data["firmen"]})
    branch_filter = c2.multiselect("Branche", branches, key="companies_branch_filter", placeholder="alle")
    show_hidden = c3.checkbox("Ausgeblendete zeigen", key="companies_show_hidden")

    rows = [(i, c) for i, c in enumerate(data["firmen"])
            if (show_hidden or not c.get("ausgeblendet"))
            and (not status_filter or status_labels.get(c.get("status"), "") in status_filter)
            and (not branch_filter or (c.get("branche") or "–") in branch_filter)]
    if not rows:
        st.info("Keine Firmen für diese Auswahl.")
        return
    frame = pd.DataFrame([{
        "Firma": c["name"],
        "Karriereseite": c.get("karriere") or "",
        "Status": status_labels.get(c.get("status"), c.get("status", "")),
        "Branche": c.get("branche") or "–",
        "Ort": c.get("ort") or "",
        "Webseite": c["website"],
        "Hinweis": c.get("hinweis", ""),
        "Ausblenden": bool(c.get("ausgeblendet")),
    } for _, c in rows])
    edited = st.data_editor(
        frame, hide_index=True, width="stretch", key="companies_table_" + str(hash(tuple(i for i, _ in rows))),
        disabled=[col for col in frame.columns if col not in ("Ausblenden", "Karriereseite")],
        column_config={
            "Firma": st.column_config.TextColumn(pinned=True),
            "Ausblenden": st.column_config.CheckboxColumn(
                                                          help="Firma interessiert nicht – wird nicht mehr geprüft"),
            "Webseite": st.column_config.LinkColumn(display_text=r"https?://(?:www\.)?([^/]+)"),
            "Karriereseite": st.column_config.LinkColumn(
                help="Zum Öffnen anklicken. Doppelklick zum Korrigieren, falls die Adresse falsch ist."),
        })
    changed = False
    for (_, company), (_, row) in zip(rows, edited.iterrows()):
        hidden = bool(row["Ausblenden"])
        if hidden != bool(company.get("ausgeblendet")):
            company["ausgeblendet"], changed = hidden, True
        career = row["Karriereseite"].strip() if isinstance(row["Karriereseite"], str) else ""
        if career != (company.get("karriere") or ""):
            career = companies.full_url(career)
            company.update(karriere=career, status="gefunden" if career else "keine",
                           hinweis="von Hand korrigiert", quelle_karriere="von Hand")
            changed = True
    if changed:
        companies.save(data)
        st.rerun()  # ausgeblendete Firmen sofort aus der Liste nehmen
    st.caption(f"{len(rows)} von {len(data['firmen'])} Firmen angezeigt.")


def _manual_add(data: dict) -> None:
    with st.expander("Firma von Hand ergänzen"):
        with st.form("companies_add", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name")
            website = c2.text_input("Webseite", placeholder="www.firma.ch")
            career = c3.text_input("Karriereseite (optional)", placeholder="www.firma.ch/jobs")
            if st.form_submit_button("Hinzufügen"):
                try:
                    companies.add_manual(data, name, website, career)
                    companies.save(data)
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))


def _collect(data: dict, store: dict, prefs: dict) -> None:
    bar = st.progress(0.0, text="Lese Karriereseiten ...")
    counts = company_jobs.collect_all(
        data, store, prefs, on_progress=lambda d, n, c: bar.progress(d / n, text=f"Karriereseiten {d} von {n}: {c['name']}"))
    far = _complete(data, store, prefs, bar)
    _, max_km = _center(data, prefs)
    st.session_state["company_jobs_message"] = (
        f"{counts['mit_stellen']} von {counts['firmen']} Firmen haben Stellen ausgeschrieben, {counts['neu']} davon "
        "sind neu. Die Liste ist nach Ähnlichkeit mit deinen Aufgaben sortiert."
        + (f" {far} Stellen liegen weiter als {max_km} km entfernt und sind ausgeblendet." if far else "")
        + (f" {counts['fehler']} Karriereseiten waren nicht erreichbar." if counts["fehler"] else ""))


def _complete(data: dict, store: dict, prefs: dict, bar) -> int:
    """Anzeigentexte laden, fehlende Orte ergänzen, Entfernung prüfen, sortieren. -> Anzahl neu ausgeblendet."""
    tasks = company_jobs.comparison_tasks(prefs)
    center, max_km = _center(data, prefs)
    places = lambda d, n, p: bar.progress(d / n, text=f"Orte nachschlagen {d} von {n}: {p}")  # noqa: E731
    far = company_jobs.apply_distance(store, center, max_km, on_progress=places) if center else 0
    company_jobs.load_details(
        store, S.profile, tasks, on_progress=lambda d, n, j: bar.progress(d / n, text=f"Anzeigentexte {d} von {n}"))
    company_jobs.fill_locations(store, data)  # Anzeigentexte bringen oft erst den Arbeitsort
    if center:
        far += company_jobs.apply_distance(store, center, max_km, on_progress=places)
    bar.progress(1.0, text="Sortiere nach deinen Aufgaben ...")
    company_jobs.rank_open(store, S.profile, tasks)
    return far


def _center(data: dict, prefs: dict):
    """Mittelpunkt der Firmensuche und erlaubte Entfernung (grösserer der beiden Umkreise + 10 km Spielraum)."""
    max_km = max(int(data.get("radius") or 0), int(prefs.get("radius") or 0)) + 10
    if not data.get("zentrum") and data.get("ort"):
        try:
            found = companies.geocode(data["ort"])
            data["zentrum"] = [found["lat"], found["lon"]]
            companies.save(data)
        except (ValueError, RuntimeError):
            return None, max_km
    return (tuple(data["zentrum"]) if data.get("zentrum") else None), max_km


def _jobs_section(data: dict) -> None:
    st.markdown("**Schritt 3 · Stellen bei diesen Firmen holen**")
    store = company_jobs.load()
    prefs = discovery.load_preferences(S.profile or {})
    targets = sum(1 for c in data["firmen"] if c.get("karriere") and not c.get("ausgeblendet"))
    st.caption("Liest die Karriereseiten und erkennt die einzelnen Stellen. Kosten: unter 0.1 Rappen pro Firma; "
               "unveränderte Seiten werden ohne KI übersprungen. Verworfene Stellen kommen nicht wieder.")
    if message := st.session_state.pop("company_jobs_message", None):
        from ui.tab_jobdb import show_newest
        m1, m2 = st.columns([3, 1])
        m1.success(message)
        m2.button("Stellen ansehen →", key="companies_show", on_click=show_newest, type="primary",
                  width="stretch")
    c1, c2 = st.columns([1, 1])
    if c1.button(f"Stellen bei {targets} Firmen holen", type="primary", width="stretch",
                 disabled=not targets or not S.LLM_OK,
                 help=None if S.LLM_OK else "Zuerst den KI-Zugang unter Einstellungen eintragen."):
        _collect(data, store, prefs)
        st.rerun()
    missing = company_jobs.missing_details(store)
    if missing and c2.button(f"Fehlende Anzeigentexte laden ({len(missing)})", width="stretch",
                             help="Lädt nur die Anzeigen, von denen bisher nur der Titel bekannt ist, ohne die "
                                  "Karriereseiten neu zu lesen. Danach werden Orte ergänzt."):
        far = _complete(data, store, prefs, st.progress(0.0, text="Lade Anzeigentexte ..."))
        st.session_state["company_jobs_message"] = (
            f"Anzeigentexte geladen ({len(missing) - len(company_jobs.missing_details(store))} von {len(missing)})."
            + (f" {far} Stellen liegen zu weit weg und sind ausgeblendet." if far else ""))
        st.rerun()
    if store.get("zeit"):
        open_count = len(company_jobs.open_jobs(store))
        st.caption(f"Zuletzt geholt: {datetime.fromisoformat(store['zeit']).strftime('%d.%m. %H:%M')} · "
                   f"{open_count} offene Stellen, zu sehen unter «Stellen ansehen».")


def render() -> None:
    st.caption("Viele Firmen schreiben Stellen nur auf der eigenen Webseite aus. Das Tool sucht Firmen mit "
               "Webseite in OpenStreetMap, findet ihre Karriereseiten und holt die Stellen von dort. Kleine Firmen "
               "fehlen in OpenStreetMap oft – die kannst du von Hand ergänzen.")
    data = companies.load()
    if message := st.session_state.pop("companies_message", None):
        st.success(message)
    st.markdown("**Schritt 1 · Firmen suchen**")
    with st.expander(f"Ort und Umkreis: {data.get('ort') or 'noch nicht gesucht'}"
                     + (f", {data.get('radius')} km" if data.get("radius") else ""), expanded=not data["firmen"]):
        _search_form(data)
    if not data["firmen"]:
        return
    with_career = sum(1 for c in data["firmen"] if c.get("karriere") and not c.get("ausgeblendet"))
    st.markdown("**Schritt 2 · Karriereseiten finden**")
    with st.expander(f"Firmenliste: {len(data['firmen'])} Firmen, {with_career} mit Karriereseite"):
        _check_controls(data)
        _table(data)
        _manual_add(data)
    _jobs_section(data)
