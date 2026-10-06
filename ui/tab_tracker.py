
import pandas as pd
import streamlit as st

from src import db


def render() -> None:
    apps = db.list_applications()
    if not apps:
        st.info("Noch keine Bewerbungen.")
    else:
        df = pd.DataFrame(apps)
        counts = df["status"].value_counts()
        for col, status in zip(st.columns(len(db.STATUS_OPTIONS)), db.STATUS_OPTIONS):
            col.metric(status, int(counts.get(status, 0)))

        df = df[["id", "status", "score", "title", "company", "location", "source", "url", "notes", "updated_at"]]
        edited = st.data_editor(
            df,
            hide_index=True,
            width="stretch",
            disabled=["id", "score", "title", "company", "location", "source", "url", "updated_at"],
            column_config={
                "id": "ID",
                "status": st.column_config.SelectboxColumn("Status", options=db.STATUS_OPTIONS, required=True),
                "score": st.column_config.NumberColumn("Passung %"),
                "title": "Stelle",
                "company": "Firma",
                "location": "Ort",
                "source": "Quelle",
                "url": st.column_config.LinkColumn("Link", display_text="öffnen"),
                "notes": "Notizen",
                "updated_at": "Geändert",
            },
            key="tracker_editor",
        )
        t1, t2, t3 = st.columns([1, 2, 1])
        if t1.button("Änderungen speichern", type="primary"):
            for row in edited.to_dict("records"):
                notes = row["notes"] if isinstance(row["notes"], str) else None
                db.update_application(int(row["id"]), status=row["status"], notes=notes)
            st.success("Gespeichert.")
            st.rerun()
        del_id = t2.selectbox("Stelle löschen", [a["id"] for a in apps],
                              format_func=lambda i: next(f'#{a["id"]} {a["title"]}' for a in apps if a["id"] == i))
        if t3.button("Löschen"):
            db.delete_application(del_id)
            st.rerun()
