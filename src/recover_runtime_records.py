import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_FILE = ROOT / "data" / "sql" / "hr_service_system.sqlite"
BACKUP_FILE = ROOT / "data" / "sql" / "hr_service_system.pre_recovery_backup.sqlite"
AUDIT_FILE = ROOT / "data" / "runtime" / "processed_requests.jsonl"

TARGET_IDS = {
    "TKT-2026-000001",
    "TKT-2026-000002",
    "TKT-2026-000003",
    "TKT-2026-000004",
}


def load_records():
    if not AUDIT_FILE.is_file():
        raise FileNotFoundError(f"Audit log missing: {AUDIT_FILE}")

    records = [
        json.loads(line)
        for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = [r for r in records if r.get("ticket_id") in TARGET_IDS]

    found = [r.get("ticket_id") for r in selected]
    if len(selected) != len(TARGET_IDS) or set(found) != TARGET_IDS:
        raise ValueError("Audit log must contain exactly one record for each target ticket.")
    if len(found) != len(set(found)):
        raise ValueError("Duplicate audit records found for target tickets.")

    return selected


def validate_record(db, record):
    tid = record["ticket_id"]
    decision = record.get("decision", {})
    messages = record.get("messages", [])
    events = record.get("events", [])

    for key in ("recommended_state", "assigned_group", "priority"):
        if not decision.get(key):
            raise ValueError(f"{tid}: missing decision field {key}")

    if not db.execute(
        "SELECT 1 FROM tickets WHERE ticket_id=?", (tid,)
    ).fetchone():
        raise ValueError(f"{tid}: source ticket missing")

    if db.execute(
        "SELECT 1 FROM runtime_ticket_state WHERE ticket_id=?", (tid,)
    ).fetchone():
        raise ValueError(f"{tid}: runtime state already exists")

    for message in messages:
        for key in (
            "message_id", "ticket_id", "sender_type", "message_type",
            "sent_timestamp", "message_content", "lifecycle_state",
        ):
            if key not in message:
                raise ValueError(f"{tid}: message missing {key}")
        if message["ticket_id"] != tid:
            raise ValueError(f"{tid}: message ticket mismatch")
        if db.execute(
            "SELECT 1 FROM runtime_messages WHERE message_id=?",
            (message["message_id"],),
        ).fetchone():
            raise ValueError(f"{tid}: message ID already exists: {message['message_id']}")

        version = message.get("policy_version_id", "")
        if version and not db.execute(
            "SELECT 1 FROM policy_versions WHERE version_id=?", (version,)
        ).fetchone():
            raise ValueError(f"{tid}: policy version missing: {version}")

    message_ids = {m["message_id"] for m in messages}
    for event in events:
        for key in (
            "event_id", "ticket_id", "event_type",
            "event_timestamp", "state",
        ):
            if key not in event:
                raise ValueError(f"{tid}: event missing {key}")
        if event["ticket_id"] != tid:
            raise ValueError(f"{tid}: event ticket mismatch")
        if db.execute(
            "SELECT 1 FROM runtime_events WHERE event_id=?",
            (event["event_id"],),
        ).fetchone():
            raise ValueError(f"{tid}: event ID already exists: {event['event_id']}")
        mid = event.get("message_id") or ""
        if mid and mid not in message_ids:
            raise ValueError(f"{tid}: event references absent audit message: {mid}")

    if not messages or not events:
        raise ValueError(f"{tid}: messages/events unexpectedly empty")


def main():
    if not BACKUP_FILE.is_file():
        raise FileNotFoundError(f"Verified backup missing: {BACKUP_FILE}")

    backup = sqlite3.connect(
        f"file:{BACKUP_FILE.resolve().as_posix()}?mode=ro", uri=True
    )
    try:
        integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Backup integrity check failed: {integrity}")
    finally:
        backup.close()

    records = load_records()
    db = sqlite3.connect(f"file:{DB_FILE.resolve().as_posix()}?mode=ro", uri=True)
    try:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Current database integrity check failed")

        for record in records:
            validate_record(db, record)

        fk_issues = db.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise ValueError(f"Current database has foreign-key violations: {fk_issues[:5]}")

        print("DRY RUN PASSED — no database writes performed.")
        print("Backup integrity: ok")
        print("Target records validated:", len(records))
        print("Messages to restore:", sum(len(r.get("messages", [])) for r in records))
        print("Events to restore:", sum(len(r.get("events", [])) for r in records))
        print("Ticket states to restore:", len(records))
        print("Assignments to restore:", sum(
            2 if r["decision"].get("original_assigned_group")
               and r["decision"]["original_assigned_group"] != r["decision"]["assigned_group"]
            else 1
            for r in records
        ))
        for record in records:
            if any(m.get("message_type") == "RESOLUTION_MESSAGE"
                   for m in record.get("messages", [])) and record["decision"].get(
                       "recommended_state"
                   ) not in ("RESOLVED", "CLOSED"):
                print(
                    "REVIEW WARNING:",
                    record["ticket_id"],
                    "has a resolution message but decision state is",
                    record["decision"].get("recommended_state"),
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
