
import json
from pathlib import Path

import pandas as pd


# The validator is in src/validators/, so parents[2] is the project root.
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "csv"
REPORT_FILE = (
    ROOT / "output" / "validation" / "ticket_event_validation_report.json"
)

VALID_STATES = {
    "OPEN",
    "WAITING_FOR_INFO",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED",
}

ALLOWED_TRANSITIONS = {
    "OPEN": {"WAITING_FOR_INFO", "IN_PROGRESS"},
    "WAITING_FOR_INFO": {"IN_PROGRESS"},
    "IN_PROGRESS": {"WAITING_FOR_INFO", "RESOLVED"},
    "RESOLVED": {"CLOSED"},
}

REQUIRED_COLUMNS = {
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
}


def read_csv(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main():
    events = read_csv("ticket_events.csv")
    tickets = read_csv("tickets.csv")
    messages = read_csv("messages.csv")
    assignments = read_csv("assignments.csv")
    resolutions = read_csv("resolutions.csv")

    checks = []

    def check(name, passed, details=""):
        checks.append({
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        })

    missing_columns = sorted(REQUIRED_COLUMNS - set(events.columns))
    check(
        "required_columns",
        not missing_columns,
        f"Missing columns: {missing_columns}",
    )

    if missing_columns:
        save_report(checks, events)
        print("Validation status: FAIL")
        print(f"Missing columns: {missing_columns}")
        raise SystemExit(1)

    ticket_ids = set(tickets["ticket_id"])
    message_ids = set(messages["message_id"])
    assignment_ids = set(assignments["assignment_id"])

    # IDs and foreign keys
    check(
        "event_ids_unique",
        events["event_id"].ne("").all() and events["event_id"].is_unique,
        f"{events['event_id'].nunique()} unique IDs / {len(events)} events",
    )

    check(
        "ticket_foreign_keys",
        events["ticket_id"].ne("").all()
        and set(events["ticket_id"]).issubset(ticket_ids),
        "Every event references an existing ticket.",
    )

    invalid_messages = sorted({
        value for value in events["related_message_id"]
        if value and value not in message_ids
    })
    check(
        "message_foreign_keys",
        not invalid_messages,
        f"Invalid message IDs: {invalid_messages[:10]}",
    )

    invalid_assignments = sorted({
        value for value in events["related_assignment_id"]
        if value and value not in assignment_ids
    })
    check(
        "assignment_foreign_keys",
        not invalid_assignments,
        f"Invalid assignment IDs: {invalid_assignments[:10]}",
    )

    # Required descriptive fields and timestamps
    check("event_types_present", events["event_type"].ne("").all())
    check("event_reasons_present", events["event_reason"].ne("").all())
    check("event_sources_present", events["event_source"].ne("").all())

    parsed = pd.to_datetime(events["event_timestamp"], errors="coerce")
    check(
        "timestamps_valid",
        parsed.notna().all(),
        f"Invalid timestamps: {int(parsed.isna().sum())}",
    )

    valid_states = (
        events["new_state"].isin(VALID_STATES).all()
        and events.loc[
            events["event_type"] != "TICKET_CREATED", "old_state"
        ].isin(VALID_STATES).all()
        and (
            events.loc[
                events["event_type"] == "TICKET_CREATED", "old_state"
            ] == ""
        ).all()
    )
    check("lifecycle_states_valid", valid_states)

    # Exactly one initial OPEN event per ticket
    initial = events[events["event_type"] == "TICKET_CREATED"]
    initial_counts = initial.groupby("ticket_id").size()
    bad_initial_counts = sorted(
        initial_counts[initial_counts != 1].index.tolist()
    )
    missing_initial = sorted(ticket_ids - set(initial_counts.index))

    initial_ok = (
        len(initial) == len(ticket_ids)
        and not missing_initial
        and not bad_initial_counts
        and (initial["old_state"] == "").all()
        and (initial["new_state"] == "OPEN").all()
    )
    check(
        "one_initial_open_event_per_ticket",
        initial_ok,
        f"Missing: {missing_initial}; incorrect counts: {bad_initial_counts}",
    )

    # Replay each ticket's state history chronologically.
    ordered = events.copy()
    ordered["_timestamp"] = pd.to_datetime(
        ordered["event_timestamp"], errors="coerce"
    )
    ordered["_row_order"] = range(len(ordered))
    ordered = ordered.sort_values(
        ["ticket_id", "_timestamp", "_row_order"],
        kind="stable",
    )

    transition_errors = []
    backwards_timestamps = []
    final_states = {}

    for ticket_id, group in ordered.groupby("ticket_id", sort=False):
        current_state = None
        previous_timestamp = None

        for row in group.to_dict("records"):
            timestamp = row["_timestamp"]
            event_type = row["event_type"]
            old_state = row["old_state"]
            new_state = row["new_state"]

            if pd.isna(timestamp):
                continue

            if (
                previous_timestamp is not None
                and timestamp < previous_timestamp
            ):
                backwards_timestamps.append(ticket_id)

            previous_timestamp = timestamp

            if event_type == "TICKET_CREATED":
                if current_state is not None:
                    transition_errors.append(
                        f"{ticket_id}: duplicate ticket creation"
                    )
                current_state = "OPEN"
                continue

            if current_state is None:
                transition_errors.append(
                    f"{ticket_id}: event before ticket creation "
                    f"({row['event_id']})"
                )
                continue

            if old_state != current_state:
                transition_errors.append(
                    f"{ticket_id} / {row['event_id']}: expected "
                    f"{current_state}, got {old_state}"
                )
                continue

            # Assignment and message activities may retain the same state.
            if new_state == current_state:
                continue

            if new_state not in ALLOWED_TRANSITIONS.get(current_state, set()):
                transition_errors.append(
                    f"{ticket_id} / {row['event_id']}: illegal transition "
                    f"{current_state} -> {new_state}"
                )
                continue

            current_state = new_state

        final_states[ticket_id] = current_state

    check(
        "legal_chronological_state_transitions",
        not transition_errors,
        f"Errors: {transition_errors[:10]}",
    )

    check(
        "timestamps_non_decreasing_per_ticket",
        not backwards_timestamps,
        f"Tickets with backwards timestamps: "
        f"{sorted(set(backwards_timestamps))[:10]}",
    )

    # Every resolved source record must have exactly one matching event.
    resolved_source = resolutions[
        resolutions["resolution_status"] == "RESOLVED"
    ]
    expected_resolved = set(resolved_source["ticket_id"])

    resolution_events = events[
        events["event_type"] == "TICKET_RESOLVED"
    ]
    actual_resolved = set(resolution_events["ticket_id"])
    resolution_counts = resolution_events.groupby("ticket_id").size()
    duplicate_resolutions = sorted(
        resolution_counts[resolution_counts != 1].index.tolist()
    )

    check(
        "resolution_events_match_source",
        expected_resolved == actual_resolved
        and not duplicate_resolutions,
        f"Missing: {sorted(expected_resolved - actual_resolved)}; "
        f"unexpected: {sorted(actual_resolved - expected_resolved)}; "
        f"duplicates: {duplicate_resolutions}",
    )

    pending_tickets = set(
        resolutions.loc[
            resolutions["resolution_status"] != "RESOLVED", "ticket_id"
        ]
    )
    falsely_resolved = sorted(pending_tickets & actual_resolved)

    check(
        "pending_tickets_not_resolved",
        not falsely_resolved,
        f"Incorrectly resolved: {falsely_resolved}",
    )

    # The current source data has no confirmed CLOSED tickets.
    closed_events = events[events["new_state"] == "CLOSED"]
    check(
        "closure_events_supported",
        closed_events.empty,
        f"Unexpected CLOSED events: "
        f"{closed_events['ticket_id'].tolist()}",
    )

    # Resolution timestamps must match their source records exactly.
    expected_times = {
        row["ticket_id"]: row["resolved_timestamp"]
        for row in resolved_source.to_dict("records")
    }
    timestamp_mismatches = []

    for row in resolution_events.to_dict("records"):
        if expected_times.get(row["ticket_id"]) != row["event_timestamp"]:
            timestamp_mismatches.append(row["ticket_id"])

    check(
        "resolution_timestamps_match_source",
        not timestamp_mismatches,
        f"Mismatches: {timestamp_mismatches}",
    )

    expected_ticket_count = len(ticket_ids)
    check(
        "expected_event_volume",
        len(events) >= expected_ticket_count,
        f"Event count: {len(events)} for {expected_ticket_count} tickets; "
        "expected at least one event per ticket.",
    )

    check(
        "all_tickets_covered",
        set(events["ticket_id"]) == ticket_ids,
        f"Covered {events['ticket_id'].nunique()} of {len(ticket_ids)} tickets",
    )

    save_report(checks, events)

    failed = [item for item in checks if item["status"] == "FAIL"]

    print(f"Validation status: {'PASS' if not failed else 'FAIL'}")
    print(f"Checks passed: {len(checks) - len(failed)}")
    print(f"Checks failed: {len(failed)}")

    for item in checks:
        print(f"[{item['status']}] {item['check']}")
        if item["status"] == "FAIL":
            print(f"  {item['details']}")

    print(f"\nReport saved to: {REPORT_FILE}")

    if failed:
        raise SystemExit(1)


def save_report(checks, events):
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    failed_count = sum(item["status"] == "FAIL" for item in checks)
    report = {
        "validation_status": "FAIL" if failed_count else "PASS",
        "event_count": len(events),
        "unique_ticket_count": (
            int(events["ticket_id"].nunique())
            if "ticket_id" in events.columns else 0
        ),
        "checks_passed": sum(
            item["status"] == "PASS" for item in checks
        ),
        "checks_failed": failed_count,
        "checks": checks,
    }

    REPORT_FILE.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
