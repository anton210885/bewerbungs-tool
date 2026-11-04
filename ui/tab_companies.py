"""Firmen in der Umgebung und ihre Karriereseiten (Stufe 1, ohne KI)."""
import pandas as pd
import streamlit as st

from src import companies, discovery
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
        data.update(ort=place.strip(), radius=radius, branchen=branchen)
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


def render() -> None:
    st.subheader("Firmen in der Umgebung")
    st.caption("Viele Firmen schreiben Stellen nur auf der eigenen Webseite aus. Das Tool sucht Firmen mit "
               "Webseite in OpenStreetMap und findet ihre Karriereseiten. Ohne KI, kostenlos. Kleine Firmen fehlen "
               "in OpenStreetMap oft – die kannst du von Hand ergänzen.")
    data = companies.load()
    message = st.session_state.pop("companies_message", None)
    if message:
        st.success(message)
    with st.expander("Firmen suchen", expanded=not data["firmen"]):
        _search_form(data)
    if not data["firmen"]:
        return
    _check_controls(data)
    _table(data)
    _manual_add(data)
