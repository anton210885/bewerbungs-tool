"""Profilbasierte Stellensuche nach Berufen, Fähigkeiten oder Aufgaben."""
from datetime import datetime

import streamlit as st

from src import config, discovery, scraper, skill_search, task_search
from src.config import adzuna_configured
from ui import state as S
from ui.helpers import show_analysis, store_job


def render() -> None:
    st.subheader("Passende Stellen für mein Profil")
    st.caption("Nach Berufsbezeichnungen, Fähigkeiten oder deinen Aufgaben suchen und Stellen mit deinem Profil "
               "vergleichen.")
    st.caption("Suchwünsche und gesammelte Treffer werden gespeichert (die neuesten "
               f"{discovery.MAX_PORTAL_ITEMS}) und erscheinen auch in der Stellen-Datenbank.")
    if not S.PROFILE_READY:
        st.info("Erstelle zuerst unter «Meine Unterlagen» dein Profil.")
        return
    if st.session_state.get("discovery_items_profile") != config.active_profile():  # auch nach Personenwechsel
        st.session_state["discovery_items"] = discovery.load_portal_items()
        st.session_state["discovery_items_profile"] = config.active_profile()
    preferences = discovery.load_preferences(S.profile)
    _task_fields(preferences)
    available_skills = skill_search.unique(skill_search.profile_skills(S.profile) + preferences.get("selected_skills", []))
    with st.form("discovery_preferences"):
        mode = st.radio("Wonach suchen?", list(skill_search.MODES),
                        index=skill_search.MODES.index(preferences.get("search_mode", "Berufe")), horizontal=True)
        terms = st.text_area("Berufe / Suchbegriffe (eine Suche pro Zeile)", "\n".join(preferences["terms"]), height=100)
        selected_skills = st.multiselect("Fähigkeiten für die Suche auswählen", available_skills,
                                        default=preferences.get("selected_skills", [])[:5], max_selections=5,
                                        help="Aus den Kenntnissen deines Profils. Im Modus Fähigkeiten werden die Berufsbezeichnungen ignoriert.")
        additional_skills = st.text_input("Weitere Fähigkeiten als Suchbegriffe (mit Komma trennen)",
                                         placeholder="z.B. Prozessoptimierung, Kundenberatung, Excel")
        st.caption("Bis zu fünf Suchanfragen pro Portal. Jeder Begriff wird einzeln gesucht. "
                   "Bei «Berufe + Fähigkeiten» werden beide abwechselnd berücksichtigt. "
                   "Weitere Suchbegriffe ergänzen dein Bewerberprofil nicht automatisch.")
        a, b = st.columns([3, 1])
        location = a.text_input("Arbeitsort", preferences["location"])
        radius = b.number_input("Umkreis in km", 0, 200, int(preferences["radius"]), step=5)
        exclude = st.text_input("Ausschliessen (mit Komma trennen)", preferences["exclude"], placeholder="z.B. Praktikum, Lehrstelle")
        wishes = st.text_area("Weitere Wünsche für die Bewertung", preferences["wishes"],
                              placeholder="z.B. 80–100 %, maximal zwei Bürotage, kein Schichtdienst")
        limit = st.slider("Maximal pro Durchlauf mit KI bewerten", 1, 15, int(preferences["limit"]))
        saved = st.form_submit_button("Suchwünsche speichern", type="primary")
    if saved:
        preferences = {"terms": list(dict.fromkeys(t.strip() for t in terms.splitlines() if t.strip()))[:5],
                       "location": location.strip(), "radius": radius, "exclude": exclude,
                       "wishes": wishes, "limit": limit, "search_mode": mode,
                       "selected_skills": skill_search.unique(selected_skills + additional_skills.split(","))[:5]}
        discovery.save_preferences(preferences)
        # Bewertungen sollen nach geänderten Suchwünschen neu erstellt werden.
        for item in st.session_state.get("discovery_items", []):
            item.pop("analysis", None)
        st.success("Suchwünsche gespeichert. Sie werden für die nächsten Suchen verwendet.")

    active_terms = skill_search.search_terms(preferences)
    st.markdown("**Aktive Suchanfragen:** " + (" · ".join(active_terms) if active_terms else "Noch keine – oben auswählen und speichern."))
    if preferences.get("search_mode") not in ("Berufe", "Aufgaben"):
        st.caption("Die Fähigkeiten werden als Portal-Suchbegriffe übergeben. Ob auch der Inseratstext durchsucht wird, "
                   "bestimmt das Portal. Der Profilvergleich beurteilt anschliessend die geladenen Aufgaben und Anforderungen.")
    match_wishes = skill_search.evaluation_wishes(preferences)
    # Im Modus «Aufgaben» nach Ähnlichkeit mit den eigenen Aufgaben sortieren (lädt die besten Anzeigen zuerst)
    compare_tasks = task_search.selected_tasks(preferences.get("task_fields") or [],
                                               preferences.get("selected_fields") or [])
    ranker = ((lambda found: task_search.rank(S.profile, found, compare_tasks))
              if preferences.get("search_mode") == "Aufgaben" else None)

    scraper_tab, api_tab, alert_tab = st.tabs(["Direkt auf Jobportalen suchen", "Stellen über API finden", "Job-Alert importieren"])
    with scraper_tab:
        st.write("Öffentliche Stellenangebote direkt suchen – ohne E-Mail-Import oder Adzuna-Zugang.")
        sources = st.multiselect("Jobportale", list(scraper.SOURCES), default=list(scraper.SOURCES), key="scraper_sources")
        a, b = st.columns(2)
        pages = a.selectbox("Ergebnisseiten pro Suchbegriff", [1, 2], key="scraper_pages")
        detail_limit = b.slider("Anzeigentexte laden (maximal)", 1, 15, 10, key="scraper_details")
        st.caption("Verwendet die oben angezeigten Suchanfragen. Der Umkreis wird bei LinkedIn mitgegeben; "
                   "bei jobs.ch wird nach dem Arbeitsort gesucht. Zugriffssperren werden als Fehler angezeigt. "
                   "Die Portalbedingungen untersagen automatisiertes Auslesen; die Anbindung kann jederzeit ausfallen.")
        auto_evaluate = st.checkbox("Geladene Stellen direkt mit meinem Profil bewerten", value=S.LLM_OK,
                                    disabled=not S.LLM_OK, key="scraper_auto_evaluate")
        if st.button("Jobportale jetzt durchsuchen", type="primary", disabled=not (sources and active_terms)):
            with st.status("Suche direkt auf Jobportalen ...", expanded=True) as status:
                found, errors = scraper.search(preferences, sources, pages, detail_limit, on_progress=st.write,
                                               ranker=ranker)
                if auto_evaluate:
                    candidates = [j for j in found if len(j.get("description", "")) >= 150][:preferences["limit"]]
                    for index, item in enumerate(candidates, 1):
                        st.write(f"Profilvergleich {index}/{len(candidates)}: {item['title']}")
                        try:
                            item.update(discovery.evaluate(S.profile, item, match_wishes))
                        except Exception:
                            errors.append(f"«{item['title']}»: Profilvergleich fehlgeschlagen. Später erneut versuchen.")
                _merge(found)
                status.update(label=f"{len(found)} Stellen gefunden", state="complete" if found else "error")
            for error in errors:
                st.warning(error)
            if found:
                st.success(f"{len(found)} Treffer gesammelt. Die Bewertungen und Anzeigen stehen unten.")
    with api_tab:
        st.caption("Verwendet die gespeicherten Suchwünsche und Adzuna. Pro Suchbegriff werden bis zu 20 Treffer geladen.")
        if not adzuna_configured():
            st.info("Für die API-Suche Adzuna-App-ID und API-Key unter Einstellungen → API & KI eintragen.")
        if st.button("Jetzt passende Stellen suchen", disabled=not (adzuna_configured() and active_terms)):
            with st.spinner("Suche Stellen ..."):
                items, errors = discovery.search_api(preferences, ranker=ranker)
                _merge(items)
            for error in errors:
                st.error(error)
            st.success(f"{len(items)} Treffer nach Ausschlüssen und Zusammenführen.")
    with alert_tab:
        st.caption("Job-Alert bei jobs.ch oder LinkedIn abonnieren. E-Mail als .eml speichern oder ihren Text hier einfügen. "
                   "Der Import ruft keine Portal-Links ab. E-Mail-Inhalte werden zur Extraktion an deinen KI-Anbieter gesendet.")
        upload = st.file_uploader("Gespeicherte Alert-E-Mail", type=["eml"], key="discovery_email", max_upload_size=2)
        text = st.text_area("Oder E-Mail-Text einfügen", height=130, key="discovery_alert_text")
        if st.button("Stellen aus Alert übernehmen", disabled=not (S.LLM_OK and (upload or text.strip()))):
            try:
                with st.spinner("Lese Job-Alert ..."):
                    content = discovery.email_text(upload.getvalue()) if upload else text
                    items = discovery.import_alert(content)
                    _merge(discovery.deduplicate(items, preferences["exclude"]))
                st.success(f"{len(items)} Stellen aus dem Alert erkannt.")
            except Exception:
                st.error("Import fehlgeschlagen. E-Mail-Format und KI-Verbindung prüfen oder den Text direkt einfügen.")

    items = st.session_state.get("discovery_items", [])
    if not items:
        return
    st.markdown(f"**Gesammelte Stellen: {len(items)}**")
    st.caption("Bei API- oder Alert-Treffern und bei nicht geladenen Anzeigentexten ist die Bewertung vorläufig. "
               "Beim Scraper werden die geladenen Inserate zur Bewertung an deinen KI-Anbieter gesendet.")
    if st.button("Nächste Treffer mit meinem Profil bewerten", disabled=not S.LLM_OK):
        candidates = [j for j in items if not j.get("analysis") and len(j.get("description", "")) >= 150][:preferences["limit"]]
        if not candidates:
            st.info("Keine unbewerteten Treffer mit ausreichend Text. Bitte unten Anzeigentexte ergänzen.")
        with st.status(f"Bewerte {len(candidates)} Treffer ..."):
            for item in candidates:
                try:
                    item.update(discovery.evaluate(S.profile, item, match_wishes))
                except Exception:
                    st.warning(f"«{item['title']}» konnte nicht bewertet werden. Später erneut versuchen.")

    def order(job):
        match = job.get("aufgaben_match") or {}
        return ((job.get("analysis") or {}).get("score", -1), match.get("staerke", -1))

    for item in sorted(items, key=order, reverse=True):
        key = item["_key"]
        score = (item.get("analysis") or {}).get("score")
        match = item.get("aufgaben_match")
        label = f"{item['title']} · {item.get('company') or '?'}"
        if score is not None:
            label = f"{score} % · " + label
        elif match and not _only_title(match):
            label = f"Aufgaben-Nähe {match['naehe']} % · " + label
        with st.expander(label):
            st.caption(f"{item.get('source', '')} · {item.get('location', '')}")
            if item.get("search_terms"):
                st.caption("Gefunden über: " + ", ".join(item["search_terms"]))
            if match and _only_title(match):
                st.caption("Aufgaben-Nähe offen: Von dieser Anzeige ist nur der Titel bekannt. Text unten einfügen "
                           "oder mehr Anzeigentexte laden.")
            elif match:
                st.write(f"**Aufgaben-Nähe: {match['naehe']} %** – {match['abgedeckt']} von {match['abschnitte']} "
                         f"Abschnitten der Anzeige passen deutlich zu deinen Aufgaben (Vergleich nach {match['methode']}).")
                if match["passende_aufgaben"]:
                    st.caption("Am ähnlichsten aus deinem Profil:"
                               + "".join(f"\n- {t}" for t in match["passende_aufgaben"]))
            if preferences.get("search_mode", "Berufe") not in ("Berufe", "Aufgaben"):
                matches = skill_search.matching_skills(item, preferences.get("selected_skills") or [])
                st.write("**Im Titel oder Anzeigentext erkannt:** " + (", ".join(matches) if matches else "Noch keine ausgewählte Fähigkeit wörtlich gefunden."))
                st.caption("Wörtliche Texttreffer sind ein Hinweis; sie belegen allein noch keine Eignung für die Stelle.")
            if item.get("url"):
                st.link_button("Anzeige öffnen", item["url"])
            full = st.checkbox("Dies ist der vollständige Anzeigentext", value=not item.get("preliminary", True), key=f"full_{key}")
            body = st.text_area("Anzeigentext prüfen oder ergänzen", item.get("description", ""), height=170, key=f"body_{key}")
            if st.button("Diesen Text bewerten", key=f"evaluate_{key}", disabled=not S.LLM_OK):
                try:
                    with st.spinner("Vergleiche mit deinem Profil ..."):
                        item.update(discovery.evaluate(S.profile, {**item, "description": body, "preliminary": not full}, match_wishes))
                except Exception:
                    st.error("Bewertung fehlgeschlagen. Mindestens 150 Zeichen und eine funktionierende KI-Verbindung werden benötigt.")
            if item.get("analysis"):
                if item.get("preliminary", True):
                    st.info("Vorläufige Bewertung auf Basis des vorhandenen Ausschnitts.")
                show_analysis(item["analysis"], job={**item, "description": body}, source="Jobportale")
                changed = body != item.get("description", "") or full == item.get("preliminary", True)
                if changed:
                    st.caption("Text oder Vollständigkeit geändert – vor dem Übernehmen erneut bewerten.")
                if st.button("In den Bewerbungstracker übernehmen", key=f"store_{key}", disabled=changed):
                    meta = {**item, "external_id": item.get("external_id") or key}
                    app_id = store_job(item.get("url", ""), item, item["analysis"], meta)
                    st.session_state["current_app"] = app_id
                    st.success("Im Tracker gespeichert.")
    discovery.save_portal_items(items)  # Bewertungen und ergänzte Texte behalten
    if st.button("Gesammelte Treffer leeren"):
        st.session_state["discovery_items"] = []
        discovery.clear_portal_items()
        st.rerun()


