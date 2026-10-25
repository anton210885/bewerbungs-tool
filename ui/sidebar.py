import streamlit as st

from src import backup, config, cv_builder, models, profiles, settings
from ui import state as S


def _bullets(items: list) -> str:
    return "".join(f"\n- {x}" for x in items if str(x).strip())


def _render_full_profile() -> None:
    """Vollständige Profilansicht (für Dialog und ggf. andere Stellen)."""
    p = S.profile.get("persoenlich") or {}
    stellen = cv_builder.stellen_aufgaben(S.profile)

    st.markdown(f"### {p.get('name') or S.NAME}")
    if p.get("titel"):
        st.caption(p["titel"])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Persönliche Daten**")
        lines = [
            f"{p.get('strasse', '')}".strip(),
            " ".join(filter(None, [p.get("plz"), p.get("ort")])),
            p.get("telefon", ""),
            p.get("email", ""),
            p.get("linkedin", ""),
        ]
        st.markdown(_bullets([x for x in lines if x]) or "_Keine Angaben_")
        for label, key in (("Geburtsdatum", "geburtsdatum"), ("Nationalität", "nationalitaet"),
                           ("Bewilligung", "bewilligung"), ("Zivilstand", "zivilstand"),
                           ("Führerausweis", "fuehrerausweis")):
            if p.get(key):
                st.caption(f"{label}: {p[key]}")
    with c2:
        if kurz := (S.profile.get("kurzprofil") or "").strip():
            st.markdown("**Kurzprofil**")
            st.write(kurz)
        if hobbies := cv_builder.hobbies(S.profile):
            st.markdown("**Hobbies**")
            st.markdown(_bullets(hobbies))

    st.markdown(f"**Berufserfahrung ({len(stellen)})**")
    for s in stellen:
        zeit = f"{s['von']} – {s['bis'] or 'heute'}"
        with st.container(border=True):
            st.markdown(f"**{s['position']}** · {s['firma']}"
                        + (f", {s['ort']}" if s["ort"] else "") + f"  \n`{zeit}`")
            cols = st.columns(2)
            with cols[0]:
                if s["erfolge"]:
                    st.markdown("*Erfolge*")
                    for item in s["erfolge"]:
                        q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                        st.markdown(f"- ★ {item['text']}" + (f" · `{q}`" if q else ""))
            with cols[1]:
                if s["aufgaben"]:
                    st.markdown("*Aufgaben*")
                    for item in s["aufgaben"]:
                        q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                        st.markdown(f"- {item['text']}" + (f" · `{q}`" if q else ""))

    a1, a2 = st.columns(2)
    with a1:
        if ausbildung := S.profile.get("ausbildung") or []:
            st.markdown(f"**Ausbildung ({len(ausbildung)})**")
            for a in ausbildung:
                st.markdown(f"- **{a.get('abschluss', '')}** – {a.get('institution', '')}"
                            + (f", {a.get('ort')}" if a.get("ort") else "")
                            + f" ({a.get('von', '')} – {a.get('bis') or 'heute'})")
        if zert := S.profile.get("zertifikate") or []:
            st.markdown(f"**Weiterbildung & Zertifikate ({len(zert)})**")
            for z in zert:
                if isinstance(z, dict):
                    st.markdown(f"- {z.get('name', '')}" + (f" ({z.get('jahr')})" if z.get("jahr") else ""))
                else:
                    st.markdown(f"- {z}")
    with a2:
        skills = S.profile.get("skills") or {}
        if skills.get("fachlich") or skills.get("software"):
            st.markdown("**Kenntnisse**")
            if skills.get("fachlich"):
                st.markdown("Fachlich:" + _bullets(skills["fachlich"]))
            if skills.get("software"):
                st.markdown("Software:" + _bullets(skills["software"]))
        if sprachen := S.profile.get("sprachen") or []:
            st.markdown("**Sprachen**")
            for s in sprachen:
                if isinstance(s, dict):
                    st.markdown(f"- {s.get('sprache', '')}" + (f" ({s.get('niveau')})" if s.get("niveau") else ""))
                else:
                    st.markdown(f"- {s}")

    if bewertungen := [b for b in (S.profile.get("bewertungen") or []) if isinstance(b, dict) and b.get("zitat")]:
        st.markdown(f"**Zeugnis-Zitate ({len(bewertungen)})**")
        for b in bewertungen:
            st.markdown(f"> {b['zitat']}  \n> — {b.get('firma', '')}")

    wuensche = S.profile.get("wuensche") or {}
    if any(wuensche.get(k) for k in ("wunschberufe", "pensum", "lohn", "region", "verfuegbarkeit", "sonstiges")):
        st.markdown("**Wünsche**")
        if wuensche.get("wunschberufe"):
            st.markdown("Berufe:" + _bullets(wuensche["wunschberufe"]))
        for label, key in (("Pensum", "pensum"), ("Lohn", "lohn"), ("Region", "region"),
                           ("Verfügbarkeit", "verfuegbarkeit"), ("Sonstiges", "sonstiges")):
            if wuensche.get(key):
                st.caption(f"{label}: {wuensche[key]}")

    if weitere := (S.profile.get("weitere_infos") or "").strip():
        st.markdown("**Weitere Infos**")
        st.write(weitere)

    st.caption("Zum Bearbeiten: Reiter „Meine Unterlagen“ → Profil ansehen und bearbeiten.")


