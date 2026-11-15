"""Seite «Stellen ansehen»: alle gefundenen Stellen in einer Liste – sortieren, suchen, bewerten, übernehmen."""
import hashlib

import numpy as np
import streamlit as st

from src import company_jobs, discovery, job_actions, job_index, quality, skill_search, task_search
from ui import state as S
from ui.helpers import show_analysis, store_job

SORT_BEST, SORT_TASKS, SORT_LIKE, SORT_SCORE, SORT_NEW = (
    "Beste zuerst", "Passt zu meinen Aufgaben", "Ähnlich wie meine 👍", "Meine Bewertung", "Neueste zuerst")
SORTS = [SORT_BEST, SORT_TASKS, SORT_LIKE, SORT_SCORE, SORT_NEW]
SOURCES = job_index.SOURCE_ORDER
PAGE_SIZE = 30
PRICE_RAPPEN = 3


def show_newest() -> None:
    """Sprung von «Stellen holen» hierher, neueste zuerst (als on_click-Callback)."""
    st.session_state.update(nav_page="stellen_db", jobdb_sort=SORT_NEW, jobdb_query="", jobdb_limit=PAGE_SIZE)
    st.session_state.pop("jobdb_similar", None)


def similarity_word(prozent: int) -> str:
    """Ähnlichkeit in Worten: eine Zahl wäre mit der Bewertung (Passung in %) zu verwechseln."""
    return "sehr ähnlich" if prozent >= 70 else "ähnlich" if prozent >= 40 else "entfernt ähnlich"


# ---------------------------------------------------------------- Index

def _signature(records: list[dict]) -> str:
    raw = "|".join(f"{r['key']}:{len(r['description'])}:{r['title']}" for r in records)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _index(records: list[dict]):
    """Vektoren nur neu holen, wenn sich die Anzeigen geändert haben; Status und Bewertungen immer frisch."""
    signature = _signature(records)
    cached = st.session_state.get("jobdb_index")
    if cached and cached[0] == signature:
        index = cached[1]
        index.records, index.groups = records, None
        return index
    with st.spinner("Stellen werden für die Suche vorbereitet (neue Anzeigen kosten einmalig unter 0.1 Rappen) ..."):
        index = job_index.build(records)
    if index is not None:
        st.session_state["jobdb_index"] = (signature, index)
    return index


# ---------------------------------------------------------------- Aktionen (Callbacks)

def _open_in_tracker(app_id: int) -> None:
    st.session_state["current_app"] = app_id
    st.session_state["show_app_detail"] = True
    st.session_state["nav_page"] = "bewerben"
    st.session_state["notice"] = "Stelle unter «Prüfen & bewerben» geöffnet."


def _take_over(record: dict) -> None:
    app_id = job_actions.take_over(record, store_job)
    if app_id:
        _open_in_tracker(app_id)
        st.session_state["notice"] = (f"„{record['title']}“ in den Tracker übernommen – hier analysieren und "
                                      "bewerben.")


def _dismiss(record: dict) -> None:
    job_actions.dismiss(record)
    st.session_state["jobdb_message"] = f"„{record['title']}“ ausgeblendet – kommt bei neuen Suchen nicht wieder."


def _show_similar(key: str) -> None:
    st.session_state["jobdb_similar"] = key


def _wishes() -> str:
    prefs = discovery.load_preferences(S.profile or {})
    return skill_search.evaluation_wishes({**prefs, "search_mode": "Aufgaben"})


# ---------------------------------------------------------------- Anzeige einer Stelle

def _label(r: dict) -> str:
    where = r["location"] + (f" ({r['distanz_km']} km)" if r.get("distanz_km") is not None else "")
    text = " · ".join(p for p in (r["title"] or "Ohne Titel", r["company"], where) if p)
    if r.get("score") is not None:
        badge = f"**{r['score']} %**"
    elif r.get("wort"):
        badge = r["wort"]
    else:
        badge = ""
    marks = " · im Tracker" if r.get("app_id") else ""
    return (f"{badge} · " if badge else "") + text + marks


