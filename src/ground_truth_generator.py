
"""
HR Service System
Ground Truth Generator

Creates one deterministic ground-truth record per ticket.
Calculates expected SLA status from source timestamps and rules.
Refuses to overwrite existing ground-truth data.
"""

from pathlib import Path

import pandas as pd

from src.workflow_rules import ROUTING_RULES, CLARIFICATION_SCENARIOS
from src.sla_generator import SLA_TARGETS, EVALUATION_TIMESTAMP


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_FILE = DATA_DIR / "ground_truth.csv"

GROUND_TRUTH_COLUMNS = [
    "ground_truth_id",
    "entity_type",
    "entity_id",
    "issue_type",
    "expected_category",
    "expected_route",
    "expected_policy_version",
    "expected_sla_status",
    "expected_resolution_status",
    "expected_clarification",
    "severity",
]

RESOLUTION_MESSAGE_TYPES = {
    "RESOLUTION_MESSAGE",
    "RESOLUTION",
    "RESOLVED",
    "CLOSURE",
    "CLOSED",
}


def read_source(filename, required_columns):
    """Load a CSV file and validate its required columns."""
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Required source file not found: {path}"
        )

    df = pd.read_csv(path, dtype=str).fillna("")
    missing = set(required_columns) - set(df.columns)

    if missing:
        raise ValueError(
            f"{filename} is missing columns: {sorted(missing)}"
        )

    return df


def validate_unique_key(df, column, filename):
    """Reject blank or duplicate identifiers."""
    if df[column].str.strip().eq("").any():
        raise ValueError(
            f"{filename} contains blank values in {column}."
        )

    if df[column].duplicated().any():
        raise ValueError(
            f"{filename} contains duplicate values in {column}."
        )


def parse_boolean(value, field_name):
    """Parse a boolean value explicitly."""
    normalized = str(value).strip().lower()

    if normalized in {"true", "1", "yes", "y"}:
        return True

    if normalized in {"false", "0", "no", "n"}:
        return False

    raise ValueError(
        f"Invalid boolean for {field_name}: {value!r}"
    )


def load_inputs():
    """Load all source datasets."""
    tickets = read_source(
        "tickets.csv",
        [
            "ticket_id",
            "scenario_type",
            "category_id",
            "policy_id",
            "priority",
            "requires_clarification",
            "created_timestamp",
        ],
    )

    categories = read_source(
        "categories.csv",
        ["category_id", "category_name"],
    )

    versions = read_source(
        "policy_versions.csv",
        [
            "version_id",
            "policy_id",
            "is_current",
            "status",
        ],
    )

    resolutions = read_source(
        "resolutions.csv",
        [
            "ticket_id",
            "resolution_status",
            "resolved_timestamp",
        ],
    )

    messages = read_source(
        "messages.csv",
        [
            "ticket_id",
            "message_type",
            "sent_timestamp",
        ],
    )

    validate_unique_key(tickets, "ticket_id", "tickets.csv")
    validate_unique_key(categories, "category_id", "categories.csv")
    validate_unique_key(versions, "version_id", "policy_versions.csv")
    validate_unique_key(resolutions, "ticket_id", "resolutions.csv")

    if tickets.empty:
        raise ValueError("No tickets found.")

    return tickets, categories, versions, resolutions, messages


def build_category_map(categories):
    """Map category IDs to category names."""
    mapping = dict(
        zip(
            categories["category_id"],
            categories["category_name"],
        )
    )

    if any(
        not key.strip() or not value.strip()
        for key, value in mapping.items()
    ):
        raise ValueError(
            "Category master contains blank IDs or names."
        )

    return mapping


def build_current_policy_map(versions):
    """Find exactly one current version for each policy."""
    is_current = versions["is_current"].str.strip().str.lower().isin(
        {"true", "1", "yes", "y"}
    )

    current = versions[is_current].copy()
    current["status"] = current["status"].str.strip().str.upper()
    current = current[current["status"] == "CURRENT"]

    if current["policy_id"].duplicated().any():
        raise ValueError(
            "A policy has multiple current versions."
        )

    return dict(
        zip(
            current["policy_id"],
            current["version_id"],
        )
    )


def build_resolution_map(resolutions):
    """Map tickets to their resolution status and timestamp."""
    valid_statuses = {"PENDING", "RESOLVED"}
    mapping = {}

    for _, row in resolutions.iterrows():
        ticket_id = row["ticket_id"]
        status = row["resolution_status"].strip().upper()
        timestamp = row["resolved_timestamp"].strip()

        if status not in valid_statuses:
            raise ValueError(
                f"Invalid resolution status for {ticket_id}: {status}"
            )

        if status == "RESOLVED" and not timestamp:
            raise ValueError(
                f"Resolved ticket {ticket_id} has no timestamp."
            )

        if status == "PENDING" and timestamp:
            raise ValueError(
                f"Pending ticket {ticket_id} has a resolution timestamp."
            )

        mapping[ticket_id] = {
            "status": status,
            "resolved_timestamp": timestamp,
        }

    return mapping


def build_resolution_message_map(messages):
    """Find explicit resolution-message timestamps."""
    candidates = messages[
        messages["message_type"].str.strip().str.upper().isin(
            RESOLUTION_MESSAGE_TYPES
        )
    ]

    result = {}

    for _, row in candidates.iterrows():
        ticket_id = row["ticket_id"]

        timestamp = pd.to_datetime(
            row["sent_timestamp"],
            errors="raise",
        )

        if ticket_id in result:
            raise ValueError(
                f"Multiple resolution messages found for {ticket_id}."
            )

        result[ticket_id] = timestamp

    return result


