import streamlit as st

from src import backup, cv_builder, models
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


def _model_section() -> None:
    st.subheader("KI-Modell")
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
    st.subheader("Sicherung")
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
        _profile_section()
        st.divider()
        st.header("Einstellungen")
        _model_section()
        st.divider()
        _backup_section()