def _item(r: dict, index, prefix: str) -> None:
    with st.expander(_label(r)):
        if r.get("passender_abschnitt"):
            st.markdown(f"**Passt am besten zur Suche:** «{r['passender_abschnitt']}»")
        info = [f"Gefunden über: {', '.join(r['quellen'])}"]
        if r.get("gefunden"):
            info.append(f"am {r['gefunden'][8:10]}.{r['gefunden'][5:7]}.")
        if r["status"] and r["ausgeblendet"]:
            info.append(f"Status: {r['status']}")
        doubles = job_index.duplicates_of(index, r["key"])
        if doubles:
            info.append("auch unter: " + ", ".join(f"{d['company'] or '?'} ({d['quelle']})" for d in doubles))
        st.caption(" · ".join(info))

        if r.get("analysis"):
            show_analysis(r["analysis"], job=r, source=r["quelle"])
        elif r["nur_titel"]:
            st.info("Von dieser Stelle ist nur der Titel bekannt. Anzeige öffnen und den Text unter «Prüfen & "
                    "bewerben» einfügen – oder unter «Stellen holen → Firmen» die fehlenden Texte laden.")
        else:
            st.write(r["description"][:600] + (" …" if len(r["description"]) > 600 else ""))

        cols = st.columns(4)
        if r["url"]:
            cols[0].link_button("Anzeige öffnen", r["url"], width="stretch")
        if r.get("app_id"):
            cols[1].button("Im Tracker öffnen", key=f"{prefix}_open_{r['key']}", on_click=_open_in_tracker,
                           args=(r["app_id"],), type="primary", width="stretch")
        else:
            if not r.get("analysis") and cols[1].button(
                    f"Bewerten (ca. {PRICE_RAPPEN} Rp.)", key=f"{prefix}_eval_{r['key']}", width="stretch",
                    disabled=not (S.LLM_OK and S.PROFILE_READY and job_actions.can_evaluate(r)),
                    help="Die KI vergleicht die Anzeige mit deinem Profil und gibt die Passung in Prozent an."):
                with st.spinner("Vergleiche mit deinem Profil ..."):
                    try:
                        job_actions.evaluate(r, S.profile, _wishes())
                        st.rerun()
                    except Exception as error:
                        st.error(f"Bewertung fehlgeschlagen: {error}")
            if r.get("analysis"):
                cols[1].button("In den Tracker übernehmen", key=f"{prefix}_take_{r['key']}", on_click=_take_over,
                               args=(r,), type="primary", width="stretch")
            cols[2].button("Interessiert mich nicht", key=f"{prefix}_skip_{r['key']}", on_click=_dismiss,
                           args=(r,), width="stretch")
        cols[3].button("Ähnliche Stellen", key=f"{prefix}_sim_{r['key']}", on_click=_show_similar,
                       args=(r["key"],), width="stretch")


def _list(results: list[dict], index, prefix: str, empty: str) -> None:
    if not results:
        st.caption(empty)
        return
    limit = st.session_state.get("jobdb_limit", PAGE_SIZE)
    for r in results[:limit]:
        _item(r, index, prefix)
    if len(results) > limit:
        st.button(f"Weitere anzeigen ({len(results) - limit} übrig)", key=f"{prefix}_more",
                  on_click=lambda: st.session_state.update(jobdb_limit=limit + PAGE_SIZE))


def _similar_section(index, key: str, show_hidden: bool) -> None:
    position = index.position(key)
    if position is None:
        st.session_state.pop("jobdb_similar", None)
        return
    base = index.records[position]
    c1, c2 = st.columns([4, 1])
    c1.markdown(f"#### Ähnlich wie: {base['title']} – {base['company'] or '?'}")
    c2.button("Zurück zur Liste", on_click=lambda: st.session_state.pop("jobdb_similar", None), width="stretch")
    results = [{**r, "wort": similarity_word(r["prozent"])}
               for r in job_index.similar(index, key, limit=15, show_hidden=show_hidden)]
    _list(results, index, "sim", "Keine deutlich ähnlichen Stellen in der Datenbank.")


# ---------------------------------------------------------------- Sortieren

def _tasks() -> list[str]:
    prefs = discovery.load_preferences(S.profile or {})
    return company_jobs.comparison_tasks(prefs) or task_search.profile_tasks(S.profile or {})


