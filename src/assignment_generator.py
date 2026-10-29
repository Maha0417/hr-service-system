"""
HR Service System
Assignment History Generator

Creates initial assignments and explicit reassignment events.
Uses workflow_rules.py as the single source of truth for routing.

Existing assignment history is never overwritten or deleted.
"""

from pathlib import Path

import pandas as pd

from src.workflow_rules import ROUTING_RULES


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"

TICKETS_FILE = DATA_DIR / "tickets.csv"
CATEGORIES_FILE = DATA_DIR / "categories.csv"
ASSIGNMENTS_FILE = DATA_DIR / "assignments.csv"

ASSIGNMENT_COLUMNS = [
    "assignment_id",
    "ticket_id",
    "assigned_group",
    "assigned_to",
    "assignment_reason",
    "assigned_timestamp",
    "assignment_status",
    "previous_assignment_id",
]

SENIOR_TEAM_RULES = {
    "Benefits": "SENIOR_BENEFITS_TEAM",
    "Leave": "SENIOR_LEAVE_TEAM",
    "Payroll": "SENIOR_PAYROLL_TEAM",
    "Onboarding": "SENIOR_ONBOARDING_TEAM",
    "Employee Relations": "HR_PARTNER",
}


def load_input_data():
    """Load and validate the ticket and category source data."""
    if not TICKETS_FILE.exists():
        raise FileNotFoundError(f"Tickets file not found: {TICKETS_FILE}")

    if not CATEGORIES_FILE.exists():
        raise FileNotFoundError(f"Categories file not found: {CATEGORIES_FILE}")

    tickets = pd.read_csv(TICKETS_FILE, dtype=str).fillna("")
    categories = pd.read_csv(CATEGORIES_FILE, dtype=str).fillna("")

    required_ticket_columns = {
        "ticket_id",
        "scenario_type",
        "category_id",
        "created_timestamp",
        "sensitive_flag",
    }
    required_category_columns = {"category_id", "category_name"}

    missing_ticket_columns = required_ticket_columns - set(tickets.columns)
    missing_category_columns = required_category_columns - set(categories.columns)

    if missing_ticket_columns:
        raise ValueError(
            f"tickets.csv is missing columns: {sorted(missing_ticket_columns)}"
        )

    if missing_category_columns:
        raise ValueError(
            f"categories.csv is missing columns: {sorted(missing_category_columns)}"
        )

    if tickets.empty:
        raise ValueError("No tickets found.")

    if tickets["ticket_id"].duplicated().any():
        raise ValueError("Duplicate ticket IDs found in tickets.csv.")

    if categories["category_id"].duplicated().any():
        raise ValueError("Duplicate category IDs found in categories.csv.")

    category_lookup = categories.set_index("category_id")["category_name"].to_dict()

    return tickets, category_lookup


def load_existing_assignments():
    """Load existing history without modifying it."""
    if not ASSIGNMENTS_FILE.exists():
        return pd.DataFrame(columns=ASSIGNMENT_COLUMNS)

    existing = pd.read_csv(ASSIGNMENTS_FILE, dtype=str).fillna("")

    missing_columns = set(ASSIGNMENT_COLUMNS) - set(existing.columns)
    if missing_columns:
        raise ValueError(
            f"assignments.csv is missing columns: {sorted(missing_columns)}"
        )

    if existing["assignment_id"].duplicated().any():
        raise ValueError("Existing assignment history contains duplicate IDs.")

    return existing[ASSIGNMENT_COLUMNS].copy()


