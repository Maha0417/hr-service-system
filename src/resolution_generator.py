
import logging
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_FILE = DATA_DIR / "resolutions.csv"

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

RESOLUTION_TYPES = {
    "NORMAL": "POLICY_GUIDANCE",
    "AMBIGUOUS": "CLARIFICATION",
    "MISSING_CONTEXT": "ADDITIONAL_INFORMATION",
    "CONFIDENTIAL": "CONFIDENTIAL_HR_REVIEW",
    "OUTDATED_POLICY": "POLICY_CORRECTION",
}


def load_csv(filename, required_columns):
    path = DATA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required source file missing: {path}")

    df = pd.read_csv(path)
    missing = set(required_columns) - set(df.columns)
    if missing:
        raise ValueError(f"{filename} missing columns: {sorted(missing)}")
    return df


def is_true(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def generate_resolutions():
    if OUTPUT_FILE.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing output: {OUTPUT_FILE}"
        )

    tickets = load_csv(
        "tickets.csv",
        {"ticket_id", "scenario_type", "policy_id",
         "current_assignment_group"},
    )
    versions = load_csv(
        "policy_versions.csv",
        {"version_id", "policy_id", "version_number", "is_current"},
    )
    policies = load_csv("policy_documents.csv", {"policy_id", "policy_name"})
    messages = load_csv(
        "messages.csv",
        {"ticket_id", "message_type", "sent_timestamp"},
    )
    assignments = load_csv(
        "assignments.csv",
        {"ticket_id", "assigned_group", "assigned_timestamp"},
    )

    if tickets["ticket_id"].duplicated().any():
        raise ValueError("Duplicate ticket IDs found")
    if tickets["ticket_id"].isna().any() or tickets["ticket_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Empty ticket IDs found")

    if versions["version_id"].duplicated().any():
        raise ValueError("Duplicate policy version IDs found")

    versions = versions.copy()
    versions["_current"] = versions["is_current"].map(is_true)
    current = versions[versions["_current"]]

    if current["policy_id"].duplicated().any():
        raise ValueError("Multiple current versions exist for a policy")

    current_by_policy = current.set_index("policy_id").to_dict("index")
    policy_names = policies.set_index("policy_id")["policy_name"].to_dict()

    ticket_ids = set(tickets["ticket_id"])
    if not set(messages["ticket_id"].dropna()).issubset(ticket_ids):
        raise ValueError("Messages contain unknown ticket IDs")

    resolution_messages = messages[
        messages["message_type"].eq("RESOLUTION_MESSAGE")
    ].copy()

    if resolution_messages["ticket_id"].duplicated().any():
        raise ValueError("Duplicate resolution messages for a ticket")

    resolution_messages["sent_timestamp"] = pd.to_datetime(
        resolution_messages["sent_timestamp"], errors="raise"
    )
    resolved_by_ticket = resolution_messages.set_index("ticket_id").to_dict(
        "index"
    )

    records = []

    for _, ticket in tickets.iterrows():
        ticket_id = ticket["ticket_id"]
        scenario = ticket["scenario_type"]
        policy_id = ticket["policy_id"]

        if scenario not in RESOLUTION_TYPES:
            raise ValueError(f"Unsupported scenario: {scenario}")

        policy = current_by_policy.get(policy_id)
        if policy is None:
            raise ValueError(f"No current policy version for {ticket_id}")

        resolution_message = resolved_by_ticket.get(ticket_id)
        resolved = resolution_message is not None

        if resolved:
            timestamp = resolution_message["sent_timestamp"].isoformat(
                timespec="seconds"
            )
            version_id = policy["version_id"]

            ticket_assignments = assignments[
                assignments["ticket_id"].eq(ticket_id)
            ].copy()

            if not ticket_assignments.empty:
                ticket_assignments["_time"] = pd.to_datetime(
                    ticket_assignments["assigned_timestamp"], errors="raise"
                )
                latest = ticket_assignments.sort_values("_time").iloc[-1]
                assigned_group = latest["assigned_group"]
            else:
                assigned_group = ticket["current_assignment_group"]

            resolver = (
                "HR_PARTNER" if assigned_group == "HR_PARTNER" else "HR_AGENT"
            )
            status = "RESOLVED"
            outcome = (
                "Confidential case resolved by HR Partner"
                if scenario == "CONFIDENTIAL"
                else "Policy guidance provided"
            )
            citation = (
                f"{policy_names.get(policy_id, policy_id)}; "
                f"version {policy['version_number']}; "
                f"reference {version_id}"
            )
            notes = (
                f"Supported by an existing RESOLUTION_MESSAGE. "
                f"Scenario: {scenario}. Current policy version selected."
            )
        else:
            timestamp = None
            version_id = None
            resolver = None
            status = "PENDING"
            outcome = "Awaiting resolution"
            citation = "Not yet applied; resolution is pending"
            notes = (
                f"Ticket remains unresolved. Scenario: {scenario}. "
                "No resolution timestamp or applied policy version invented."
            )

        records.append({
            "resolution_id": f"RES-{ticket_id}",
            "ticket_id": ticket_id,
            "policy_version_id": version_id,
            "resolution_type": RESOLUTION_TYPES[scenario],
            "resolution_status": status,
            "resolved_by": resolver,
            "resolved_timestamp": timestamp,
            "outcome": outcome,
            "resolution_notes": notes,
            "policy_citation": citation,
        })

    result = pd.DataFrame(records)

    expected_ticket_count = len(tickets)
    if (
        len(result) != expected_ticket_count
        or result["ticket_id"].nunique() != expected_ticket_count
        or set(result["ticket_id"]) != set(tickets["ticket_id"])
    ):
        raise ValueError("Expected exactly one resolution per input ticket")

    if result["resolution_id"].duplicated().any():
        raise ValueError("Duplicate resolution IDs generated")

    if (result["resolution_status"] == "RESOLVED").sum() != len(
        resolution_messages
    ):
        raise ValueError("Resolved record count differs from message history")

    # Recheck immediately before writing.
    if OUTPUT_FILE.exists():
        raise FileExistsError(f"Refusing to overwrite {OUTPUT_FILE}")

    result.to_csv(OUTPUT_FILE, index=False)

    logger.info("Generated %d resolution records", len(result))
    logger.info(
        "Resolved: %d; Pending: %d",
        (result["resolution_status"] == "RESOLVED").sum(),
        (result["resolution_status"] == "PENDING").sum(),
    )
    logger.info("Saved to %s", OUTPUT_FILE)
    return result


if __name__ == "__main__":
    generate_resolutions()