def _liked_examples(rating: str = "passt") -> list[dict]:
    return [{"key": quality.job_key(v["url"], v["description"]), "title": v["title"],
             "description": v["description"]} for v in quality.load_labels().values() if v["rating"] == rating]


def _best_word(parts: dict, position: int) -> str:
    """Warum eine unbewertete Stelle so weit oben steht, in Worten."""
    words = []
    if not np.isnan(task := parts["aufgaben"][position]):
        words.append(f"Aufgaben: {similarity_word(int(task))}")
    if not np.isnan(like := parts["wie_passt"][position]):
        words.append(f"wie deine 👍: {similarity_word(int(like))}")
    dislike = parts["wie_passt_nicht"][position]
    if not np.isnan(dislike) and dislike >= 40 and dislike > np.nan_to_num(like, nan=0.0):
        words.append("ähnelt deinen 👎")
    return " · ".join(words)


def _sorted(index, sort: str, show_hidden: bool) -> tuple[list[dict], str]:
    """-> (Stellen in dieser Reihenfolge, Hinweis zur Sortierung)"""
    records = index.records
    if sort == SORT_BEST:
        liked, disliked = _liked_examples("passt"), _liked_examples("passt_nicht")
        parts = job_index.best_scores(index, _tasks(), liked, disliked)
        results = job_index.ranked(index, parts["wert"], show_hidden)
        positions = {rec["key"]: i for i, rec in enumerate(records)}
        for r in results:
            r["wort"] = _best_word(parts, positions[r["key"]])
        # Stellen im Tracker kennst du schon: ans Ende, damit oben die neuen Kandidaten stehen
        results = [r for r in results if not r.get("app_id")] + [r for r in results if r.get("app_id")]
        used =["die Bewertung der KI", "die Nähe zu deinen Aufgaben"]
        if liked:
            used.append(f"die Ähnlichkeit mit deinen {len(liked)} 👍")
        hint = ("Zusammen zählen " + ", ".join(used[:-1]) + " und " + used[-1] + "."
                + (f" Stellen wie deine {len(disliked)} 👎 rutschen nach unten." if disliked else "")
                + " Eine unbewertete Stelle weit oben lohnt sich zu bewerten. Stellen im Tracker stehen am "
                  "Schluss.")
        return results, hint
    if sort == SORT_TASKS:
        scores = job_index.task_scores(index, _tasks())
        if scores is not None:
            words = {i: similarity_word(job_index.percent(s, task_search.NAEHE_MIN, task_search.NAEHE_MAX))
                     for i, s in enumerate(scores) if s > -1}
            results = job_index.ranked(index, scores, show_hidden)
            positions = {rec["key"]: i for i, rec in enumerate(records)}
            for r in results:
                position = positions[r["key"]]
                r["wort"] = f"Aufgaben: {words[position]}" if position in words else ""
            return results, ("Oben stehen die Anzeigen, deren Aufgaben deinen bisherigen am meisten gleichen. "
                             "Stellen ohne Anzeigentext stehen am Schluss.")
        sort = SORT_SCORE
    if sort == SORT_LIKE:
        examples = _liked_examples()
        scores = job_index.like_scores(index, examples) if examples else None
        if scores is not None:
            results = job_index.ranked(index, scores, show_hidden)
            for r in results:
                r["wort"] = "wie deine 👍: " + similarity_word(job_index.percent(
                    r["aehnlichkeit"], job_index.LIKE_MIN, job_index.LIKE_MAX))
            return results, f"Verglichen mit den {len(examples)} Stellen, die du mit 👍 eingeschätzt hast."
        st.info("Noch keine Stelle mit 👍 eingeschätzt – das geht unter jeder Bewertung. Bis dahin nach "
                "Bewertung sortiert.")
        sort = SORT_SCORE
    if sort == SORT_SCORE:
        scores = np.array([r["score"] if r.get("score") is not None else -1 for r in records], dtype=float)
        return job_index.ranked(index, scores, show_hidden), "Bewertete Stellen zuerst, nach Passung."
    order = sorted(range(len(records)), key=lambda i: records[i].get("gefunden") or "")
    scores = np.empty(len(records))
    scores[order] = np.arange(len(records))
    return job_index.ranked(index, scores, show_hidden), "Zuletzt gefundene zuerst."


