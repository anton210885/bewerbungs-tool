"""Bereich „Analyse deiner Arbeitszeugnisse“ im Reiter „Meine Unterlagen“."""
from pathlib import Path

import pandas as pd
import streamlit as st

from src import documents, zeugnisse
from ui import state as S

WERTUNG_ICONS = {"positiv": "🟢", "neutral": "⚪", "negativ": "🔴"}
SCHWERE_ICONS = {"gering": "🟡", "mittel": "🟠", "hoch": "🔴"}
URTEIL_ICONS = {"sehr gut": "🟢", "gut": "🟢", "befriedigend": "🟡", "genügend": "🟠", "ungenügend": "🔴",
                "fehlt": "⚫"}


def _bullets(title: str, items: list[str]) -> str:
    return f"**{title}**" + "".join(f"\n- {x}" for x in items)


def _box(punkte: int):
    return st.success if punkte >= 8 else st.warning if punkte >= 5 else st.error


def render() -> None:
    docs = documents.active_documents("zeugnisse")
    if not docs:
        return
    st.subheader("Analyse deiner Arbeitszeugnisse")
    missing = [p for p in docs if zeugnisse.load_analysis(p) is None]
    c1, c2 = st.columns([3, 1])
    c1.caption("Die KI liest jedes Zeugnis wie ein erfahrener Personaler: Sie übersetzt die Zeugnissprache in "
               "Klartext, zeigt Stärken und Warnsignale, sagt, welche Zeugnisse ins Dossier gehören, und entwirft "
               "bei Bedarf eine Bitte um Berichtigung an den Arbeitgeber.")
    todo = missing or docs
    label = f"Zeugnisse analysieren ({len(missing)})" if missing else "Alle neu analysieren"
    if c2.button(label, type="primary" if missing else "secondary", width="stretch", disabled=not S.LLM_OK):
        _run(todo)

    items = zeugnisse.all_analyses()
    if not items:
        return
    overview = zeugnisse.load_overview()
    if overview is None and not missing and st.button("Gesamtbild aktualisieren", disabled=not S.LLM_OK):
        _run([])
    if overview:
        _show_overview(overview)

    st.markdown("**Die einzelnen Zeugnisse**")
    st.dataframe(pd.DataFrame([{
        "Aussteller": z.get("aussteller", ""), "Zeitraum": z.get("zeitraum", ""), "Art": z.get("typ", ""),
        "Urteil": f"{URTEIL_ICONS.get(z.get('urteil'), '')} {z.get('urteil', '')}",
        "Punkte": f"{z.get('punkte', '–')}/10",
        "Warnsignale": len(z.get("warnsignale", [])),
        "Berichtigung": "empfohlen" if z.get("berichtigung_empfohlen") else "",
    } for z in items]), hide_index=True, width="stretch")
    for i, z in enumerate(items):
        with st.expander(f"{URTEIL_ICONS.get(z.get('urteil'), '')} {z.get('aussteller', '?')} – "
                         f"{z.get('funktion', '')} ({z.get('zeitraum', '')})"):
            _show_zeugnis(z, i)


def _run(paths: list[Path]) -> None:
    with st.status("Zeugnisse werden analysiert ...", expanded=True) as status:
        try:
            for p in paths:
                st.write(f"{p.name} wird gelesen und analysiert ...")
                zeugnisse.analyze(p, on_progress=st.write)
            st.write("Gesamtbild wird erstellt ...")
            zeugnisse.overview()
            status.update(label="Analyse fertig", state="complete")
            st.rerun()
        except Exception as e:
            status.update(label="Fehler", state="error")
            st.error(f"Analyse fehlgeschlagen: {e}")


def _show_overview(ov: dict) -> None:
    n1, n2 = st.columns([1, 5])
    punkte = ov.get("punkte", 0)
    n1.metric("Gesamt", f"{punkte}/10", ov.get("gesamturteil", ""), delta_color="off")
    with n2:
        _box(punkte)(ov.get("zusammenfassung", ""))
    s1, s2 = st.columns(2)
    s1.markdown(_bullets("Stärken", ov.get("staerken", [])))
    s2.markdown(_bullets("Schwachpunkte", ov.get("schwachpunkte", [])))
    if ov.get("roter_faden"):
        s1.markdown(_bullets("Roter Faden durch alle Zeugnisse", ov["roter_faden"]))
    if ov.get("entwicklung"):
        s2.markdown(f"**Entwicklung über die Zeit**\n\n{ov['entwicklung']}")
    if ov.get("top_zitate"):
        st.markdown("**Die stärksten Sätze** – ideal für Bewerbungsschreiben und Vorstellungsgespräch")
        for q in ov["top_zitate"]:
            st.markdown(f"> «{q.get('zitat', '')}»  \n> — {q.get('quelle', '')}")
    if ov.get("dossier"):
        st.markdown("**Ins Bewerbungsdossier?**")
        st.dataframe(pd.DataFrame([{"Zeugnis": d.get("aussteller", ""), "Empfehlung": d.get("empfehlung", ""),
                                    "Grund": d.get("grund", "")} for d in ov["dossier"]]),
                     hide_index=True, width="stretch")
    if ov.get("naechste_schritte"):
        st.info(_bullets("Nächste Schritte", ov["naechste_schritte"]))
    st.caption(f"Erstellt am {ov.get('erstellt', '')}")


