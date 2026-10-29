"""SQLite persistence for live HR workflow processing."""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_FILE = ROOT / "data" / "sql" / "hr_service_system.sqlite"


def connect():
    if not DB_FILE.is_file():
        raise FileNotFoundError(
            f"Dataset database not found: {DB_FILE}. "
            "Run the dataset export before initializing runtime storage."
        )
    connection = sqlite3.connect(DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_runtime_store():
    """Create runtime tables without dropping or rebuilding source tables."""
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS runtime_ticket_state (
                ticket_id TEXT PRIMARY KEY,
                current_state TEXT NOT NULL,
                assigned_group TEXT NOT NULL,
                priority TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            );

            CREATE TABLE IF NOT EXISTS runtime_assignments (
                assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                assigned_group TEXT NOT NULL,
                assignment_reason TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            );

            CREATE TABLE IF NOT EXISTS runtime_messages (
                message_id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                sender_type TEXT NOT NULL,
                message_type TEXT NOT NULL,
                sent_timestamp TEXT NOT NULL,
                message_content TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL,
                policy_version_id TEXT,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            );

            CREATE TABLE IF NOT EXISTS runtime_events (
                event_id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                message_id TEXT,
                state TEXT NOT NULL,
                details_json TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            );

            CREATE INDEX IF NOT EXISTS idx_runtime_events_ticket
                ON runtime_events(ticket_id, event_timestamp);

            CREATE INDEX IF NOT EXISTS idx_runtime_messages_ticket
                ON runtime_messages(ticket_id, sent_timestamp);

            CREATE INDEX IF NOT EXISTS idx_runtime_assignments_ticket
                ON runtime_assignments(ticket_id, assigned_at);
        """)


def save_processed_record(record):
    """Persist one processed ticket and all its runtime records atomically."""
    ticket_id = record["ticket_id"]
    decision = record["decision"]
    now = record["processed_at"]

    with connect() as db:
        exists = db.execute(
            "SELECT 1 FROM tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        if exists is None:
            raise ValueError(f"Unknown source ticket: {ticket_id}")

        if db.execute(
            "SELECT 1 FROM runtime_ticket_state WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone():
            raise ValueError(f"Ticket already persisted: {ticket_id}")

        db.execute(
            """INSERT INTO runtime_ticket_state
               (ticket_id, current_state, assigned_group, priority, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                ticket_id,
                decision["recommended_state"],
                decision["assigned_group"],
                decision["priority"],
                now,
            ),
        )

        original_group = decision.get(
            "original_assigned_group", decision["assigned_group"]
        )
        if original_group != decision["assigned_group"]:
            db.execute(
                """INSERT INTO runtime_assignments
                   (ticket_id, assigned_group, assignment_reason, assigned_at)
                   VALUES (?, ?, ?, ?)""",
                (ticket_id, original_group, "INITIAL_ROUTING", now),
            )

        db.execute(
            """INSERT INTO runtime_assignments
               (ticket_id, assigned_group, assignment_reason, assigned_at)
               VALUES (?, ?, ?, ?)""",
            (
                ticket_id,
                decision["assigned_group"],
                decision.get("routing_reason", "WORKFLOW_ROUTING"),
                now,
            ),
        )

        for message in record.get("messages", []):
            db.execute(
                """INSERT INTO runtime_messages
                   (message_id, ticket_id, sender_type, message_type,
                    sent_timestamp, message_content, lifecycle_state,
                    policy_version_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message["message_id"],
                    message["ticket_id"],
                    message["sender_type"],
                    message["message_type"],
                    message["sent_timestamp"],
                    message["message_content"],
                    message["lifecycle_state"],
                    message.get("policy_version_id", ""),
                ),
            )

        for event in record.get("events", []):
            details = {
                key: value for key, value in event.items()
                if key not in {
                    "event_id", "ticket_id", "event_type",
                    "event_timestamp", "message_id", "state"
                }
            }
            db.execute(
                """INSERT INTO runtime_events
                   (event_id, ticket_id, event_type, event_timestamp,
                    message_id, state, details_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["event_id"],
                    event["ticket_id"],
                    event["event_type"],
                    event["event_timestamp"],
                    event.get("message_id") or None,
                    event["state"],
                    json.dumps(details, ensure_ascii=False),
                ),
            )


def get_ticket_history(ticket_id):
    """Return persisted state, assignments, messages and events for a ticket."""
    with connect() as db:
        source = db.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if source is None:
            raise ValueError(f"Unknown source ticket: {ticket_id}")

        state = db.execute(
            "SELECT * FROM runtime_ticket_state WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        assignments = db.execute(
            """SELECT * FROM runtime_assignments WHERE ticket_id = ?
               ORDER BY assignment_id""",
            (ticket_id,),
        ).fetchall()
        messages = db.execute(
            """SELECT * FROM runtime_messages WHERE ticket_id = ?
               ORDER BY sent_timestamp, message_id""",
            (ticket_id,),
        ).fetchall()
        events = db.execute(
            """SELECT * FROM runtime_events WHERE ticket_id = ?
               ORDER BY event_timestamp, event_id""",
            (ticket_id,),
        ).fetchall()

        return {
            "source_ticket": dict(source),
            "runtime_state": dict(state) if state else None,
            "assignments": [dict(row) for row in assignments],
            "messages": [dict(row) for row in messages],
            "events": [dict(row) for row in events],
        }


if __name__ == "__main__":
    initialize_runtime_store()
    with connect() as db:
        for table in (
            "runtime_ticket_state",
            "runtime_assignments",
            "runtime_messages",
            "runtime_events",
        ):
            count = db.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
            print(f"{table}: ready ({count} records)")
