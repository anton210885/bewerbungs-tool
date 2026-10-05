import sqlite3
from datetime import datetime

from src.config import DATA_DIR

DB_PATH = DATA_DIR / "bewerbungen.db"

STATUS_OPTIONS = ["gefunden", "in Bearbeitung", "beworben", "Gespräch", "Zusage", "Absage"]

_COLUMNS = {
    "source", "external_id", "title", "company", "location", "url", "description",
    "recipient", "status", "score", "analysis", "cv_json", "letter_json",
    "cv_pdf", "letter_pdf", "notes",
}


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(
            f"UPDATE applications SET {assignments} WHERE id = ?",
            [*fields.values(), app_id],
        )


def delete_application(app_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