def generate_assignment_history(tickets, category_lookup, existing):
    """
    Generate only missing assignment events.

    Existing assignments are preserved. For a ticket that already has an
    assignment history, new events are linked to its latest assignment.
    """
    new_records = []

    existing_ids = set(existing["assignment_id"])
    existing_tickets = set(existing["ticket_id"])

    existing_by_ticket = {
        ticket_id: group.sort_values("assigned_timestamp")
        for ticket_id, group in existing.groupby("ticket_id")
    }

    for _, ticket in tickets.iterrows():
        ticket_id = ticket["ticket_id"]
        scenario = ticket["scenario_type"].strip().upper()
        category_id = ticket["category_id"]

        if category_id not in category_lookup:
            raise ValueError(
                f"Ticket {ticket_id} references unknown category {category_id}."
            )

        category_name = category_lookup[category_id]

        if category_name not in ROUTING_RULES:
            raise ValueError(f"No routing rule for category {category_name!r}.")

        assigned_group = ROUTING_RULES[category_name]
        created_timestamp = pd.to_datetime(
            ticket["created_timestamp"], errors="raise"
        )

        if category_name == "Employee Relations" and assigned_group != "HR_PARTNER":
            raise ValueError(
                f"Employee Relations ticket {ticket_id} must route to HR_PARTNER."
            )

        # Determine the ticket's existing assignment chain.
        if ticket_id in existing_by_ticket:
            history = existing_by_ticket[ticket_id]

            # The latest assignment is determined by timestamp.
            latest = history.iloc[-1]
            previous_id = latest["assignment_id"]
            latest_group = latest["assigned_group"]
            latest_timestamp = pd.to_datetime(
                latest["assigned_timestamp"], errors="raise"
            )

            # Do not generate a second initial assignment.
            has_initial = (
                history["assignment_reason"] == "INITIAL_ROUTING"
            ).any()
        else:
            previous_id = ""
            latest_group = ""
            latest_timestamp = None
            has_initial = False

        ticket_new_records = []

        def add_assignment(group, reason, timestamp):
            nonlocal previous_id, latest_group, latest_timestamp

            sequence = 1
            while f"ASN-{ticket_id}-{sequence:03d}" in existing_ids or any(
                record["assignment_id"] == f"ASN-{ticket_id}-{sequence:03d}"
                for record in new_records + ticket_new_records
            ):
                sequence += 1

            assignment_id = f"ASN-{ticket_id}-{sequence:03d}"

            if latest_timestamp is not None and timestamp <= latest_timestamp:
                raise ValueError(
                    f"New assignment timestamp must follow existing history "
                    f"for ticket {ticket_id}."
                )


            ticket_new_records.append(
                {
                    "assignment_id": assignment_id,
                    "ticket_id": ticket_id,
                    "assigned_group": group,
                    "assigned_to": "",
                    "assignment_reason": reason,
                    "assigned_timestamp": timestamp.isoformat(),
                    "assignment_status": "ACTIVE",
                    "previous_assignment_id": previous_id,
                }
            )

            previous_id = assignment_id
            latest_group = group
            latest_timestamp = timestamp

        if not has_initial:
            add_assignment(
                assigned_group,
                "INITIAL_ROUTING",
                created_timestamp,
            )

        # Existing tickets with only initial assignments may receive the
        # applicable missing reassignment event.
        if scenario == "OUTDATED_POLICY":
            senior_team = SENIOR_TEAM_RULES.get(category_name)

            if (
                senior_team
                and senior_team != assigned_group
                and latest_group != senior_team
            ):
                add_assignment(
                    senior_team,
                    "ESCALATION",
                    max(
                        created_timestamp + pd.Timedelta(hours=1),
                        (latest_timestamp + pd.Timedelta(minutes=1))
                        if latest_timestamp is not None
                        else created_timestamp + pd.Timedelta(hours=1),
                    ),
                )

        elif scenario == "CONFIDENTIAL":
            if assigned_group != "HR_PARTNER" and latest_group != "HR_PARTNER":
                add_assignment(
                    "HR_PARTNER",
                    "SENSITIVE_CASE_ROUTING",
                    max(
                        created_timestamp + pd.Timedelta(minutes=5),
                        (latest_timestamp + pd.Timedelta(minutes=1))
                        if latest_timestamp is not None
                        else created_timestamp + pd.Timedelta(minutes=5),
                    ),
                )

        new_records.extend(ticket_new_records)

    generated = pd.DataFrame(new_records, columns=ASSIGNMENT_COLUMNS)

    if not generated.empty and generated["assignment_id"].duplicated().any():
        raise ValueError("Generated duplicate assignment IDs.")

    return generated


