import argparse
import json
import sqlite3

from src.recover_runtime_records import (
    BACKUP_FILE,
    DB_FILE,
    load_records,
    validate_record,
)


def connect_readonly(path):
    return sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro", uri=True
    )


def validate_backup():
    if not BACKUP_FILE.is_file():
        raise FileNotFoundError(f"Verified backup missing: {BACKUP_FILE}")
    with connect_readonly(BACKUP_FILE) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError(f"Backup integrity failed: {result}")


def insert_record(db, record):
    tid = record["ticket_id"]
    decision = record["decision"]
    now = record["processed_at"]

    db.execute(
        """INSERT INTO runtime_ticket_state
           (ticket_id, current_state, assigned_group, priority, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            tid,
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
            (tid, original_group, "INITIAL_ROUTING", now),
        )

    db.execute(
        """INSERT INTO runtime_assignments
           (ticket_id, assigned_group, assignment_reason, assigned_at)
           VALUES (?, ?, ?, ?)""",
        (
            tid,
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
            key: value
            for key, value in event.items()
            if key not in {
                "event_id", "ticket_id", "event_type",
                "event_timestamp", "message_id", "state",
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply recovery. Without this flag, perform dry run only.",
    )
    args = parser.parse_args()

    validate_backup()
    records = load_records()

    if not args.apply:
        with connect_readonly(DB_FILE) as db:
            for record in records:
                validate_record(db, record)
        print("DRY RUN PASSED — no database writes performed.")
        print("Backup integrity: ok")
        print("Tickets:", len(records))
        print("Assignments:", sum(
            2 if r["decision"].get("original_assigned_group")
               and r["decision"]["original_assigned_group"]
                   != r["decision"]["assigned_group"]
            else 1 for r in records
        ))
        print("Messages:", sum(len(r.get("messages", [])) for r in records))
        print("Events:", sum(len(r.get("events", [])) for r in records))
        print("Audit log will not be modified.")
        return

    # Revalidate all records and perform every insert in one transaction.
    db = sqlite3.connect(DB_FILE, timeout=30)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("BEGIN IMMEDIATE")

        for record in records:
            validate_record(db, record)

        for record in records:
            insert_record(db, record)

        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"Foreign-key violations after recovery: {violations[:5]}")

        expected = {
            "runtime_ticket_state": len(records),
            "runtime_assignments": sum(
                2 if r["decision"].get("original_assigned_group")
                   and r["decision"]["original_assigned_group"]
                       != r["decision"]["assigned_group"]
                else 1 for r in records
            ),
            "runtime_messages": sum(len(r.get("messages", [])) for r in records),
            "runtime_events": sum(len(r.get("events", [])) for r in records),
        }

        for table, count in expected.items():
            actual = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ticket_id IN ({','.join('?' for _ in records)})",
                [r["ticket_id"] for r in records],
            ).fetchone()[0]
            if actual != count:
                raise ValueError(
                    f"{table}: expected {count} recovered rows, found {actual}"
                )

        db.commit()
        print("RECOVERY COMMITTED")
        for table, count in expected.items():
            print(f"{table}: {count} rows verified")
        print("Foreign-key violations: 0")
        print("Original JSONL audit log: unchanged")
        print("Resolution/state discrepancy, if any, was preserved.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
