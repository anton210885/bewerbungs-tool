"""Firmen in der Umgebung, ihre Karriereseiten und die Stellen dort."""
from datetime import datetime

import pandas as pd
import streamlit as st

from src import companies, company_jobs, discovery, skill_search
from ui import state as S
from ui.helpers import show_analysis, store_job


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
    tasks = company_jobs.comparison_tasks(prefs)
    center, max_km = _center(data, prefs)
    places = lambda d, n, p: bar.progress(d / n, text=f"Orte nachschlagen {d} von {n}: {p}")  # noqa: E731
    far = company_jobs.apply_distance(store, center, max_km, on_progress=places) if center else 0
    company_jobs.load_details(
        store, S.profile, tasks, on_progress=lambda d, n, j: bar.progress(d / n, text=f"Anzeigentexte {d} von {n}"))
    if center:  # Anzeigentexte bringen oft erst den Arbeitsort
        far += company_jobs.apply_distance(store, center, max_km, on_progress=places)
    bar.progress(1.0, text="Sortiere nach deinen Aufgaben ...")
    company_jobs.rank_open(store, S.profile, tasks)
    st.session_state["company_jobs_message"] = (
        f"{counts['mit_stellen']} von {counts['firmen']} Firmen haben Stellen ausgeschrieben, {counts['neu']} davon "
        "sind neu. Die Liste ist nach Ähnlichkeit mit deinen Aufgaben sortiert."
        + (f" {far} Stellen liegen weiter als {max_km} km entfernt und sind ausgeblendet." if far else "")
        + (f" {counts['fehler']} Karriereseiten waren nicht erreichbar." if counts["fehler"] else ""))


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


def _job_item(store: dict, job: dict, wishes: str) -> None:
    url = job["url"]
    score = (job.get("analysis") or {}).get("score")
    match = job.get("aufgaben_match") or {}
    known_text = len(job.get("description", "")) >= company_jobs.MIN_TEXT
    label = (f"{job.get('title') or 'Ohne Titel'} · {job.get('company', '')}" + (f" · {job['location']}" if job.get("location") else "")
             + (f" ({job['distanz_km']} km)" if job.get("distanz_km") is not None else ""))
    if score is not None:
        label = f"**{score} %** · {label}"
    elif match and known_text:
        label = f"Aufgaben-Nähe {match['naehe']} % · {label}"
    with st.expander(label):
        st.link_button("Anzeige öffnen", url)
        if job.get("detail_fehler"):
            st.caption(f"Anzeigentext nicht geladen: {job['detail_fehler']}. Bitte selbst ansehen.")
        elif match and known_text:
            st.write(f"**Aufgaben-Nähe: {match['naehe']} %** – {match['abgedeckt']} von {match['abschnitte']} "
                     "Abschnitten der Anzeige passen deutlich zu deinen Aufgaben.")
            if match.get("passende_aufgaben"):
                st.caption("Am ähnlichsten aus deinem Profil:" + "".join(f"\n- {t}" for t in match["passende_aufgaben"]))
        if job.get("analysis"):
            show_analysis(job["analysis"])
        b1, b2 = st.columns(2)
        if job.get("analysis"):
            if b1.button("In den Tracker übernehmen", type="primary", key=f"cj_take_{url}"):
                meta = {"source": "Firmenseite", "external_id": url, "company": job["company"],
                        "location": job.get("location", "")}
                st.session_state["current_app"] = store_job(url, job, job["analysis"], meta)
                company_jobs.set_status(store, url, "übernommen")
                st.session_state["notice"] = (f"„{job['title']}“ übernommen – weiter unter „2. Stelle prüfen "
                                              "& bewerben“.")
                st.rerun()
        elif b1.button("Diese Stelle bewerten", key=f"cj_eval_{url}", disabled=not (known_text and S.LLM_OK)):
            with st.spinner("Vergleiche mit deinem Profil ..."):
                try:
                    job.update(analysis=discovery.evaluate(S.profile, job, wishes)["analysis"], status="bewertet")
                    company_jobs.save(store)
                    st.rerun()
                except Exception as error:
                    st.error(f"Bewertung fehlgeschlagen: {error}")
        if b2.button("Interessiert mich nicht", key=f"cj_skip_{url}"):
            company_jobs.set_status(store, url, "verworfen")
            st.rerun()


