
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "csv"
OUTPUT_FILE = DATA_DIR / "ticket_events.csv"

ALLOWED_TRANSITIONS = {
    "OPEN": {"WAITING_FOR_INFO", "IN_PROGRESS"},
    "WAITING_FOR_INFO": {"IN_PROGRESS"},
    "IN_PROGRESS": {"WAITING_FOR_INFO", "RESOLVED"},
    "RESOLVED": {"CLOSED"},
}

VALID_STATES = set(ALLOWED_TRANSITIONS) | {"CLOSED"}

EVENT_PRIORITY = {
    "TICKET_CREATED": 0,
    "ASSIGNMENT_RECORDED": 1,
    "CLARIFICATION_REQUEST": 2,
    "CLARIFICATION_RESPONSE": 3,
    "POLICY_RESPONSE": 4,
    "ESCALATION_NOTICE": 5,
    "RESOLUTION_MESSAGE": 6,
    "TICKET_RESOLVED": 7,
}


def load_csv(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def require_columns(df, columns, filename):
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{filename} is missing columns: {missing}")


def generate_events():
    tickets = load_csv("tickets.csv")
    messages = load_csv("messages.csv")
    assignments = load_csv("assignments.csv")
    resolutions = load_csv("resolutions.csv")

    require_columns(
        tickets,
        ["ticket_id", "created_timestamp"],
        "tickets.csv",
    )
    require_columns(
        messages,
        [
            "message_id", "ticket_id", "message_type",
            "sent_timestamp", "lifecycle_state",
        ],
        "messages.csv",
    )
    require_columns(
        assignments,
        [
            "assignment_id", "ticket_id",
            "assigned_timestamp", "assigned_group",
        ],
        "assignments.csv",
    )
    require_columns(
        resolutions,
        [
            "resolution_id", "ticket_id", "resolution_status",
            "resolved_timestamp", "resolution_notes",
        ],
        "resolutions.csv",
    )

    ticket_ids = set(tickets["ticket_id"])

    for filename, df in [
        ("messages.csv", messages),
        ("assignments.csv", assignments),
        ("resolutions.csv", resolutions),
    ]:
        unknown = set(df["ticket_id"]) - ticket_ids
        unknown.discard("")
        if unknown:
            raise ValueError(
                f"{filename} references unknown tickets: "
                f"{sorted(unknown)[:10]}"
            )

    events = []

    def add_event(
        ticket_id,
        timestamp,
        old_state,
        new_state,
        event_type,
        reason,
        source,
        message_id="",
        assignment_id="",
    ):
        if not timestamp:
            raise ValueError(
                f"Missing timestamp for {event_type}, ticket {ticket_id}"
            )

        events.append({
            "event_id": "",
            "ticket_id": ticket_id,
            "old_state": old_state,
            "new_state": new_state,
            "event_timestamp": timestamp,
            "event_type": event_type,
            "event_reason": reason,
            "event_source": source,
            "related_message_id": message_id,
            "related_assignment_id": assignment_id,
        })

    message_groups = {
        ticket_id: group.to_dict("records")
        for ticket_id, group in messages.groupby("ticket_id")
    }
    assignment_groups = {
        ticket_id: group.to_dict("records")
        for ticket_id, group in assignments.groupby("ticket_id")
    }
    resolution_groups = {
        ticket_id: group.to_dict("records")
        for ticket_id, group in resolutions.groupby("ticket_id")
    }

    for ticket in tickets.to_dict("records"):
        ticket_id = ticket["ticket_id"]

        initial_message = next(
            (
                message
                for message in message_groups.get(ticket_id, [])
                if message["message_type"] == "INITIAL_REQUEST"
            ),
            None,
        )

        add_event(
            ticket_id,
            ticket["created_timestamp"],
            "",
            "OPEN",
            "TICKET_CREATED",
            "Ticket created in the source ticket dataset.",
            "tickets.csv",
            message_id=initial_message["message_id"] if initial_message else "",
        )

        # Preserve assignments as operational events.
        for assignment in assignment_groups.get(ticket_id, []):
            add_event(
                ticket_id,
                assignment["assigned_timestamp"],
                "",
                "",
                "ASSIGNMENT_RECORDED",
                f"Assignment recorded for group "
                f"{assignment['assigned_group']}.",
                "assignments.csv",
                assignment_id=assignment["assignment_id"],
            )

        timeline = []

        for message in message_groups.get(ticket_id, []):
            if message["message_type"] == "INITIAL_REQUEST":
                continue

            timeline.append({
                "timestamp": message["sent_timestamp"],
                "kind": "MESSAGE",
                "record": message,
            })

        for resolution in resolution_groups.get(ticket_id, []):
            if resolution["resolution_status"] == "RESOLVED":
                timeline.append({
                    "timestamp": resolution["resolved_timestamp"],
                    "kind": "RESOLUTION",
                    "record": resolution,
                })

        timeline.sort(key=lambda item: (
            item["timestamp"],
            0 if item["kind"] == "MESSAGE" else 1,
            item["record"].get("message_id", ""),
        ))

        current_state = "OPEN"

        for item in timeline:
            timestamp = item["timestamp"]
            record = item["record"]

            if item["kind"] == "MESSAGE":
                target_state = record["lifecycle_state"]
                message_type = record["message_type"]

                if target_state not in VALID_STATES:
                    raise ValueError(
                        f"Invalid state {target_state!r} in message "
                        f"{record['message_id']}"
                    )

                if target_state != current_state:
                    if target_state not in ALLOWED_TRANSITIONS.get(
                        current_state, set()
                    ):
                        raise ValueError(
                            f"Illegal transition for {ticket_id}: "
                            f"{current_state} -> {target_state}; "
                            f"message {record['message_id']}"
                        )

                add_event(
                    ticket_id,
                    timestamp,
                    current_state,
                    target_state,
                    message_type,
                    f"Recorded message activity: {message_type}.",
                    "messages.csv",
                    message_id=record["message_id"],
                )

                current_state = target_state

            else:
                if "RESOLVED" not in ALLOWED_TRANSITIONS.get(
                    current_state, set()
                ):
                    raise ValueError(
                        f"Cannot resolve {ticket_id} from {current_state}"
                    )

                add_event(
                    ticket_id,
                    timestamp,
                    current_state,
                    "RESOLVED",
                    "TICKET_RESOLVED",
                    "Resolution recorded in resolutions.csv.",
                    "resolutions.csv",
                )

                current_state = "RESOLVED"

    # Sort events per ticket. Creation always precedes assignment at equal
    # timestamps; other events use their documented priority.
    events.sort(key=lambda event: (
        event["ticket_id"],
        event["event_timestamp"],
        EVENT_PRIORITY.get(event["event_type"], 99),
        event["event_type"],
    ))

    # Reconstruct assignment states using the preceding chronological state.
    for ticket_id in sorted(ticket_ids):
        ticket_events = [
            event for event in events
            if event["ticket_id"] == ticket_id
        ]

        current_state = None

        for event in ticket_events:
            event_type = event["event_type"]

            if event_type == "TICKET_CREATED":
                if current_state is not None:
                    raise ValueError(
                        f"Duplicate creation event for {ticket_id}"
                    )

                current_state = "OPEN"
                continue

            if current_state is None:
                raise ValueError(
                    f"{ticket_id}: event occurred before ticket creation"
                )

            if event_type == "ASSIGNMENT_RECORDED":
                event["old_state"] = current_state
                event["new_state"] = current_state
                continue

            if event["old_state"] != current_state:
                raise ValueError(
                    f"{ticket_id}: expected old state {current_state}, "
                    f"found {event['old_state']} in {event_type}"
                )

            target_state = event["new_state"]

            if target_state != current_state:
                if target_state not in ALLOWED_TRANSITIONS.get(
                    current_state, set()
                ):
                    raise ValueError(
                        f"{ticket_id}: illegal transition "
                        f"{current_state} -> {target_state}"
                    )

                current_state = target_state

    # Link events to the most recent assignment at or before their timestamp.
    for event in events:
        if event["related_assignment_id"]:
            continue

        candidates = [
            assignment
            for assignment in assignment_groups.get(
                event["ticket_id"], []
            )
            if assignment["assigned_timestamp"] <= event["event_timestamp"]
        ]

        if candidates:
            candidates.sort(key=lambda assignment: (
                assignment["assigned_timestamp"],
                assignment["assignment_id"],
            ))
            event["related_assignment_id"] = candidates[-1]["assignment_id"]

    for number, event in enumerate(events, start=1):
        event["event_id"] = f"EVT-2026-{number:06d}"

    columns = [
        "event_id",
        "ticket_id",
        "old_state",
        "new_state",
        "event_timestamp",
        "event_type",
        "event_reason",
        "event_source",
        "related_message_id",
        "related_assignment_id",
    ]

    output = pd.DataFrame(events, columns=columns)

    if output["event_id"].duplicated().any():
        raise ValueError("Duplicate event IDs generated")

    if output["ticket_id"].eq("").any():
        raise ValueError("An event has no ticket ID")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_FILE, index=False)

    print(f"Generated {len(output)} ticket events.")
    print(f"Unique event IDs: {output['event_id'].nunique()}")
    print(f"Tickets covered: {output['ticket_id'].nunique()}")
    print(
        "Actual state changes:",
        int((output["old_state"] != output["new_state"]).sum()),
    )
    print("\nEvent types:")
    print(output["event_type"].value_counts().to_string())
    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_events()