def calculate_expected_sla(ticket, resolution, resolution_messages):
    """Calculate SLA status independently from SLA output records."""
    ticket_id = ticket["ticket_id"]
    priority = ticket["priority"].strip().upper()

    if priority not in SLA_TARGETS:
        raise ValueError(
            f"Unsupported priority for {ticket_id}: {priority}"
        )

    created = pd.to_datetime(
        ticket["created_timestamp"],
        errors="raise",
    )

    if created > EVALUATION_TIMESTAMP:
        raise ValueError(
            f"Ticket {ticket_id} was created after the SLA "
            "evaluation timestamp."
        )

    message_timestamp = resolution_messages.get(ticket_id)
    status = resolution["status"]
    resolution_timestamp = resolution["resolved_timestamp"]

    if status == "RESOLVED":
        if message_timestamp is None:
            raise ValueError(
                f"Resolved ticket {ticket_id} has no resolution message."
            )

        recorded_timestamp = pd.to_datetime(
            resolution_timestamp,
            errors="raise",
        )

        if message_timestamp != recorded_timestamp:
            raise ValueError(
                f"Resolution timestamp mismatch for {ticket_id}."
            )

        end_timestamp = message_timestamp

    else:
        if message_timestamp is not None:
            raise ValueError(
                f"Pending ticket {ticket_id} has a resolution message."
            )

        end_timestamp = EVALUATION_TIMESTAMP

    elapsed_hours = (
        end_timestamp - created
    ).total_seconds() / 3600

    if elapsed_hours < 0:
        raise ValueError(
            f"Negative elapsed time for ticket {ticket_id}."
        )

    target_hours = SLA_TARGETS[priority]

    if elapsed_hours > target_hours:
        return "BREACHED"

    return "WITHIN_SLA"


def generate_ground_truth():
    """Generate one deterministic record per source ticket."""
    (
        tickets,
        categories,
        versions,
        resolutions,
        messages,
    ) = load_inputs()

    category_map = build_category_map(categories)
    current_policy_map = build_current_policy_map(versions)
    resolution_map = build_resolution_map(resolutions)
    resolution_message_map = build_resolution_message_map(messages)

    ticket_ids = set(tickets["ticket_id"])

    if ticket_ids != set(resolution_map):
        raise ValueError(
            "Tickets and resolution records do not match."
        )

    records = []

    for _, ticket in tickets.iterrows():
        ticket_id = ticket["ticket_id"]
        category_id = ticket["category_id"]
        policy_id = ticket["policy_id"]
        scenario = ticket["scenario_type"].strip().upper()
        priority = ticket["priority"].strip().upper()

        if category_id not in category_map:
            raise ValueError(
                f"Unknown category {category_id} for {ticket_id}."
            )

        if policy_id not in current_policy_map:
            raise ValueError(
                f"No current policy version found for {policy_id}."
            )

        category_name = category_map[category_id]

        if category_name not in ROUTING_RULES:
            raise ValueError(
                f"No routing rule for category {category_name}."
            )

        expected_clarification = (
            scenario in CLARIFICATION_SCENARIOS
        )

        source_clarification = parse_boolean(
            ticket["requires_clarification"],
            f"{ticket_id}.requires_clarification",
        )

        if expected_clarification != source_clarification:
            raise ValueError(
                f"Clarification rule mismatch for {ticket_id}."
            )

        resolution = resolution_map[ticket_id]

        expected_sla_status = calculate_expected_sla(
            ticket,
            resolution,
            resolution_message_map,
        )

        records.append(
            {
                "ground_truth_id": f"GT-{ticket_id}",
                "entity_type": "TICKET",
                "entity_id": ticket_id,
                "issue_type": ticket["scenario_type"],
                "expected_category": category_name,
                "expected_route": ROUTING_RULES[category_name],
                "expected_policy_version": current_policy_map[policy_id],
                "expected_sla_status": expected_sla_status,
                "expected_resolution_status": resolution["status"],
                "expected_clarification": expected_clarification,
                "severity": priority,
            }
        )

    result = pd.DataFrame(
        records,
        columns=GROUND_TRUTH_COLUMNS,
    )

    expected_ticket_count = len(tickets)
    if (
        len(result) != expected_ticket_count
        or result["entity_id"].nunique() != expected_ticket_count
        or set(result["entity_id"]) != set(tickets["ticket_id"])
    ):
        raise ValueError(
            "Expected exactly one ground-truth record per input ticket."
        )

    if result["entity_id"].duplicated().any():
        raise ValueError("Duplicate ticket records generated.")

    if result["ground_truth_id"].duplicated().any():
        raise ValueError("Duplicate ground-truth IDs generated.")

    return result


def main():
    """Save the baseline without overwriting existing output."""
    if OUTPUT_FILE.exists():
        raise FileExistsError(
            f"{OUTPUT_FILE} already exists. "
            "Refusing to overwrite it."
        )

    result = generate_ground_truth()

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    print("Ground Truth generation completed.")
    print(f"Tickets processed: {result['entity_id'].nunique()}")
    print(f"Records generated: {len(result)}")
    print(f"Unique ground-truth IDs: {result['ground_truth_id'].nunique()}")
    print(f"Output saved to: {OUTPUT_FILE}")

    print("\nExpected SLA status:")
    print(result["expected_sla_status"].value_counts().to_string())

    print("\nExpected resolution status:")
    print(result["expected_resolution_status"].value_counts().to_string())

    print("\nExpected clarification:")
    print(result["expected_clarification"].value_counts().to_string())


if __name__ == "__main__":
    main()
