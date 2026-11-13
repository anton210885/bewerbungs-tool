"""Seite «Matching-Qualität»: deine Einschätzungen gegen die Bewertung des Tools."""
from datetime import datetime

import pandas as pd
import streamlit as st

from src import quality
from ui import state as S

COST_PER_JOB = 3  # Rappen, wie bei der Stellenbewertung


def _percent(value) -> str:
    return "–" if value is None else f"{round(100 * value)} %"


def _delta(now, before, scale=100, unit=" Pkt.", invert=False):
    if now is None or before is None:
        return None
    diff = round((now - before) * scale, 1)
    return None if diff == 0 else f"{diff:+g}{unit}"


def _summary(run: dict, previous: dict | None) -> None:
    k = run["kennzahlen"]
    p = (previous or {}).get("kennzahlen") or {}
    when = datetime.fromisoformat(run["zeit"]).strftime("%d.%m.%Y %H:%M")
    st.markdown(f"**Letzter Prüflauf:** {when} · {k['n']} Stellen · Modell {run.get('modell', '?')}"
                + ("" if run.get("mit_automatischen", True) else " · nur eigene Einschätzungen"))
    if not k["genug"]:
        st.warning(f"Noch zu wenig Einschätzungen für verlässliche Zahlen: mindestens {quality.MIN_FOR_METRICS}, "
                   "und es müssen verschiedene Einschätzungen dabei sein. Gut sind 30 bis 40.")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"Top {quality.TOP_K}: passt", _percent(k["top_passt"]), _delta(k["top_passt"], p.get("top_passt")),
              help=f"Wie viele der {quality.TOP_K} am besten bewerteten Stellen hast du mit «passt» eingeschätzt. "
                   "Die wichtigste Zahl für den Alltag.")
    c2.metric("Richtig sortiert", _percent(k["paar_treffer"]), _delta(k["paar_treffer"], p.get("paar_treffer")),
              help="Nimm zwei Stellen, die du unterschiedlich einschätzt: Wie oft bekommt die bessere auch die höhere "
                   "Prozentzahl? 50 % wäre Zufall, 100 % perfekt.")
    c3.metric("Rangkorrelation", "–" if k["rangkorrelation"] is None else f"{k['rangkorrelation']:.2f}",
              _delta(k["rangkorrelation"], p.get("rangkorrelation"), scale=1, unit=""),
              help="Spearman zwischen Prozentzahl und deiner Einschätzung: 0 = kein Zusammenhang, 1 = perfekt. "
                   "Ab etwa 0.5 ist das Matching brauchbar.")
    c4.metric("Falsche K.-o.", k["falsche_ko"], _delta(k["falsche_ko"], p.get("falsche_ko"), scale=1, unit=""),
              delta_color="inverse",
              help="Stellen mit «passt» oder «teilweise», die das Tool per K.-o. aussortiert. Der teuerste Fehler: "
                   "solche Stellen siehst du in der Suche sonst nie.")
    c5.metric("Schwankung", "–" if k["schwankung"] is None else f"±{k['schwankung']:g}",
              _delta(k["schwankung"], p.get("schwankung"), scale=1, unit=""), delta_color="inverse",
              help="Durchschnittlicher Unterschied zur Bewertung, die beim Einschätzen angezeigt wurde. Zeigt, wie "
                   "stark die KI bei derselben Anzeige schwankt (dazu kommen Änderungen an Profil und Suchwünschen).")
    classes = k["nach_einschaetzung"]
    st.caption("Durchschnittliche Prozentzahl nach deiner Einschätzung – je weiter auseinander, desto besser: "
               + " · ".join(f"{quality.LABELS[name]}: {c['mittel'] if c['mittel'] is not None else '–'} % "
                            f"({c['anzahl']})" for name, c in classes.items()))
    if run.get("fehler"):
        with st.expander(f"{len(run['fehler'])} Stellen konnten nicht bewertet werden"):
            for error in run["fehler"]:
                st.write(error)


def _outliers(run: dict) -> None:
    outliers = run["kennzahlen"]["ausreisser"]
    st.markdown(f"#### Ausreisser ({len(outliers)})")
    if not outliers:
        st.caption("Keine: Das Tool liegt bei allen Stellen ungefähr bei deiner Einschätzung.")
        return
    st.caption("Hier liegen Tool und du weit auseinander. Die Begründung der KI zeigt, wo das Matching danebenliegt: "
               "Gewichtung, Zielprofil, K.-o.-Regeln, fehlende Angaben im Profil oder das Modell.")
    for row in outliers:
        auto = " (automatisch)" if row.get("automatisch") else ""
        with st.expander(f"Tool {row['score']} % · du: {quality.LABELS[row['einschaetzung']]}{auto} · "
                         f"{row['title'] or '?'} – {row['company'] or '?'}"):
            if row.get("url"):
                st.markdown(f"[Anzeige öffnen]({row['url']})")
            if row.get("ko_gruende"):
                st.error("**K.-o.:** " + "; ".join(row["ko_gruende"]))
            if row.get("fazit"):
                st.write(row["fazit"])
            a1, a2 = st.columns(2)
            a1.markdown("**Was passt (KI)**" + "".join(f"\n- {x}" for x in row.get("staerken", [])))
            a2.markdown("**Was fehlt (KI)**" + "".join(f"\n- {x}" for x in row.get("luecken", [])))