@st.dialog("Mein Profil – Vollansicht", width="large")
def _profile_dialog() -> None:
    _render_full_profile()
    if st.button("Schliessen", width="stretch"):
        st.rerun()


def _reset_session() -> None:
    """Nach einem Personenwechsel nichts aus der vorherigen Person anzeigen (gewählte Stelle, Fotos ...)."""
    for key in list(st.session_state):
        if key != "nav_page":
            del st.session_state[key]


def _person_section() -> None:
    people = profiles.list_profiles()
    active = config.active_profile()
    names = {p["slug"]: p["name"] for p in people}
    slug_of = {p["name"]: p["slug"] for p in people}
    # Schlüssel pro aktiver Person: nach einem Wechsel startet die Auswahl frisch auf der neuen Person
    chosen = st.selectbox("Wer nutzt das Tool gerade?", list(slug_of), index=list(slug_of).index(names[active]),
                          key=f"person_select_{active}",
                          help="Jede Person hat eigene Unterlagen, Lebensläufe, Fotos, Suchen und einen eigenen "
                               "Tracker. API-Zugang und Kosten gelten für alle.")
    if slug_of[chosen] != active:
        profiles.switch(slug_of[chosen])
        _reset_session()
        st.rerun()
    with st.expander("Personen verwalten", expanded=False):
        with st.form("person_new", clear_on_submit=True):
            new_name = st.text_input("Neue Person", placeholder="z.B. Marco")
            if st.form_submit_button("Anlegen und wechseln", width="stretch"):
                try:
                    profiles.switch(profiles.create(new_name))
                    _reset_session()
                    st.session_state["notice"] = (f"Person «{new_name.strip()}» angelegt. Lade jetzt unter "
                                                  "„1. Meine Unterlagen“ ihren Lebenslauf hoch.")
                    st.session_state["nav_page"] = "unterlagen"
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        with st.form("person_rename"):
            renamed = st.text_input("Name der aktuellen Person", value=names[active])
            if st.form_submit_button("Umbenennen", width="stretch") and renamed.strip() != names[active]:
                try:
                    profiles.rename(active, renamed)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        if len(people) > 1:
            confirm = st.checkbox(f"Ja, «{names[active]}» mit allen Unterlagen entfernen", key="person_delete_ok")
            if st.button("Aktuelle Person entfernen", disabled=not confirm, width="stretch"):
                profiles.delete(active)
                _reset_session()
                st.session_state["notice"] = (f"«{names[active]}» entfernt. Die Daten liegen noch im Ordner "
                                              "data/geloeschte_profile, falls du sie zurückholen willst.")
                st.rerun()


def _profile_section() -> None:
    st.subheader("Mein Profil")
    if not S.PROFILE_READY:
        st.caption("Noch kein Profil. Lade unter „Meine Unterlagen“ deinen Lebenslauf hoch.")
        return

    p = S.profile.get("persoenlich") or {}
    stellen = cv_builder.stellen_aufgaben(S.profile)
    n_aufgaben = sum(len(s["aufgaben"]) + len(s["erfolge"]) for s in stellen)
    st.markdown(f"**{p.get('name') or S.NAME}**")
    if p.get("titel"):
        st.caption(p["titel"])
    st.caption(
        f"{n_aufgaben} Aufgaben · {len(stellen)} Stellen · "
        f"{len(S.profile.get('ausbildung') or [])} Ausbildungen"
    )
    if st.button("Vollansicht öffnen", type="primary", width="stretch", key="profile_fullview"):
        _profile_dialog()


def _detect_provider(base_url: str) -> str:
    url = (base_url or "").lower()
    if "venice.ai" in url:
        return "Venice AI"
    if "openai.com" in url:
        return "OpenAI"
    return "Eigen / anderer Anbieter"


