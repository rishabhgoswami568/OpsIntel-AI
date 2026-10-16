import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "opspilot.db"


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (
                    decision IN ('Approved', 'Rejected', 'Needs review')
                ),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                )
            )
        """)


def save_review(incident_id: str, decision: str, note: str = ""):
    allowed = {"Approved", "Rejected", "Needs review"}
    if decision not in allowed:
        raise ValueError("Unsupported review decision.")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO reviews (incident_id, decision, note)
            VALUES (?, ?, ?)
            """,
            (incident_id, decision, note.strip()),
        )


def latest_reviews() -> dict[str, dict]:
    """Return the most recent review decision for each incident."""
    with connect() as conn:
        rows = conn.execute("""
            SELECT r.incident_id, r.decision, r.note, r.created_at
            FROM reviews r
            JOIN (
                SELECT incident_id, MAX(id) AS latest_id
                FROM reviews
                GROUP BY incident_id
            ) latest ON latest.latest_id = r.id
        """).fetchall()

    return {row["incident_id"]: dict(row) for row in rows}


def audit_history():
    with connect() as conn:
        rows = conn.execute("""
            SELECT id, incident_id, decision, note, created_at
            FROM reviews
            ORDER BY id DESC
        """).fetchall()

    return [dict(row) for row in rows]