def validate_assignment_history(tickets, combined):
    """Validate assignment history without modifying existing records."""
    if combined["assignment_id"].duplicated().any():
        raise ValueError("Duplicate assignment IDs found.")

    valid_tickets = set(tickets["ticket_id"])
    invalid_tickets = set(combined["ticket_id"]) - valid_tickets

    if invalid_tickets:
        raise ValueError(
            f"Assignments reference unknown tickets: {invalid_tickets}"
        )

    ticket_created = tickets.set_index("ticket_id")["created_timestamp"].map(
        lambda value: pd.to_datetime(value, errors="raise")
    )

    result = combined.copy()
    result["_timestamp"] = pd.to_datetime(
        result["assigned_timestamp"], errors="raise"
    )

    for ticket_id, group in result.groupby("ticket_id"):
        group = group.sort_values(
            ["_timestamp", "assignment_id"]
        ).reset_index(drop=True)

        if (group["_timestamp"] < ticket_created[ticket_id]).any():
            raise ValueError(
                f"Assignment precedes ticket creation for {ticket_id}."
            )

        if group["_timestamp"].duplicated().any():
            raise ValueError(
                f"Assignment timestamps must be unique per ticket: {ticket_id}."
            )

        for position, row in group.iterrows():
            previous_id = row["previous_assignment_id"]

            if position == 0:
                if previous_id:
                    raise ValueError(
                        f"Initial assignment for {ticket_id} "
                        "must not reference a previous assignment."
                    )
            else:
                expected_previous_id = group.iloc[position - 1]["assignment_id"]

                if previous_id != expected_previous_id:
                    raise ValueError(
                        f"Broken assignment chain for {ticket_id}: "
                        f"expected {expected_previous_id}, found {previous_id!r}."
                    )

        # The latest assignment is the current one.
        # Do not rewrite historical assignment_status values.

    return result.drop(columns=["_timestamp"])


def main():
    """Append new events while preserving existing assignment records."""
    tickets, category_lookup = load_input_data()
    existing = load_existing_assignments()

    generated = generate_assignment_history(
        tickets,
        category_lookup,
        existing,
    )

    if generated.empty:
        print("No new assignment events required. Existing history preserved.")
        print(f"Existing assignments: {len(existing)}")
        return

    # Preserve the existing records exactly as they were saved.
    combined = pd.concat([existing, generated], ignore_index=True)

    # Validate the combined history before writing.
    combined = validate_assignment_history(tickets, combined)

    # Ensure existing records have not been altered by validation.
    if not combined.iloc[:len(existing)][ASSIGNMENT_COLUMNS].equals(
        existing[ASSIGNMENT_COLUMNS]
    ):
        raise ValueError(
            "Existing assignment history changed. Refusing to save."
        )

    # Append only new records to the existing file.
    generated[ASSIGNMENT_COLUMNS].to_csv(
        ASSIGNMENTS_FILE,
        mode="a",
        header=False,
        index=False,
    )

    print(f"Tickets processed: {tickets['ticket_id'].nunique()}")
    print(f"Existing assignments preserved: {len(existing)}")
    print(f"New assignments appended: {len(generated)}")
    print(f"Total assignments: {len(combined)}")
    print(f"Output saved to: {ASSIGNMENTS_FILE}")
    print("\nAssignments by reason:")
    print(combined["assignment_reason"].value_counts().to_string())
    print("\nAssignments by group:")
    print(combined["assigned_group"].value_counts().to_string())


if __name__ == "__main__":
    main()
