"""Stellen holen – Reiter «Jobportale»: Suchwünsche und die Suche auf Portalen (ohne eigene Trefferliste).

Alles Gefundene wird gespeichert (discovery.save_portal_items) und erscheint unter «Stellen ansehen»."""
from datetime import datetime

import streamlit as st

from src import config, discovery, scraper, skill_search, task_search
from src.config import adzuna_configured
from ui import state as S

METHOD_SCRAPER, METHOD_API, METHOD_ALERT, METHOD_FREE = ("jobs.ch / LinkedIn direkt", "Adzuna-Schnittstelle",
                                                         "Job-Alert-E-Mail", "Freie Suche")
LOAD_BATCH = 30  # Anzeigentexte pro Klick; LinkedIn sperrt bei mehr meist ohnehin


def found_message(count: int, errors: list[str] | None = None, key: str = "found") -> None:
    """Rückmeldung nach einer Suche, mit Sprung zur Liste."""
    for error in errors or []:
        st.warning(error)
    if not count:
        st.info("Keine neuen Stellen gefunden.")
        return
    from ui.tab_jobdb import show_newest
    c1, c2 = st.columns([3, 1])
    c1.success(f"{count} Stellen gefunden. Sie stehen jetzt unter «Stellen ansehen».")
    c2.button("Stellen ansehen →", key=f"{key}_show", on_click=show_newest, type="primary", width="stretch")


def _preferences_form(preferences: dict) -> dict:
    available_skills = skill_search.unique(skill_search.profile_skills(S.profile)
                                           + preferences.get("selected_skills", []))
    with st.form("discovery_preferences"):
        mode = st.radio("Wonach suchen?", list(skill_search.MODES),
                        index=skill_search.MODES.index(preferences.get("search_mode", "Berufe")), horizontal=True,
                        help="Berufe: nach Berufsbezeichnungen. Fähigkeiten: nach Kenntnissen. Aufgaben: nach "
                             "Begriffen aus deinen Tätigkeitsfeldern (oben) – findet auch Stellen mit anderem Titel.")
        terms = st.text_area("Berufe / Suchbegriffe (eine Suche pro Zeile)", "\n".join(preferences["terms"]),
                             height=100)
        selected_skills = st.multiselect(
            "Fähigkeiten für die Suche auswählen", available_skills,
            default=preferences.get("selected_skills", [])[:5], max_selections=5,
            help="Aus den Kenntnissen deines Profils. Im Modus Fähigkeiten werden die Berufsbezeichnungen ignoriert.")
        additional_skills = st.text_input("Weitere Fähigkeiten als Suchbegriffe (mit Komma trennen)",
                                          placeholder="z.B. Prozessoptimierung, Kundenberatung, Excel")
        a, b = st.columns([3, 1])
        location = a.text_input("Arbeitsort", preferences["location"])
        radius = b.number_input("Umkreis in km", 0, 200, int(preferences["radius"]), step=5)
        exclude = st.text_input("Ausschliessen (mit Komma trennen)", preferences["exclude"],
                                placeholder="z.B. Praktikum, Lehrstelle")
        wishes = st.text_area("Weitere Wünsche für die Bewertung", preferences["wishes"],
                              placeholder="z.B. 80–100 %, maximal zwei Bürotage, kein Schichtdienst")
        limit = st.slider("Nach einer Suche höchstens so viele gleich mit KI bewerten", 1, 15,
                          int(preferences["limit"]))
        saved = st.form_submit_button("Suchwünsche speichern", type="primary")
    if saved:
        preferences = {**preferences,
                       "terms": list(dict.fromkeys(t.strip() for t in terms.splitlines() if t.strip()))[:5],
                       "location": location.strip(), "radius": radius, "exclude": exclude,
                       "wishes": wishes, "limit": limit, "search_mode": mode,
                       "selected_skills": skill_search.unique(selected_skills + additional_skills.split(","))[:5]}
        discovery.save_preferences(preferences)
        st.success("Suchwünsche gespeichert. Sie gelten für die nächsten Suchen.")
    return preferences


