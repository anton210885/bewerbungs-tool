import streamlit as st

from src import backup, cv_builder, models
from ui import state as S


def _bullets(items: list) -> str:
    return "".join(f"\n- {x}" for x in items if str(x).strip())


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

    with st.expander("Persönliche Daten", expanded=True):
        lines = [
            f"{p.get('strasse', '')}".strip(),
            " ".join(filter(None, [p.get("plz"), p.get("ort")])),
            p.get("telefon", ""),
            p.get("email", ""),
            p.get("linkedin", ""),
        ]
        st.markdown(_bullets([x for x in lines if x]) or "_Keine Angaben_")
        extras = [
            ("Geburtsdatum", p.get("geburtsdatum")),
            ("Nationalität", p.get("nationalitaet")),
            ("Bewilligung", p.get("bewilligung")),
            ("Zivilstand", p.get("zivilstand")),
            ("Führerausweis", p.get("fuehrerausweis")),
        ]
        for label, value in extras:
            if value:
                st.caption(f"{label}: {value}")

    if kurz := (S.profile.get("kurzprofil") or "").strip():
        with st.expander("Kurzprofil"):
            st.write(kurz)

    with st.expander(f"Berufserfahrung ({len(stellen)})", expanded=True):
        for s in stellen:
            zeit = f"{s['von']} – {s['bis'] or 'heute'}"
            st.markdown(f"**{s['position']}**  \n{s['firma']}"
                        + (f", {s['ort']}" if s["ort"] else "") + f"  \n`{zeit}`")
            for item in s["erfolge"]:
                q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                st.caption(f"★ {item['text']}" + (f" · {q}" if q else ""))
            for item in s["aufgaben"]:
                q = cv_builder.QUELLE_LABEL.get(item.get("quelle", ""), "")
                st.caption(f"• {item['text']}" + (f" · {q}" if q else ""))
            st.divider()

    if ausbildung := S.profile.get("ausbildung") or []:
        with st.expander(f"Ausbildung ({len(ausbildung)})"):
            for a in ausbildung:
                st.markdown(f"**{a.get('abschluss', '')}**  \n"
                            f"{a.get('institution', '')}"
                            + (f", {a.get('ort')}" if a.get("ort") else "")
                            + f"  \n{a.get('von', '')} – {a.get('bis') or 'heute'}")
                if details := [d for d in (a.get("details") or []) if str(d).strip()]:
                    st.caption(_bullets(details).lstrip("\n"))

    if zert := S.profile.get("zertifikate") or []:
        with st.expander(f"Weiterbildung & Zertifikate ({len(zert)})"):
            for z in zert:
                if isinstance(z, dict):
                    st.caption(f"• {z.get('name', '')}" + (f" ({z.get('jahr')})" if z.get("jahr") else ""))
                else:
                    st.caption(f"• {z}")

    skills = S.profile.get("skills") or {}
    if skills.get("fachlich") or skills.get("software"):
        with st.expander("Kenntnisse"):
            if skills.get("fachlich"):
                st.markdown("**Fachlich**" + _bullets(skills["fachlich"]))
            if skills.get("software"):
                st.markdown("**Software**" + _bullets(skills["software"]))

    if sprachen := S.profile.get("sprachen") or []:
        with st.expander(f"Sprachen ({len(sprachen)})"):
            for s in sprachen:
                if isinstance(s, dict):
                    st.caption(f"• {s.get('sprache', '')}" + (f" ({s.get('niveau')})" if s.get("niveau") else ""))
                else:
                    st.caption(f"• {s}")

    if hobbies := cv_builder.hobbies(S.profile):
        with st.expander(f"Hobbies ({len(hobbies)})"):
            st.markdown(_bullets(hobbies))

    if bewertungen := S.profile.get("bewertungen") or []:
        with st.expander(f"Zeugnis-Zitate ({len(bewertungen)})"):
            for b in bewertungen:
                if isinstance(b, dict) and b.get("zitat"):
                    st.markdown(f"> {b['zitat']}  \n> — {b.get('firma', '')}")

    wuensche = S.profile.get("wuensche") or {}
    if any(wuensche.get(k) for k in ("wunschberufe", "pensum", "lohn", "region", "verfuegbarkeit", "sonstiges")):
        with st.expander("Wünsche"):
            if wuensche.get("wunschberufe"):
                st.markdown("**Berufe**" + _bullets(wuensche["wunschberufe"]))
            for label, key in (("Pensum", "pensum"), ("Lohn", "lohn"), ("Region", "region"),
                               ("Verfügbarkeit", "verfuegbarkeit"), ("Sonstiges", "sonstiges")):
                if wuensche.get(key):
                    st.caption(f"{label}: {wuensche[key]}")

    if weitere := (S.profile.get("weitere_infos") or "").strip():
        with st.expander("Weitere Infos"):
            st.write(weitere)

    st.caption("Bearbeiten: Reiter „Meine Unterlagen“ → Profil ansehen und bearbeiten.")


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