def _jobs_section(data: dict) -> None:
    st.markdown("#### Stellen bei diesen Firmen")
    store = company_jobs.load()
    prefs = discovery.load_preferences(S.profile or {})
    wishes = skill_search.evaluation_wishes({**prefs, "search_mode": "Aufgaben"})
    targets = sum(1 for c in data["firmen"] if c.get("karriere") and not c.get("ausgeblendet"))
    st.caption("Das Tool liest die Karriereseiten, erkennt die einzelnen Stellen und sortiert sie nach Ähnlichkeit "
               "mit deinen Aufgaben. Kosten: unter 0.1 Rappen pro Firma für das Erkennen der Links; unveränderte "
               "Seiten werden ohne KI übersprungen. Verworfene Stellen erscheinen nicht wieder.")
    message = st.session_state.pop("company_jobs_message", None)
    if message:
        st.success(message)
    c1, c2 = st.columns([1, 1])
    if c1.button(f"Stellen bei {targets} Firmen holen", type="primary", width="stretch",
                 disabled=not targets or not S.LLM_OK,
                 help=None if S.LLM_OK else "Zuerst den KI-Zugang unter Einstellungen eintragen."):
        _collect(data, store, prefs)
        st.rerun()
    if store.get("zeit"):
        c2.caption(f"Zuletzt geholt: {datetime.fromisoformat(store['zeit']).strftime('%d.%m. %H:%M')}")

    jobs_open = company_jobs.open_jobs(store)
    if not jobs_open:
        if store.get("zeit"):
            st.info("Keine offenen Stellen. Entweder schreiben die Firmen gerade nichts aus, oder du hast alles "
                    "bearbeitet.")
        return

    ready = len(company_jobs.next_candidates(store, 10_000))
    e1, e2 = st.columns([1, 2])
    count = e1.number_input("Wie viele bewerten?", 1, 25, min(5, max(ready, 1)), key="cj_eval_count")
    if e2.button(f"Die {count} ähnlichsten mit meinem Profil bewerten (ca. {count * 3} Rappen)",
                 disabled=not ready or not S.LLM_OK, width="stretch"):
        bar = st.progress(0.0, text="Bewerte ...")
        errors = company_jobs.evaluate_best(
            store, S.profile, int(count), wishes,
            on_progress=lambda d, n, j: bar.progress(d / n, text=f"{d} von {n}: {j['title']}"))
        for error in errors:
            st.warning(error)
        if not errors:
            st.rerun()
    st.caption(f"{len(jobs_open)} offene Stellen, davon {sum(1 for j in jobs_open if j.get('analysis'))} bewertet "
               f"und {ready} bereit zum Bewerten.")

    f1, f2 = st.columns([2, 1])
    query = f1.text_input("Filtern (Titel, Firma oder Ort)", key="cj_filter").strip().casefold()
    only_rated = f2.checkbox("Nur bewertete", key="cj_only_rated")
    shown = [j for j in jobs_open
             if (not query or query in f"{j['title']} {j['company']} {j.get('location', '')}".casefold())
             and (not only_rated or j.get("analysis"))]
    limit = st.session_state.get("cj_limit", 30)
    for job in shown[:limit]:
        _job_item(store, job, wishes)
    if len(shown) > limit:
        if st.button(f"Weitere anzeigen ({len(shown) - limit} übrig)"):
            st.session_state["cj_limit"] = limit + 30
            st.rerun()


def render() -> None:
    st.subheader("Firmen in der Umgebung")
    st.caption("Viele Firmen schreiben Stellen nur auf der eigenen Webseite aus. Das Tool sucht Firmen mit "
               "Webseite in OpenStreetMap, findet ihre Karriereseiten und holt die Stellen von dort. Kleine Firmen "
               "fehlen in OpenStreetMap oft – die kannst du von Hand ergänzen.")
    data = companies.load()
    message = st.session_state.pop("companies_message", None)
    if message:
        st.success(message)
    with st.expander("Firmen suchen", expanded=not data["firmen"]):
        _search_form(data)
    if not data["firmen"]:
        return
    with_career = sum(1 for c in data["firmen"] if c.get("karriere") and not c.get("ausgeblendet"))
    with st.expander(f"Firmenliste: {len(data['firmen'])} Firmen, {with_career} mit Karriereseite"):
        _check_controls(data)
        _table(data)
        _manual_add(data)
    _jobs_section(data)