def _only_title(match: dict) -> bool:
    """Ohne geladenen Anzeigentext ist die Nähe nicht aussagekräftig (unbekannt ist nicht unpassend)."""
    return match["abschnitte"] <= 3


def _task_fields(preferences: dict) -> None:
    """Tätigkeitsfelder für den Modus «Aufgaben»: von der KI aus den Profil-Aufgaben vorgeschlagen, abwählbar."""
    fields = preferences.get("task_fields") or []
    active = preferences.get("search_mode") == "Aufgaben"
    with st.expander("Tätigkeitsfelder für die Suche nach Aufgaben", expanded=active and not fields):
        st.caption("Die KI fasst die Aufgaben aus deinem Profil zu Tätigkeitsfeldern zusammen und nennt die Begriffe, "
                   "unter denen solche Stellen ausgeschrieben werden – auch mit anderen Jobtiteln. Danach oben "
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
    existing = st.session_state.get("discovery_items", [])
    combined = discovery.deduplicate(existing + new)
    for item in combined:
        identity = item.get("url") or "|".join(item.get(k, "") for k in ("title", "company", "location"))
        item.setdefault("_key", hashlib.sha256(identity.encode()).hexdigest()[:20])
        item.setdefault("preliminary", True)
        item.setdefault("gefunden", datetime.now().isoformat(timespec="minutes"))
    st.session_state["discovery_items"] = combined
    discovery.save_portal_items(combined)
