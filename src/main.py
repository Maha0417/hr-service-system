"""Command-line interface for the HR Service System."""

import argparse
import json
import sqlite3
from pathlib import Path

from src.request_processor import process_ticket
from src.runtime_store import (
    connect,
    get_ticket_history,
    initialize_runtime_store,
)

ROOT = Path(__file__).resolve().parent.parent


def show_history(ticket_id):
    history = get_ticket_history(ticket_id)

    print(f"\nTicket: {ticket_id}")
    print(f"Subject: {history['source_ticket']['ticket_subject']}")

    state = history["runtime_state"]
    if not state:
        print("Runtime status: NOT PROCESSED")
        print("Run: python -m src.main process", ticket_id)
        return

    print(f"State: {state['current_state']}")
    print(f"Assigned group: {state['assigned_group']}")
    print(f"Priority: {state['priority']}")

    print("\nAssignments:")
    for item in history["assignments"]:
        print(
            f"  {item['assigned_group']} | "
            f"{item['assignment_reason']} | {item['assigned_at']}"
        )

    print("\nMessages:")
    for item in history["messages"]:
        print(
            f"  [{item['message_type']}] {item['sender_type']}: "
            f"{item['message_content']}"
        )

    print("\nEvents:")
    for item in history["events"]:
        details = json.loads(item["details_json"])
        print(
            f"  {item['event_type']} | {item['state']} | "
            f"{json.dumps(details, ensure_ascii=False)}"
        )


def show_summary():
    initialize_runtime_store()

    with connect() as db:
        print("\nHR SERVICE SYSTEM — RUNTIME SUMMARY")
        print("=" * 42)

        tables = (
            "tickets",
            "runtime_ticket_state",
            "runtime_assignments",
            "runtime_messages",
            "runtime_events",
        )

        for table in tables:
            count = db.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
            print(f"{table}: {count}")

        print("\nProcessed ticket states:")
        rows = db.execute(
            """
            SELECT current_state, COUNT(*) AS total
            FROM runtime_ticket_state
            GROUP BY current_state
            ORDER BY current_state
            """
        ).fetchall()

        if rows:
            for row in rows:
                print(f"  {row['current_state']}: {row['total']}")
        else:
            print("  No processed tickets yet.")

        print("\nCurrent assignment groups:")
        rows = db.execute(
            """
            SELECT assigned_group, COUNT(*) AS total
            FROM runtime_ticket_state
            GROUP BY assigned_group
            ORDER BY total DESC, assigned_group
            """
        ).fetchall()

        if rows:
            for row in rows:
                print(f"  {row['assigned_group']}: {row['total']}")
        else:
            print("  No assignments yet.")


def main():
    parser = argparse.ArgumentParser(
        description="HR Service System workflow CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser(
        "process", help="Process and persist an HR ticket"
    )
    process_parser.add_argument("ticket_id")

    history_parser = subparsers.add_parser(
        "history", help="Display a ticket's persisted history"
    )
    history_parser.add_argument("ticket_id")

    subparsers.add_parser(
        "summary", help="Display runtime counts and metrics"
    )

    args = parser.parse_args()

    if args.command == "process":
        process_ticket(args.ticket_id)
    elif args.command == "history":
        show_history(args.ticket_id)
    elif args.command == "summary":
        show_summary()


if __name__ == "__main__":
    main()