def _evaluate_next(shown: list[dict]) -> None:
    candidates = [r for r in shown if r.get("score") is None and not r.get("app_id") and job_actions.can_evaluate(r)]
    if not candidates:
        return
    c1, c2 = st.columns([1, 3])
    count = c1.number_input("Wie viele?", 1, 25, min(5, len(candidates)), key="jobdb_eval_count",
                            label_visibility="collapsed")
    if c2.button(f"Die nächsten {count} unbewerteten dieser Liste mit meinem Profil bewerten "
                 f"(ca. {count * PRICE_RAPPEN} Rappen)", disabled=not (S.LLM_OK and S.PROFILE_READY)):
        bar = st.progress(0.0, text="Bewerte ...")
        errors = job_actions.evaluate_many(
            candidates[:int(count)], S.profile, _wishes(),
            on_progress=lambda d, n, r: bar.progress(d / n, text=f"{d} von {n}: {r['title']}"))
        for error in errors:
            st.warning(error)
        if not errors:
            st.rerun()


# ---------------------------------------------------------------- Seite

def render() -> None:
    st.subheader("Stellen ansehen")
    st.caption("Alle Stellen, die das Tool gefunden hat, in einer Liste. Neue Stellen holst du unter «Stellen "
               "holen». **Prozent** = Bewertung durch die KI, wie gut die Stelle zu deinem Profil passt. "
               "**sehr ähnlich / ähnlich** = nur inhaltlich verwandt, noch nicht bewertet.")
    records = job_index.collect()
    if not records:
        st.info("Noch keine Stellen gefunden. Hole zuerst Stellen unter «Stellen holen».")
        return
    if not task_search.embedding_model():
        st.warning("Diese Seite braucht einen Embedding-Zugang (OpenAI oder Venice) unter Einstellungen.")
        return
    index = _index(records)
    if index is None:
        st.error("Die Stellen konnten nicht vorbereitet werden (Embedding-Anbieter nicht erreichbar). "
                 "Später nochmals versuchen.")
        return
    if message := st.session_state.pop("jobdb_message", None):
        st.success(message)

    c1, c2 = st.columns([3, 2])
    query = c1.text_input("Suchen", key="jobdb_query", placeholder="z.B. Automatisierung mit Python im Datenbankumfeld",
                          help="Sucht nach Bedeutung, nicht nach Stichworten: «Skripte für den Betrieb» findet "
                               "auch «PowerShell-Automatisierung».")
    sort = c2.selectbox("Sortieren nach", SORTS, key="jobdb_sort", disabled=bool(query.strip()),
                        on_change=lambda: st.session_state.update(jobdb_limit=PAGE_SIZE))
    f1, f2, f3 = st.columns([3, 1.3, 1.7])
    sources = f1.multiselect("Gefunden über", SOURCES, key="jobdb_sources", placeholder="alle Quellen")
    only_new = f2.checkbox("Nur unbewertete", key="jobdb_unrated")
    show_hidden = f3.checkbox("Auch verworfene und zu weit entfernte", key="jobdb_hidden")

    if st.session_state.get("jobdb_similar"):
        _similar_section(index, st.session_state["jobdb_similar"], show_hidden)
        return

    if query.strip():
        results = [{**r, "wort": f"zur Suche: {similarity_word(r['prozent'])}"}
                   for r in job_index.search(index, query, limit=100, show_hidden=show_hidden)]
        hint = "Nach Ähnlichkeit mit deiner Suche."
    else:
        results, hint = _sorted(index, sort, show_hidden)
    shown = [r for r in results
             if (not sources or set(sources) & set(r["quellen"]))
             and (not only_new or (r.get("score") is None and not r.get("app_id")))]
    hidden = sum(r["ausgeblendet"] for r in records)
    st.markdown(f"**{len(shown)} Stellen** · {hint}"
                + (f" {hidden} verworfene oder zu weit entfernte sind ausgeblendet." if hidden and not show_hidden
                   else ""))
    _evaluate_next(shown)
    _list(shown, index, "q", "Nichts gefunden. Andere Worte versuchen oder die Filter lockern.")