def render() -> None:
    if not S.PROFILE_READY:
        st.info("Erstelle zuerst unter «Meine Unterlagen» dein Profil.")
        return
    preferences = discovery.load_preferences(S.profile)
    active_terms = skill_search.search_terms(preferences)

    st.markdown("**Schritt 1 · Was und wo?**")
    summary = " · ".join(active_terms) if active_terms else "noch keine Suchbegriffe"
    with st.expander(f"Suchwünsche: {summary} · {preferences['location'] or 'kein Ort'}, "
                     f"{preferences['radius']} km", expanded=not active_terms):
        _task_fields(preferences)
        preferences = _preferences_form(preferences)
        active_terms = skill_search.search_terms(preferences)

    st.markdown("**Schritt 2 · Wo suchen?**")
    method = st.radio("Wo suchen?", [METHOD_SCRAPER, METHOD_API, METHOD_ALERT, METHOD_FREE], horizontal=True,
                      key="discovery_method", label_visibility="collapsed")
    match_wishes = skill_search.evaluation_wishes(preferences)
    # Im Modus «Aufgaben» nach Ähnlichkeit mit den eigenen Aufgaben vorsortieren (lädt die besten Anzeigen zuerst)
    compare_tasks = task_search.selected_tasks(preferences.get("task_fields") or [],
                                               preferences.get("selected_fields") or [])
    ranker = ((lambda found: task_search.rank(S.profile, found, compare_tasks))
              if preferences.get("search_mode") == "Aufgaben" else None)

    if method == METHOD_SCRAPER:
        st.caption("Sucht mit deinen Suchwünschen direkt auf den Portalen. Der Umkreis wird bei LinkedIn "
                   "mitgegeben, bei jobs.ch der Arbeitsort. Die Portalbedingungen untersagen automatisiertes "
                   "Auslesen; die Anbindung kann jederzeit ausfallen.")
        sources = st.multiselect("Jobportale", list(scraper.SOURCES), default=list(scraper.SOURCES),
                                 key="scraper_sources")
        a, b, c = st.columns(3)
        pages = a.selectbox("Ergebnisseiten pro Suchbegriff", [1, 2], key="scraper_pages")
        detail_limit = b.slider("Anzeigentexte laden (maximal)", 1, 15, 10, key="scraper_details")
        auto_evaluate = c.checkbox(f"Die besten {preferences['limit']} gleich bewerten", value=S.LLM_OK,
                                   disabled=not S.LLM_OK, key="scraper_auto_evaluate",
                                   help="Kostet ca. 3 Rappen pro Stelle. Bewerten geht auch später unter "
                                        "«Stellen ansehen».")
        if st.button("Jobportale durchsuchen", type="primary", disabled=not (sources and active_terms)):
            with st.status("Suche direkt auf Jobportalen ...", expanded=True) as status:
                found, errors = scraper.search(preferences, sources, pages, detail_limit, on_progress=st.write,
                                               ranker=ranker)
                if auto_evaluate:
                    errors += evaluate_best(found, preferences["limit"], match_wishes)
                _merge(found)
                status.update(label=f"{len(found)} Stellen gefunden", state="complete" if found else "error")
            found_message(len(found), errors, "scraper")
    elif method == METHOD_API:
        st.caption("Verwendet deine Suchwünsche und Adzuna. Pro Suchbegriff bis zu 20 Treffer.")
        if not adzuna_configured():
            st.info("Dafür Adzuna-App-ID und API-Key unter Einstellungen → API & KI eintragen.")
        if st.button("Über Adzuna suchen", type="primary", disabled=not (adzuna_configured() and active_terms)):
            with st.spinner("Suche Stellen ..."):
                items, errors = discovery.search_api(preferences, ranker=ranker)
                _merge(items)
            found_message(len(items), errors, "api")
    elif method == METHOD_ALERT:
        st.caption("Job-Alert bei jobs.ch oder LinkedIn abonnieren, die E-Mail als .eml speichern oder ihren Text "
                   "einfügen. Der Import ruft keine Portal-Links ab. E-Mail-Inhalte werden zur Extraktion an deinen "
                   "KI-Anbieter gesendet.")
        upload = st.file_uploader("Gespeicherte Alert-E-Mail", type=["eml"], key="discovery_email",
                                  max_upload_size=2)
        text = st.text_area("Oder E-Mail-Text einfügen", height=130, key="discovery_alert_text")
        if st.button("Stellen aus dem Alert übernehmen", type="primary",
                     disabled=not (S.LLM_OK and (upload or text.strip()))):
            try:
                with st.spinner("Lese Job-Alert ..."):
                    content = discovery.email_text(upload.getvalue()) if upload else text
                    items = discovery.import_alert(content)
                    _merge(discovery.deduplicate(items, preferences["exclude"]))
                found_message(len(items), key="alert")
            except Exception:
                st.error("Import fehlgeschlagen. E-Mail-Format und KI-Verbindung prüfen oder den Text direkt "
                         "einfügen.")
    else:
        _free_search()

    _saved_items(preferences, compare_tasks, match_wishes)


