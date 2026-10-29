"""
HR Service System
SLA Generator

Generates one reproducible SLA record per ticket.
SLA outcomes are derived from timestamps and documented rules.
Existing SLA data is never silently overwritten.
"""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"

TICKETS_FILE = DATA_DIR / "tickets.csv"
MESSAGES_FILE = DATA_DIR / "messages.csv"
SLA_FILE = DATA_DIR / "sla_records.csv"

SLA_COLUMNS = [
    "sla_id",
    "ticket_id",
    "priority",
    "response_target_hours",
    "resolution_target_hours",
    "business_hours_only",
    "created_timestamp",
    "first_response_timestamp",
    "resolved_timestamp",
    "elapsed_hours",
    "sla_breached",
    "breach_reason",
]

# Documented priority-based targets, in hours.
SLA_TARGETS = {
    "LOW": 72,
    "MEDIUM": 48,
    "HIGH": 24,
    "CRITICAL": 8,
}

# Fixed evaluation timestamp for reproducible results.
# This is intentionally not based on the current system time.
EVALUATION_TIMESTAMP = pd.Timestamp("2026-10-28T00:00:00")


def load_inputs():
    """Load and validate the source datasets."""
    if not TICKETS_FILE.exists():
        raise FileNotFoundError(f"Tickets file not found: {TICKETS_FILE}")

    if not MESSAGES_FILE.exists():
        raise FileNotFoundError(f"Messages file not found: {MESSAGES_FILE}")

    tickets = pd.read_csv(TICKETS_FILE, dtype=str).fillna("")
    messages = pd.read_csv(MESSAGES_FILE, dtype=str).fillna("")

    required_ticket_columns = {
        "ticket_id",
        "priority",
        "created_timestamp",
        "ticket_status",
    }
    missing = required_ticket_columns - set(tickets.columns)

    if missing:
        raise ValueError(
            f"tickets.csv is missing required columns: {sorted(missing)}"
        )

    required_message_columns = {
        "ticket_id",
        "sender_type",
        "message_type",
        "sent_timestamp",
    }
    missing = required_message_columns - set(messages.columns)

    if missing:
        raise ValueError(
            f"messages.csv is missing required columns: {sorted(missing)}"
        )

    if tickets["ticket_id"].duplicated().any():
        raise ValueError("Duplicate ticket IDs found.")

    if tickets.empty:
        raise ValueError("No tickets found.")

    return tickets, messages


def get_first_response(messages_for_ticket, created_timestamp):
    """Find the earliest qualifying non-employee response after creation."""
    if messages_for_ticket.empty:
        return ""

    qualifying = messages_for_ticket[
        messages_for_ticket["sender_type"].str.upper().isin(
            {"HR", "HR_PARTNER", "IT", "OPERATIONS", "MANAGER"}
        )
    ].copy()

    if qualifying.empty:
        return ""

    qualifying["_timestamp"] = pd.to_datetime(
        qualifying["sent_timestamp"], errors="coerce"
    )
    qualifying = qualifying[
        qualifying["_timestamp"].notna()
        & (qualifying["_timestamp"] >= created_timestamp)
    ]

    if qualifying.empty:
        return ""

    return qualifying["_timestamp"].min().isoformat()


def get_resolution_timestamp(ticket, messages_for_ticket, created_timestamp):
    """Return the timestamp of an explicit resolution event, if present."""

    if messages_for_ticket.empty:
        return ""

    # Recognize the actual message type used in our dataset.
    candidates = messages_for_ticket[
        messages_for_ticket["message_type"].str.upper().isin(
            {
                "RESOLUTION_MESSAGE",
                "RESOLUTION",
                "RESOLVED",
                "CLOSURE",
                "CLOSED",
            }
        )
    ].copy()

    if candidates.empty:
        return ""

    candidates["_timestamp"] = pd.to_datetime(
        candidates["sent_timestamp"], errors="coerce"
    )

    candidates = candidates[
        candidates["_timestamp"].notna()
        & (candidates["_timestamp"] >= created_timestamp)
    ]

    if candidates.empty:
        return ""

    return candidates["_timestamp"].max().isoformat()


def calculate_elapsed_hours(created_timestamp, resolved_timestamp):
    """Calculate elapsed hours from resolution, or the fixed evaluation time."""
    end_timestamp = (
        pd.Timestamp(resolved_timestamp)
        if resolved_timestamp
        else EVALUATION_TIMESTAMP
    )

    elapsed = (end_timestamp - created_timestamp).total_seconds() / 3600

    if elapsed < 0:
        raise ValueError("Elapsed time cannot be negative.")

    return round(elapsed, 4)