def _labels_table(labels: dict) -> None:
    with st.expander(f"Eingeschätzte Stellen ({len(labels)})"):
        frame = pd.DataFrame([{
            "Entfernen": False, "Stelle": v["title"] or "?", "Firma": v["company"],
            "Einschätzung": quality.LABELS.get(v["rating"], v["rating"]),
            "Art": "automatisch" if v.get("automatisch") else "von dir", "Quelle": v.get("quelle", ""),
            "Bewertung damals": v.get("score_damals"), "Datum": v.get("zeit", "")[:10], "_key": k,
        } for k, v in sorted(labels.items(), key=lambda kv: kv[1].get("zeit", ""), reverse=True)])
        edited = st.data_editor(frame, hide_index=True, width="stretch", key=f"quality_labels_{len(labels)}",
                                column_order=[c for c in frame.columns if c != "_key"],
                                disabled=[c for c in frame.columns if c != "Entfernen"])
        remove = edited.loc[edited["Entfernen"], "_key"].tolist()
        if remove and st.button(f"{len(remove)} Einschätzung(en) entfernen"):
            for key in remove:
                quality.remove_label(key)
            st.rerun()
        st.caption("Automatische Einschätzungen entstehen beim Übernehmen («passt») und bei «Interessiert mich "
                   "nicht» («passt nicht»). Klickst du selbst eine Einschätzung an, gilt deine.")


def render() -> None:
    st.subheader("Matching-Qualität")
    st.caption("Wie gut trifft das Tool deine Einschätzung? Schätze bewertete Stellen mit 👍 / 🤷 / 👎 ein – die "
               "Knöpfe stehen unter jeder Bewertung. Ein Prüflauf bewertet diese Stellen neu und vergleicht. "
               "So siehst du bei jeder Änderung am Matching, ob es besser oder schlechter wird.")
    labels = quality.load_labels()
    manual = sum(1 for v in labels.values() if not v.get("automatisch"))
    counts = {name: sum(1 for v in labels.values() if v["rating"] == name) for name in quality.RATINGS}
    st.write(f"**{len(labels)} Stellen eingeschätzt** ({manual} von dir, {len(labels) - manual} automatisch): "
             + " · ".join(f"{quality.LABELS[n]} {c}" for n, c in counts.items()))
    if not labels:
        st.info("Noch keine Einschätzungen. Bewerte Stellen in der Stellensuche oder im Tracker und klicke unter "
                "der Bewertung auf 👍, 🤷 oder 👎.")
        return

    c1, c2 = st.columns([1, 2])
    include_auto = c1.checkbox("Automatische mitzählen", value=True, key="quality_include_auto",
                               help="Übernommen = passt, «Interessiert mich nicht» = passt nicht. Etwas ungenauer, "
                                    "weil man auch aus anderen Gründen verwirft (z.B. Arbeitsweg).")
    n = len(quality.selected(include_auto))
    if c2.button(f"Qualität jetzt prüfen ({n} Stellen, ca. {n * COST_PER_JOB} Rappen)", type="primary",
                 disabled=not n or not S.LLM_OK, width="stretch"):
        bar = st.progress(0.0, text="Bewerte neu ...")
        quality.run_check(S.profile, include_auto,
                          on_progress=lambda d, t, label: bar.progress(d / t, text=f"{d} von {t}: {label['title']}"))
        st.rerun()

    runs = quality.load_runs()
    if runs:
        _summary(runs[-1], runs[-2] if len(runs) > 1 else None)
        _outliers(runs[-1])
        if len(runs) > 1:
            with st.expander(f"Frühere Prüfläufe ({len(runs) - 1})"):
                st.dataframe(pd.DataFrame([{
                    "Zeit": r["zeit"].replace("T", " "), "Modell": r.get("modell", ""), "Stellen": r["kennzahlen"]["n"],
                    f"Top {quality.TOP_K} passt": _percent(r["kennzahlen"]["top_passt"]),
                    "Richtig sortiert": _percent(r["kennzahlen"]["paar_treffer"]),
                    "Falsche K.-o.": r["kennzahlen"]["falsche_ko"],
                } for r in reversed(runs[:-1])]), hide_index=True, width="stretch")
    else:
        st.caption("Noch kein Prüflauf.")
    _labels_table(labels)
