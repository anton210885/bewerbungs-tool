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
                + (f" · Logik-Version {run['logik']}" if run.get("logik") else "")
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


# ---------------------------------------------------------------- A/B-Vergleich

VERDICT = {"B besser": "✅ B besser", "B schlechter": "❌ B schlechter",
           "kein klarer Unterschied": "➖ kein klarer Unterschied", "zu wenig Stellen": "⏳ zu wenig Stellen"}


def _value(name: str, value) -> str:
    if value is None:
        return "–"
    if name in ("top_passt", "paar_treffer"):
        return f"{round(100 * value)} %"
    if name == "rangkorrelation":
        return f"{value:.2f}"
    return f"{value:g}"


def _diff(name: str, value) -> str:
    if value is None:
        return "–"
    if name in ("top_passt", "paar_treffer"):
        return f"{100 * value:+.0f} Pkt."
    return f"{value:+.2f}" if name == "rangkorrelation" else f"{value:+g}"


def _comparison(result: dict, label_a: str, label_b: str) -> None:
    st.markdown(f"**A:** {label_a} · **B:** {label_b} · {result['gemeinsam']} gemeinsam bewertete Stellen")
    if not result["kennzahlen"]:
        st.info("Keine Stellen, die beide Varianten bewertet haben.")
        return
    st.dataframe(pd.DataFrame([{
        "Kennzahl": e["name"], "A": _value(name, e["a"]), "B": _value(name, e["b"]),
        "Unterschied B–A": _diff(name, e["diff"]),
        "Sicherheit, dass B besser ist": "–" if e.get("p_besser") is None else f"{round(100 * e['p_besser'])} %",
        "Urteil": VERDICT.get(e.get("urteil"), "–"),
    } for name, e in result["kennzahlen"].items()]), hide_index=True, width="stretch")
    st.caption(f"«Sicherheit» kommt aus einem Bootstrap: Die Stellen werden {quality.BOOTSTRAP}-mal neu gezogen. "
               f"Erst ab {round(100 * quality.CONFIDENT)} % (bzw. unter {round(100 * (1 - quality.CONFIDENT))} %) "
               "gilt ein Unterschied als echt; dazwischen kann er Zufall sein. Bei falschen K.-o. ist weniger besser.")


def _weights_tab(runs: list[dict]) -> None:
    from src import matching
    run = next((r for r in reversed(runs) if any(z.get("kriterien") for z in r.get("zeilen") or [])), None)
    st.caption("Rechnet die Prozentzahlen des letzten Prüflaufs mit anderen Gewichten neu – ohne KI, ohne Kosten. "
               "So siehst du, ob z.B. mehr Gewicht auf den Aufgaben die Reihenfolge verbessert.")
    if not run:
        st.info("Zuerst einen Prüflauf machen (oben). Ältere Läufe enthalten die Einzelwerte noch nicht.")
        return
    current = run.get("gewichtung") or matching.GEWICHTUNG
    with st.form("quality_weights"):
        cols = st.columns(len(matching.GEWICHTUNG))
        weights = {key: col.number_input(matching.KRITERIEN[key], 0, 100, int(current.get(key, 0)), step=5,
                                         key=f"quality_w_{key}")
                   for col, key in zip(cols, matching.GEWICHTUNG)}
        go = st.form_submit_button("Gewichte vergleichen", type="primary")
    if go:
        if not sum(weights.values()):
            st.warning("Mindestens ein Gewicht muss grösser als 0 sein.")
            return
        rows = run["zeilen"]
        result = quality.compare(rows, quality.rescore(rows, weights))
        _comparison(result, "heutige Gewichte " + " / ".join(f"{current.get(k, 0):g}" for k in matching.GEWICHTUNG),
                    "neue Gewichte " + " / ".join(f"{weights[k]:g}" for k in matching.GEWICHTUNG))
        st.caption("Gefällt dir B: die Gewichte in deinem Profil unter «zielprofil → gewichtung» eintragen "
                   "(aufgaben, muss, wuensche, senioritaet). Danach einen neuen Prüflauf machen.")