def evaluate_best(items: list[dict], count: int, wishes: str) -> list[str]:
    """Bewertet die ersten `count` noch unbewerteten Treffer mit Anzeigentext (items sind schon nach Passung
    sortiert) und trägt die Bewertung direkt ein. -> Fehlermeldungen"""
    from src.job_index import HIDDEN
    candidates = [i for i in items if len(i.get("description") or "") >= 150 and not i.get("analysis")
                  and i.get("status", "") not in HIDDEN][:count]
    errors = []
    for number, item in enumerate(candidates, 1):
        st.write(f"Bewertung {number}/{len(candidates)}: {item['title']}")
        try:
            item.update(discovery.evaluate(S.profile, item, wishes))
        except Exception:
            errors.append(f"«{item['title']}»: Bewertung fehlgeschlagen. Später erneut versuchen.")
    return errors


def _by_fit(items: list[dict], compare_tasks: list[str]) -> list[dict]:
    """Dieselben Einträge (nicht Kopien), die zu deinen Aufgaben passendsten zuerst."""
    ranked = task_search.rank(S.profile, items, compare_tasks or None)
    by_url = {i["url"]: i for i in items}
    ordered = [by_url[r["url"]] for r in ranked if r.get("url") in by_url]
    return ordered + [i for i in items if i not in ordered]


def _saved_items(preferences: dict, compare_tasks: list[str], wishes: str) -> None:
    items = discovery.load_portal_items()
    if not items:
        return
    missing = [i for i in items if len(i.get("description") or "") < 150 and scraper.source_of(i.get("url"))]
    st.markdown(f"**Gespeicherte Jobportal-Treffer: {len(items)}**"
                + (f" · bei {len(missing)} ist nur der Titel bekannt" if missing else ""))
    if missing:
        st.caption(f"Ohne Anzeigentext lässt sich eine Stelle nicht bewerten (keine Prozent). «Laden» holt die Texte "
                   f"der {LOAD_BATCH} passendsten – kostenlos – und bewertet danach die besten. LinkedIn bremst nach "
                   "einigen Anzeigen; dann beim nächsten Klick weiter.")
        c1, c2 = st.columns([2, 1])
        evaluate = c2.checkbox(f"Danach die besten {preferences['limit']} bewerten (ca. "
                               f"{preferences['limit'] * 3} Rp.)", value=S.LLM_OK, disabled=not S.LLM_OK,
                               key="portal_load_evaluate",
                               help="Wie viele, stellst du oben unter Suchwünsche ein.")
        if c1.button(f"Fehlende Anzeigentexte laden (die passendsten {LOAD_BATCH})", type="primary",
                     key="portal_load_texts"):
            errors = []
            with st.status("Lade Anzeigentexte ...", expanded=True) as status:
                ordered = _by_fit(items, compare_tasks)
                loaded, errors = scraper.load_missing_texts(ordered, LOAD_BATCH, on_progress=st.write)
                if evaluate and loaded:
                    errors += evaluate_best(_by_fit(items, compare_tasks), preferences["limit"], wishes)
                discovery.save_portal_items(items)
                status.update(label=f"{loaded} Anzeigentexte geladen", state="complete" if loaded else "error")
            for error in errors:
                st.warning(error)
            if loaded:
                from ui.tab_jobdb import show_best
                c1, c2 = st.columns([3, 1])
                c1.success(f"{loaded} Anzeigentexte geladen. Unter «Stellen ansehen» stehen die bewerteten mit "
                           "Prozent oben.")
                c2.button("Stellen ansehen →", key="portal_load_show", on_click=show_best, type="primary",
                          width="stretch")
    with st.expander("Jobportal-Treffer verwalten"):
        st.caption(f"Die neuesten {discovery.MAX_PORTAL_ITEMS} werden behalten. Leeren entfernt sie aus "
                   "«Stellen ansehen»; Stellen im Tracker bleiben.")
        if st.button("Alle Jobportal-Treffer leeren"):
            discovery.clear_portal_items()
            st.rerun()