def generate_sla_records(tickets, messages):
    """Create deterministic SLA records, one per ticket."""
    records = []

    messages_by_ticket = {
        ticket_id: group.copy()
        for ticket_id, group in messages.groupby("ticket_id")
    }

    for _, ticket in tickets.iterrows():
        ticket_id = ticket["ticket_id"]
        priority = ticket["priority"].strip().upper()

        if priority not in SLA_TARGETS:
            raise ValueError(
                f"Unsupported priority {priority!r} for ticket {ticket_id}."
            )

        created_timestamp = pd.to_datetime(
            ticket["created_timestamp"], errors="raise"
        )

        if created_timestamp > EVALUATION_TIMESTAMP:
            raise ValueError(
                f"Ticket {ticket_id} is created after the fixed "
                "SLA evaluation timestamp."
            )

        ticket_messages = messages_by_ticket.get(
            ticket_id,
            pd.DataFrame(columns=messages.columns),
        )

        first_response = get_first_response(
            ticket_messages,
            created_timestamp,
        )

        resolved_timestamp = get_resolution_timestamp(
            ticket,
            ticket_messages,
            created_timestamp,
        )

        # A resolved ticket must have an explicit resolution timestamp.
        # Otherwise it remains unresolved for SLA evaluation.
        elapsed_hours = calculate_elapsed_hours(
            created_timestamp,
            resolved_timestamp,
        )

        target_hours = SLA_TARGETS[priority]
        breached = elapsed_hours > target_hours

        if breached:
            breach_reason = (
                f"Resolution target exceeded: {elapsed_hours:.2f} hours "
                f"elapsed against a {target_hours}-hour target."
            )
        else:
            breach_reason = ""

        records.append(
            {
                "sla_id": f"SLA-{ticket_id}",
                "ticket_id": ticket_id,
                "priority": priority,
                "response_target_hours": target_hours,
                "resolution_target_hours": target_hours,
                "business_hours_only": False,
                "created_timestamp": created_timestamp.isoformat(),
                "first_response_timestamp": first_response,
                "resolved_timestamp": resolved_timestamp,
                "elapsed_hours": elapsed_hours,
                "sla_breached": bool(breached),
                "breach_reason": breach_reason,
            }
        )

    return pd.DataFrame(records, columns=SLA_COLUMNS)


def validate_generated_records(tickets, records):
    """Run basic consistency checks before writing the output."""
    if records["sla_id"].duplicated().any():
        raise ValueError("Generated duplicate SLA IDs.")

    if records["ticket_id"].duplicated().any():
        raise ValueError("Generated more than one SLA record per ticket.")

    if set(records["ticket_id"]) != set(tickets["ticket_id"]):
        raise ValueError("SLA records do not cover exactly the source tickets.")

    for _, record in records.iterrows():
        target = SLA_TARGETS[record["priority"]]

        if record["response_target_hours"] != target:
            raise ValueError(f"Invalid response target for {record['ticket_id']}.")

        if record["resolution_target_hours"] != target:
            raise ValueError(
                f"Invalid resolution target for {record['ticket_id']}."
            )

        expected_breach = (
            float(record["elapsed_hours"]) > record["resolution_target_hours"]
        )

        if bool(record["sla_breached"]) != expected_breach:
            raise ValueError(
                f"Incorrect breach calculation for {record['ticket_id']}."
            )

        if expected_breach and not record["breach_reason"]:
            raise ValueError(
                f"Missing breach reason for {record['ticket_id']}."
            )

        if not expected_breach and record["breach_reason"]:
            raise ValueError(
                f"Unexpected breach reason for {record['ticket_id']}."
            )


def main():
    """Generate SLA data without overwriting existing records."""
    if SLA_FILE.exists():
        raise FileExistsError(
            f"{SLA_FILE} already exists. Refusing to overwrite SLA records."
        )

    tickets, messages = load_inputs()
    records = generate_sla_records(tickets, messages)

    validate_generated_records(tickets, records)

    SLA_FILE.parent.mkdir(parents=True, exist_ok=True)
    records.to_csv(SLA_FILE, index=False)

    print(f"Tickets processed: {tickets['ticket_id'].nunique()}")
    print(f"SLA records generated: {len(records)}")
    print(f"Unique SLA IDs: {records['sla_id'].nunique()}")
    print(f"Evaluation timestamp: {EVALUATION_TIMESTAMP.isoformat()}")
    print(f"Output saved to: {SLA_FILE}")
    print("\nSLA breaches:")
    print(records["sla_breached"].value_counts().to_string())


if __name__ == "__main__":
    main()