def _models_tab(include_auto: bool, n: int) -> None:
    from src.llm import current_model
    st.caption("Beide Varianten bewerten dieselben Stellen im selben Lauf. Tipp: Zuerst einmal «A gegen A» laufen "
               "lassen – das zeigt, wie stark die KI von sich aus schwankt. Kleinere Unterschiede sind Zufall.")
    c1, c2 = st.columns(2)
    model_a = c1.text_input("Modell A", current_model(), key="quality_model_a",
                            help="Unverändert = das eingestellte Modell.")
    same = c2.checkbox("A gegen A (Zufall messen)", key="quality_same")
    model_b = c2.text_input("Modell B", "", key="quality_model_b", disabled=same,
                            placeholder="z.B. gpt-4.1-mini oder ein Venice-Modell")
    model_a = model_a.strip()
    model_b = model_a if same else model_b.strip()
    if st.button(f"Vergleich starten ({n} Stellen × 2, ca. {2 * n * COST_PER_JOB} Rappen, je nach Modell)",
                 disabled=not (n and S.LLM_OK and model_a and model_b), key="quality_ab_start"):
        bar = st.progress(0.0, text="Bewerte mit beiden Varianten ...")
        quality.run_ab(S.profile, {"modell": model_a}, {"modell": model_b}, include_auto,
                       on_progress=lambda d, t, label: bar.progress(d / t, text=f"{d} von {t}: {label['title']}"))
        st.rerun()
    results = quality.load_ab()
    if results:
        last = results[-1]
        st.markdown(f"##### Letzter Vergleich ({last['zeit'].replace('T', ' ')})")
        same_model = last["a"]["modell"] == last["b"]["modell"]
        _comparison(last["vergleich"], last["a"]["modell"],
                    last["b"]["modell"] + (" (gleiches Modell: zeigt den Zufall)" if same_model else ""))
        errors = last["a"]["fehler"] + last["b"]["fehler"]
        if errors:
            with st.expander(f"{len(errors)} Bewertungen fehlgeschlagen"):
                for error in errors:
                    st.write(error)


def _runs_tab(runs: list[dict]) -> None:
    usable = [r for r in runs if r.get("zeilen")]
    st.caption("Zwei gespeicherte Prüfläufe Stelle für Stelle vergleichen, z.B. vor und nach einer Änderung an "
               "Profil, Prompts oder Modell (die Logik-Version zeigt, ob sich die Bewertungslogik geändert hat).")
    if len(usable) < 2:
        st.info("Dafür braucht es mindestens zwei Prüfläufe mit dieser Version des Tools.")
        return

    def name(i):
        r = usable[i]
        return f"{r['zeit'].replace('T', ' ')} · {r.get('modell', '?')} · Logik {r.get('logik', '?')}"

    c1, c2 = st.columns(2)
    a = c1.selectbox("Lauf A (vorher)", range(len(usable)), index=len(usable) - 2, format_func=name,
                     key="quality_run_a")
    b = c2.selectbox("Lauf B (nachher)", range(len(usable)), index=len(usable) - 1, format_func=name,
                     key="quality_run_b")
    if a == b:
        st.caption("Bitte zwei verschiedene Läufe wählen.")
        return
    _comparison(quality.compare_runs(usable[a], usable[b]), name(a), name(b))


def _ab_section(runs: list[dict], include_auto: bool, n: int) -> None:
    st.markdown("#### Varianten vergleichen (A/B)")
    t1, t2, t3 = st.tabs(["Gewichte testen (kostenlos)", "Modelle vergleichen", "Frühere Läufe vergleichen"])
    with t1:
        _weights_tab(runs)
    with t2:
        _models_tab(include_auto, n)
    with t3:
        _runs_tab(runs)


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
    _ab_section(runs, include_auto, n)
    _labels_table(labels)
