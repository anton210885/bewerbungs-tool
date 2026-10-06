from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src import db, interview, tracker
from ui import state as S

DATE_COLUMNS = ["applied_at", "follow_up_at", "interview_at", "deadline"]


def _reminders(apps: list[dict]) -> None:
    todo = tracker.reminders(apps)
    if not todo:
        st.success("Keine offenen Erinnerungen – alles im grünen Bereich.")
        return
    st.markdown(f"**Zu erledigen ({len(todo)})**")
    for i, r in enumerate(todo):
        app = r["app"]
        box = {"gespraech": st.info, "frist": st.error, "nachfassen": st.warning}.get(r["art"], st.info)
        box(r["text"])
        if r["art"] != "nachfassen":
            continue
        c1, c2, _ = st.columns([2, 2, 3])
        if c1.button("Nachfass-Mail entwerfen", key=f"fu_{app['id']}_{i}", disabled=not S.LLM_OK):
            with st.spinner("KI schreibt die Nachfass-Mail ..."):
                try:
                    st.session_state[f"fu_mail_{app['id']}"] = interview.followup_email(S.profile, app)
                except Exception as e:
                    st.error(f"Das hat nicht geklappt: {e}")
        if c2.button("Erledigt – in 10 Tagen erinnern", key=f"fu_done_{app['id']}_{i}"):
            db.update_application(app["id"], follow_up_at=(date.today() + timedelta(days=10)).isoformat())
            st.rerun()
        if mail := st.session_state.get(f"fu_mail_{app['id']}"):
            st.text_input("Betreff", mail.get("betreff", ""), key=f"fu_subj_{app['id']}")
            st.text_area("E-Mail (zum Kopieren)", mail.get("text", ""), height=220, key=f"fu_text_{app['id']}")


def _stats(apps: list[dict]) -> None:
    s = tracker.stats(apps)
    m = st.columns(5)
    m[0].metric("Stellen im Tracker", s["gesamt"])
    m[1].metric("Beworben", s["beworben"])
    m[2].metric("Antwortquote", f"{s['antwortquote']} %", help="Anteil der Bewerbungen mit Gespräch, Zusage oder Absage")
    m[3].metric("Einladungsquote", f"{s['einladungsquote']} %", help="Anteil mit Gespräch oder Zusage")
    m[4].metric("Ø Passung (beworben)", f"{s['passung_schnitt']} %" if s["passung_schnitt"] is not None else "–")
    if s["pro_woche"]:
        st.caption("Bewerbungen pro Woche (Wochenbeginn)")
        st.bar_chart(pd.Series(s["pro_woche"], name="Bewerbungen"), height=180)


def render() -> None:
    apps = db.list_applications()
    if not apps:
        st.info("Noch keine Bewerbungen.")
        return

    _reminders(apps)
    st.divider()
    _stats(apps)
    counts = pd.Series([a["status"] for a in apps]).value_counts()
    st.caption("  ·  ".join(f"{status}: {int(counts.get(status, 0))}" for status in db.STATUS_OPTIONS))

    df = pd.DataFrame(apps)
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    df = df[["id", "status", "score", "title", "company", "applied_at", "follow_up_at", "interview_at", "deadline",
             "notes", "url", "location", "updated_at"]]
    st.caption("Status, Daten und Notizen kannst du direkt in der Tabelle ändern. „Beworben am“ wird automatisch "
               "gesetzt, sobald du den Status auf „beworben“ stellst.")
    edited = st.data_editor(
        df,
        hide_index=True,
        width="stretch",
        disabled=["id", "score", "title", "company", "location", "url", "updated_at"],
        column_config={
            "id": "ID",
            "status": st.column_config.SelectboxColumn("Status", options=db.STATUS_OPTIONS, required=True),
            "score": st.column_config.NumberColumn("Passung %"),
            "title": "Stelle",
            "company": "Firma",
            "applied_at": st.column_config.DateColumn("Beworben am", format="DD.MM.YYYY"),
            "follow_up_at": st.column_config.DateColumn("Nachfassen am", format="DD.MM.YYYY"),
            "interview_at": st.column_config.DateColumn("Gespräch am", format="DD.MM.YYYY"),
            "deadline": st.column_config.DateColumn("Frist", format="DD.MM.YYYY"),
            "notes": "Notizen",
            "url": st.column_config.LinkColumn("Link", display_text="öffnen"),
            "location": "Ort",
            "updated_at": "Geändert",
        },
        key="tracker_editor",
    )
    t1, t2, t3 = st.columns([1, 2, 1])
    if t1.button("Änderungen speichern", type="primary"):
        for row in edited.to_dict("records"):
            fields = {"status": row["status"], "notes": row["notes"] if isinstance(row["notes"], str) else None}
            for col in DATE_COLUMNS:
                value = row[col]
                fields[col] = value.isoformat() if isinstance(value, date) and not pd.isna(value) else None
            original = next(a for a in apps if a["id"] == row["id"])
            if fields["status"] in tracker.SENT and not fields["applied_at"] and not original.get("applied_at"):
                fields.pop("applied_at")
            db.update_application(int(row["id"]), **fields)
        st.success("Gespeichert.")
        st.rerun()
    del_id = t2.selectbox("Stelle löschen", [a["id"] for a in apps],
                          format_func=lambda i: next(f'#{a["id"]} {a["title"]}' for a in apps if a["id"] == i))
    if t3.button("Löschen"):
        db.delete_application(del_id)
        st.rerun()