@st.dialog("API & KI – Einstellungen", width="large")
def _api_settings_dialog() -> None:
    current = config.api_settings()
    st.caption(f"Gespeichert in `{config.ENV_PATH}` (nur lokal, nicht im Git).")

    provider = st.selectbox(
        "Anbieter",
        list(config.PROVIDERS),
        index=list(config.PROVIDERS).index(_detect_provider(current["LLM_BASE_URL"])),
        key="api_provider",
    )
    preset = config.PROVIDERS[provider]
    st.caption(preset["hinweis"])

    country = st.radio("Land", ["ch", "de"], horizontal=True,
                       index=0 if current["COUNTRY"] != "de" else 1,
                       format_func=lambda c: "Schweiz" if c == "ch" else "Deutschland",
                       key="api_country")
    suggested_url = preset["LLM_BASE_URL"] or current["LLM_BASE_URL"]
    base_url = st.text_input(
        "API-Basis-URL",
        value=config.normalize_base_url(suggested_url),
        key="api_base_url",
        help="OpenAI: https://api.openai.com/v1  ·  Venice: https://api.venice.ai/api/v1  "
             "(nicht die Website /api-keys)",
    )
    if "platform.openai.com" in base_url or base_url.rstrip("/").endswith("/api-keys"):
        st.error("Das ist die Key-Verwaltungsseite, nicht die API. Bitte `https://api.openai.com/v1` verwenden.")
    api_key = st.text_input(
        "API-Schlüssel",
        value="",
        type="password",
        placeholder="Leer lassen = bisherigen Schlüssel behalten",
        key="api_key",
        help=f"Aktuell: {config.mask_secret(current['LLM_API_KEY'])}",
    )
    st.caption(f"Aktueller Schlüssel: `{config.mask_secret(current['LLM_API_KEY'])}`")
    default_model = preset["LLM_MODEL"] or current["LLM_MODEL"] or models.current_model()
    if provider == "OpenAI" and str(default_model).startswith("claude"):
        default_model = "gpt-4o-mini"
    model = st.text_input("Standard-Modell (Text)", value=default_model, key="api_model")
    vision = st.text_input("Vision-Modell (Bilder/Scans, optional)",
                           value=current["LLM_VISION_MODEL"] or (default_model if provider == "OpenAI" else ""),
                           key="api_vision",
                           help="Leer = gleiches Modell wie oben, bzw. automatische Wahl.")

    st.markdown("**Adzuna** (optionale Stellensuche)")
    a1, a2 = st.columns(2)
    adzuna_id = a1.text_input("Adzuna App ID", value=current["ADZUNA_APP_ID"], key="api_adzuna_id")
    adzuna_key = a2.text_input("Adzuna App Key", value="", type="password", key="api_adzuna_key",
                               placeholder="Leer = bisherigen Key behalten",
                               help=f"Aktuell: {config.mask_secret(current['ADZUNA_APP_KEY'])}")

    c1, c2, c3 = st.columns(3)
    if c1.button("Speichern", type="primary", width="stretch"):
        values = {
            "COUNTRY": country,
            "LLM_BASE_URL": config.normalize_base_url(base_url),
            "LLM_API_KEY": api_key.strip() or current["LLM_API_KEY"],
            "LLM_MODEL": model.strip() or config.DEFAULTS["LLM_MODEL"],
            "LLM_VISION_MODEL": vision.strip(),
            "ADZUNA_APP_ID": adzuna_id.strip(),
            "ADZUNA_APP_KEY": adzuna_key.strip() or current["ADZUNA_APP_KEY"],
        }
        try:
            config.save_api_settings(values)
            models.set_model(values["LLM_MODEL"])
            if models.CACHE_PATH.exists():
                models.CACHE_PATH.unlink()
            st.session_state["notice"] = (
                f"API-Einstellungen gespeichert ({_detect_provider(values['LLM_BASE_URL'])}, "
                f"{values['LLM_MODEL']})."
            )
            st.rerun()
        except Exception as e:
            st.error(f"Speichern fehlgeschlagen: {e}")
    if c2.button("Verbindung testen", width="stretch"):
        key = api_key.strip() or current["LLM_API_KEY"]
        url = config.normalize_base_url(base_url.strip() or current["LLM_BASE_URL"])
        if not key:
            st.error("Kein API-Schlüssel gesetzt.")
        else:
            try:
                import requests
                resp = requests.get(f"{url}/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
                body = resp.text[:300]
                if resp.status_code == 200 and not body.lstrip().lower().startswith("<"):
                    n = len(resp.json().get("data") or [])
                    st.success(f"Verbindung ok – {n} Modelle erreichbar unter `{url}`.")
                else:
                    st.error(config.friendly_api_error(ValueError(body))
                             if "<" in body else f"Antwort {resp.status_code}: {body}")
            except Exception as e:
                st.error(config.friendly_api_error(e))
    if c3.button("Ordner mit .env öffnen", width="stretch"):
        settings.open_folder(config.ROOT)


def _api_section() -> None:
    st.subheader("API & KI")
    current = config.api_settings()
    ok = config.llm_configured()
    (st.success if ok else st.warning)(
        f"{'Verbunden' if ok else 'Kein API-Schlüssel'} · {_detect_provider(current['LLM_BASE_URL'])}"
    )
    st.caption(f"URL: `{current['LLM_BASE_URL']}`")
    st.caption(f"Modell: `{models.current_model()}` · Key: `{config.mask_secret(current['LLM_API_KEY'])}`")
    st.caption(f"Datei: `{config.ENV_PATH.name}`")
    if st.button("API-Einstellungen öffnen", type="primary", width="stretch", key="open_api_settings"):
        _api_settings_dialog()


def _model_section() -> None:
    available = models.list_models()
    current = models.current_model()
    if not available:
        st.caption(f"Aktuell: `{current}` (Liste der Modelle nicht verfügbar)")
        return
    by_id = {m["id"]: m for m in available}
    choices = [m for m in models.RECOMMENDED if m in by_id]
    if current not in choices:
        choices.append(current)
    show_all = st.toggle("Alle Modelle anzeigen", key="all_models")
    if show_all:
        only_private = st.toggle("Nur private Modelle", value=True, key="only_private")
        choices = sorted({current, *(m["id"] for m in available if not only_private or m["privacy"] == "private")})

    def label(model_id: str) -> str:
        info = by_id.get(model_id)
        if not info:
            return model_id
        lock = "🔒 " if info["privacy"] == "private" else ""
        return lock + models.RECOMMENDED.get(model_id, info["name"])

    chosen = st.selectbox("Modell für Texte und Analysen", choices, index=choices.index(current),
                          format_func=label, key=f"model_{current}")
    if chosen != current:
        models.set_model(chosen)
        st.rerun()
    if info := by_id.get(current):
        (st.success if info["privacy"] == "private" else st.info)(
            models.PRIVACY_LABELS.get(info["privacy"], info["privacy"]))
        st.caption(f"Preis: ${info['preis_in']} / ${info['preis_out']} pro 1 Mio. Tokens (Eingabe/Ausgabe)"
                   + ("" if info["vision"] else f"  ·  Bilder liest `{models.current_vision_model()}`"))
    st.caption("🔒 = privat. Für Lebenslauf und Zeugnisse empfohlen, wenn dir Datenschutz wichtig ist.")


def _backup_section() -> None:
    days = backup.days_since_last_backup()
    if days is None:
        st.warning("Noch keine Sicherung erstellt. Deine Daten liegen nur auf diesem Computer.")
    elif days >= backup.REMIND_AFTER_DAYS:
        st.warning(f"Letzte Sicherung vor {days} Tagen.")
    else:
        st.caption(f"Letzte Sicherung: vor {days} Tag(en)" if days else "Letzte Sicherung: heute")
    st.caption("Enthält Profil, Unterlagen, Fotos, Tracker und Einstellungen.")
    if st.button("Sicherung im Bewerbungsordner speichern", width="stretch"):
        try:
            path = backup.save_backup_to_folder()
            st.success(f"Gespeichert: {path}")
        except Exception as e:
            st.error(f"Sicherung fehlgeschlagen: {e}")
    if st.button("Sicherung als Download vorbereiten", width="stretch"):
        st.session_state["backup_zip"] = backup.create_backup()
    if zip_bytes := st.session_state.get("backup_zip"):
        st.download_button("Sicherung herunterladen (.zip)", zip_bytes, file_name=backup.backup_filename(),
                           mime="application/zip", type="primary", width="stretch")
    with st.expander("Sicherung wiederherstellen"):
        upload = st.file_uploader("Sicherung (.zip)", type=["zip"], key="restore_zip")
        if upload and st.button("Jetzt wiederherstellen", type="primary", width="stretch"):
            try:
                previous = backup.restore_backup(upload.getvalue())
                st.session_state["notice"] = (f"Sicherung wiederhergestellt. Der vorherige Stand liegt in "
                                              f"`{previous.name}`.")
                st.rerun()
            except Exception as e:
                st.error(f"Wiederherstellen fehlgeschlagen: {e}")


def render() -> None:
    with st.sidebar:
        _person_section()
        st.divider()
        _profile_section()
        st.divider()
        st.header("Einstellungen")
        _api_section()
        # Modellliste/Backup erst laden, wenn aufgeklappt (weniger Arbeit pro Klick)
        with st.expander("KI-Modell", expanded=False):
            _model_section()
        with st.expander("Sicherung", expanded=False):
            _backup_section()