def _free_search() -> None:
    """Einmalige Suche mit eigenem Stichwort über Adzuna bzw. die Bundesagentur für Arbeit."""
    from dataclasses import asdict

    from src import jobs
    st.caption("Einmal mit einem eigenen Stichwort suchen, unabhängig von den Suchwünschen.")
    c1, c2, c3 = st.columns([2, 2, 1])
    what = c1.text_input("Was (Beruf, Stichwort)", key="free_what")
    where = c2.text_input("Wo (Ort oder PLZ)", key="free_where")
    radius = c3.number_input("Umkreis (km)", 0, 200, 25, step=5, key="free_radius")
    ba = "Bundesagentur für Arbeit (Deutschland)"
    adzuna = f"Adzuna ({config.COUNTRY.upper()})"
    default = ([ba] if config.COUNTRY == "de" else []) + ([adzuna] if adzuna_configured() else [])
    sources = st.multiselect("Quellen", [adzuna, ba], default=default, key="free_sources")
    if config.COUNTRY == "ch" and not adzuna_configured():
        st.info("Für die Schweiz die Adzuna-Keys unter Einstellungen → API & KI eintragen.")
    if st.button("Suchen", type="primary", disabled=not (what and sources), key="free_search"):
        results, errors = [], []
        with st.spinner("Suche läuft ..."):
            for source in sources:
                search = jobs.search_ba if source == ba else jobs.search_adzuna
                try:
                    results += [asdict(job) for job in search(what, where, int(radius))]
                except Exception as error:
                    errors.append(f"{source}: {error}")
        _merge(results)
        found_message(len(results), errors, "free")


def _task_fields(preferences: dict) -> None:
    """Tätigkeitsfelder für den Modus «Aufgaben»: von der KI aus den Profil-Aufgaben vorgeschlagen, abwählbar."""
    fields = preferences.get("task_fields") or []
    active = preferences.get("search_mode") == "Aufgaben"
    with st.expander("Tätigkeitsfelder für die Suche nach Aufgaben", expanded=active and not fields):
        st.caption("Die KI fasst die Aufgaben aus deinem Profil zu Tätigkeitsfeldern zusammen und nennt die Begriffe, "
                   "unter denen solche Stellen ausgeschrieben werden – auch mit anderen Jobtiteln. Danach unten "
                   "«Aufgaben» wählen und speichern.")
        if st.button("Aus meinen Aufgaben neu vorschlagen" if fields else "Aus meinen Aufgaben vorschlagen",
                     disabled=not S.LLM_OK, key="task_fields_suggest"):
            try:
                with st.spinner("KI ordnet deine Aufgaben ..."):
                    fields = task_search.suggest_fields(S.profile)
                preferences.update(task_fields=fields, selected_fields=task_search.recent_fields(S.profile, fields),
                                   task_terms=[])
                discovery.save_preferences(preferences)
                st.rerun()
            except Exception as e:
                st.error(f"Vorschlag fehlgeschlagen: {e}")
        if not fields:
            return
        names = [f["name"] for f in fields]
        chosen = st.multiselect("Für die Suche verwenden", names,
                                default=[n for n in preferences.get("selected_fields") or [] if n in names],
                                key="task_fields_selected")
        if chosen != preferences.get("selected_fields"):
            # Andere Felder → Suchbegriffe wieder aus den Feldern ableiten
            preferences.update(selected_fields=chosen, task_terms=[])
            discovery.save_preferences(preferences)
        for field in fields:
            mark = "✅" if field["name"] in chosen else "⬜"
            st.markdown(f"{mark} **{field['name']}** – " + ", ".join(field["suchbegriffe"]))
        proposed = task_search.search_terms(fields, chosen)
        current = preferences.get("task_terms") or proposed
        options = list(dict.fromkeys(current + [t for f in fields if f["name"] in chosen for t in f["suchbegriffe"]]))
        terms = st.multiselect(f"Suchbegriffe (max. {task_search.MAX_SEARCH_TERMS})", options, default=current,
                               max_selections=task_search.MAX_SEARCH_TERMS, accept_new_options=True,
                               key=f"task_terms_{'|'.join(chosen)}",
                               help="Unpassende Begriffe mit × entfernen, eigene eintippen und mit Enter übernehmen.")
        if terms != current:
            preferences["task_terms"] = terms
            discovery.save_preferences(preferences)


def _merge(new: list[dict]) -> None:
    import hashlib
    # immer aus der Datei: «Stellen ansehen» speichert dort Bewertungen und «Interessiert mich nicht»
    existing = discovery.load_portal_items()
    combined = discovery.deduplicate(existing + new)
    for item in combined:
        identity = item.get("url") or "|".join(item.get(k, "") for k in ("title", "company", "location"))
        item.setdefault("_key", hashlib.sha256(identity.encode()).hexdigest()[:20])
        item.setdefault("preliminary", True)
        item.setdefault("gefunden", datetime.now().isoformat(timespec="minutes"))
    discovery.save_portal_items(combined)
