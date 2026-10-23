"""Erster Prototyp der profilbasierten Stellensuche."""
import streamlit as st

from src import discovery, scraper, skill_search
from src.config import adzuna_configured
from ui import state as S
from ui.helpers import show_analysis, store_job


def render() -> None:
    st.subheader("Passende Stellen für mein Profil · Prototyp")
    st.caption("Nach Berufsbezeichnungen oder deinen Fähigkeiten suchen und Stellen mit deinem Profil vergleichen.")
    st.caption("Suchwünsche werden gespeichert. Gesammelte Treffer bleiben in dieser Sitzung; wichtige Stellen bitte in den Tracker übernehmen.")
    if not S.PROFILE_READY:
        st.info("Erstelle zuerst unter «Meine Unterlagen» dein Profil.")
        return
    preferences = discovery.load_preferences(S.profile)
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
    if preferences.get("search_mode") != "Berufe":
        st.caption("Die Fähigkeiten werden als Portal-Suchbegriffe übergeben. Ob auch der Inseratstext durchsucht wird, "
                   "bestimmt das Portal. Der Profilvergleich beurteilt anschliessend die geladenen Aufgaben und Anforderungen.")
    match_wishes = skill_search.evaluation_wishes(preferences)

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
                found, errors = scraper.search(preferences, sources, pages, detail_limit, on_progress=st.write)
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
                items, errors = discovery.search_api(preferences)
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

    for item in sorted(items, key=lambda j: (j.get("analysis") or {}).get("score", -1), reverse=True):
        key = item["_key"]
        score = (item.get("analysis") or {}).get("score")
        label = f"{item['title']} · {item.get('company') or '?'}"
        if score is not None:
            label = f"{score} % · " + label
        with st.expander(label):
            st.caption(f"{item.get('source', '')} · {item.get('location', '')}")
            if item.get("search_terms"):
                st.caption("Gefunden über: " + ", ".join(item["search_terms"]))
            if preferences.get("search_mode", "Berufe") != "Berufe":
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
                show_analysis(item["analysis"])
                changed = body != item.get("description", "") or full == item.get("preliminary", True)
                if changed:
                    st.caption("Text oder Vollständigkeit geändert – vor dem Übernehmen erneut bewerten.")
                if st.button("In den Bewerbungstracker übernehmen", key=f"store_{key}", disabled=changed):
                    meta = {**item, "external_id": item.get("external_id") or key}
                    app_id = store_job(item.get("url", ""), item, item["analysis"], meta)
                    st.session_state["current_app"] = app_id
                    st.success("Im Tracker gespeichert.")
    if st.button("Gesammelte Treffer leeren"):
        st.session_state.pop("discovery_items", None)
        st.rerun()


def _merge(new: list[dict]) -> None:
    import hashlib
    existing = st.session_state.get("discovery_items", [])
    combined = discovery.deduplicate(existing + new)
    for item in combined:
        identity = item.get("url") or "|".join(item.get(k, "") for k in ("title", "company", "location"))
        item.setdefault("_key", hashlib.sha256(identity.encode()).hexdigest()[:20])
        item.setdefault("preliminary", True)
    st.session_state["discovery_items"] = combined