def _show_zeugnis(z: dict, i: int) -> None:
    n1, n2 = st.columns([1, 5])
    punkte = z.get("punkte", 0)
    n1.metric("Punkte", f"{punkte}/10", z.get("urteil", ""), delta_color="off")
    with n2:
        _box(punkte)(z.get("zusammenfassung", ""))
        st.caption(f"{z.get('typ', '')} · ausgestellt {z.get('ausgestellt') or '–'} · Datei {z.get('datei', '')}")

    if z.get("bereiche"):
        st.dataframe(pd.DataFrame([{
            "Bereich": b.get("bereich", ""),
            "Urteil": f"{URTEIL_ICONS.get(b.get('urteil'), '')} {b.get('urteil', '')}",
            "Beleg im Zeugnis": b.get("beleg", ""),
        } for b in z["bereiche"]]), hide_index=True, width="stretch")

    if z.get("entschluesselt"):
        st.markdown("**Zeugnissprache im Klartext**")
        for e in z["entschluesselt"]:
            st.markdown(f"{WERTUNG_ICONS.get(e.get('wertung'), '⚪')} «{e.get('zitat', '')}»  \n"
                        f"→ {e.get('bedeutung', '')}")

    w1, w2 = st.columns(2)
    with w1:
        if z.get("warnsignale"):
            st.markdown("**Warnsignale**" + "".join(
                f"\n- {SCHWERE_ICONS.get(w.get('schwere'), '🟡')} **{w.get('punkt', '')}** – {w.get('erklaerung', '')}"
                for w in z["warnsignale"]))
        else:
            st.markdown("**Warnsignale**\n\nKeine gefunden.")
        if z.get("fehlt"):
            st.markdown(_bullets("Fehlt im Zeugnis", z["fehlt"]))
        if z.get("formales"):
            st.markdown(_bullets("Formale Mängel", z["formales"]))
    with w2:
        if z.get("beste_zitate"):
            st.markdown(_bullets("Gute Sätze für deine Bewerbung", [f"«{q}»" for q in z["beste_zitate"]]))
        if z.get("gespraechstipps"):
            st.markdown(_bullets("Tipps fürs Vorstellungsgespräch", z["gespraechstipps"]))

    if z.get("berichtigung_empfohlen"):
        st.warning(f"**Berichtigung empfohlen:** {z.get('berichtigung_grund', '')}")
    _correction(z, i)


def _correction(z: dict, i: int) -> None:
    key = f"korrektur_{z.get('datei')}_{i}"
    if st.button("Bitte um Berichtigung entwerfen", key=f"btn_{key}", disabled=not S.LLM_OK):
        with st.spinner("KI entwirft das Schreiben ..."):
            try:
                path = next(p for p in documents.active_documents("zeugnisse") if p.name == z.get("datei"))
                st.session_state[key] = zeugnisse.correction_request(S.profile, z, path)
            except Exception as e:
                st.error(f"Entwurf fehlgeschlagen: {e}")
    if draft := st.session_state.get(key):
        if draft.get("ersatz"):
            st.dataframe(pd.DataFrame([{"Bisher": r.get("bisher", ""), "Vorschlag": r.get("vorschlag", "")}
                                       for r in draft["ersatz"]]), hide_index=True, width="stretch")
        betreff = st.text_input("Betreff", draft.get("betreff", ""), key=f"betreff_{key}")
        text = st.text_area("Schreiben (anpassbar)", draft.get("text", ""), height=380, key=f"text_{key}")
        st.download_button("Als Textdatei herunterladen", f"Betreff: {betreff}\n\n{text}".encode("utf-8"),
                           file_name=f"Berichtigung_Zeugnis_{z.get('aussteller', '')}.txt".replace(" ", "_"),
                           mime="text/plain", key=f"dl_{key}")
        st.caption("Tipp: Freundlich anfragen wirkt meist besser als fordern. In der Schweiz hast du nach "
                   "OR Art. 330a Anspruch auf ein wahres, wohlwollendes und vollständiges Zeugnis.")
