import sqlite3
from datetime import datetime

from src import config


def db_path():
    return config.data_dir() / "bewerbungen.db"

STATUS_OPTIONS = ["gefunden", "in Bearbeitung", "beworben", "Gespräch", "Zusage", "Absage"]

_COLUMNS = {
    "source", "external_id", "title", "company", "location", "url", "description",
    "recipient", "status", "score", "analysis", "cv_json", "letter_json",
    "cv_pdf", "letter_pdf", "notes",
    "review_json", "interview_json", "applied_at", "follow_up_at", "interview_at", "deadline",
}
# Spalten, die nach der ersten Version dazugekommen sind (werden bei Bedarf ergänzt)
_ADDED_COLUMNS = ["review_json", "interview_json", "applied_at", "follow_up_at", "interview_at", "deadline"]


def _connect() -> sqlite3.Connection:
    config.data_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, external_id TEXT,
                title TEXT, company TEXT, location TEXT, url TEXT, description TEXT,
                recipient TEXT,
                status TEXT DEFAULT 'gefunden',
                score INTEGER, analysis TEXT,
                cv_json TEXT, letter_json TEXT, cv_pdf TEXT, letter_pdf TEXT,
                notes TEXT,
                created_at TEXT, updated_at TEXT,
                UNIQUE(source, external_id)
            )
            """
        )
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(applications)")}
        for column in _ADDED_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE applications ADD COLUMN {column} TEXT")


def add_application(job: dict) -> int | None:
    """Gibt die neue ID zurück, oder None falls die Stelle schon existiert."""
    fields = {k: v for k, v in job.items() if k in _COLUMNS}
    now = datetime.now().isoformat(timespec="seconds")
    fields |= {"created_at": now, "updated_at": now}
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    with _connect() as conn:
        cur = conn.execute(
            f"INSERT OR IGNORE INTO applications ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
        return cur.lastrowid if cur.rowcount else None


def find_application(source: str, external_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE source = ? AND external_id = ?", (source, external_id)
        ).fetchone()
    return dict(row) if row else None


def list_applications() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_application(app_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    return dict(row) if row else None


def update_application(app_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in _COLUMNS}
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if fields.get("status") in ("beworben", "Gespräch", "Zusage", "Absage"):
        current = get_application(app_id)
        if current and not current.get("applied_at"):
            fields.setdefault("applied_at", datetime.now().date().isoformat())
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE applications SET {assignments} WHERE id = ?",
            [*fields.values(), app_id],
        )


def delete_application(app_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
