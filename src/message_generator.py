
"""Generate traceable conversation history for HR service tickets."""

from pathlib import Path

import pandas as pd

from workflow_rules import LIFECYCLE_STATES
from scale_config import SCENARIO_COUNTS


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"

TICKETS_FILE = DATA_DIR / "tickets.csv"
POLICY_VERSIONS_FILE = DATA_DIR / "policy_versions.csv"
OUTPUT_FILE = DATA_DIR / "messages.csv"

MESSAGE_COLUMNS = [
    "message_id",
    "ticket_id",
    "sender_type",
    "message_type",
    "policy_version_id",
    "sent_timestamp",
    "message_content",
    "lifecycle_state",
]

EXPECTED_SCENARIO_COUNTS = SCENARIO_COUNTS

# Each entry: sender, type, content template, lifecycle state.
SCENARIO_FLOWS = {
    "NORMAL": [
        (
            "EMPLOYEE",
            "INITIAL_REQUEST",
            "Hello, I need help with: {subject}. {description}",
            "OPEN",
        ),
        (
            "HR_AGENT",
            "POLICY_RESPONSE",
            "Based on the applicable current policy, here is guidance "
            "for your request: {subject}. Please contact HR if you "
            "need further clarification.",
            "IN_PROGRESS",
        ),
    ],
    "AMBIGUOUS": [
        (
            "EMPLOYEE",
            "INITIAL_REQUEST",
            "I have a question about: {subject}. {description}",
            "OPEN",
        ),
        (
            "HR_AGENT",
            "CLARIFICATION_REQUEST",
            "Could you clarify the details of your request about "
            "{subject} so we can provide accurate guidance?",
            "WAITING_FOR_INFO",
        ),
        (
            "EMPLOYEE",
            "CLARIFICATION_RESPONSE",
            "Here is the additional information regarding my request: "
            "{description}",
            "IN_PROGRESS",
        ),
        (
            "HR_AGENT",
            "POLICY_RESPONSE",
            "Thank you for clarifying. Based on the current applicable "
            "policy, here is the guidance for {subject}.",
            "IN_PROGRESS",
        ),
    ],
    "MISSING_CONTEXT": [
        (
            "EMPLOYEE",
            "INITIAL_REQUEST",
            "I need assistance with {subject}. {description}",
            "OPEN",
        ),
        (
            "HR_AGENT",
            "CLARIFICATION_REQUEST",
            "We need some additional information about {subject} "
            "before we can process your request.",
            "WAITING_FOR_INFO",
        ),
        (
            "EMPLOYEE",
            "CLARIFICATION_RESPONSE",
            "Here is the additional context for my request: "
            "{description}",
            "IN_PROGRESS",
        ),
        (
            "HR_AGENT",
            "POLICY_RESPONSE",
            "Thank you for providing the information. Please follow "
            "the current applicable policy for {subject}.",
            "IN_PROGRESS",
        ),
    ],
    "CONFIDENTIAL": [
        (
            "EMPLOYEE",
            "INITIAL_REQUEST",
            "I need confidential assistance regarding: {subject}.",
            "OPEN",
        ),
        (
            "SYSTEM",
            "ESCALATION_NOTICE",
            "This sensitive request has been routed to the HR Partner "
            "for confidential handling.",
            "IN_PROGRESS",
        ),
        (
            "HR_PARTNER",
            "RESOLUTION_MESSAGE",
            "Your confidential request has been received by the HR "
            "Partner. The case will be handled through the appropriate "
            "confidential process.",
            "IN_PROGRESS",
        ),
    ],
    "OUTDATED_POLICY": [
        (
            "EMPLOYEE",
            "INITIAL_REQUEST",
            "I am referring to an older policy for {subject}. "
            "{description}",
            "OPEN",
        ),
        (
            "SYSTEM",
            "POLICY_RESPONSE",
            "The referenced policy version is being checked against "
            "the current approved version.",
            "IN_PROGRESS",
        ),
        (
            "HR_AGENT",
            "POLICY_RESPONSE",
            "Please use the current approved policy version for "
            "{subject}. The older version should not be used as the "
            "basis for this request.",
            "IN_PROGRESS",
        ),
    ],
}


def _as_bool(value):
    """Interpret common CSV Boolean representations safely."""
    if pd.isna(value):
        return False
    return str(value).strip().upper() in {"TRUE", "Y", "YES", "1"}


def _load_data():
    """Load and check the source datasets."""
    for path in (TICKETS_FILE, POLICY_VERSIONS_FILE):
        if not path.is_file():
            raise FileNotFoundError(f"Required source file not found: {path}")

    tickets = pd.read_csv(TICKETS_FILE, dtype=str).fillna("")
    versions = pd.read_csv(POLICY_VERSIONS_FILE, dtype=str).fillna("")

    required_ticket_columns = {
        "ticket_id",
        "scenario_type",
        "policy_id",
        "ticket_subject",
        "ticket_description",
        "created_timestamp",
    }
    required_version_columns = {
        "version_id",
        "policy_id",
        "is_current",
    }

    missing_ticket_columns = required_ticket_columns - set(tickets.columns)
    missing_version_columns = required_version_columns - set(versions.columns)

    if missing_ticket_columns:
        raise ValueError(
            f"Missing ticket columns: {sorted(missing_ticket_columns)}"
        )
    if missing_version_columns:
        raise ValueError(
            f"Missing policy-version columns: {sorted(missing_version_columns)}"
        )

    if tickets["ticket_id"].duplicated().any():
        raise ValueError("Duplicate ticket IDs found in tickets.csv")

    if tickets["ticket_id"].eq("").any():
        raise ValueError("A ticket has an empty ticket_id")

    actual_counts = tickets["scenario_type"].value_counts().to_dict()
    if actual_counts != EXPECTED_SCENARIO_COUNTS:
        raise ValueError(
            f"Unexpected ticket scenario distribution: {actual_counts}"
        )

    if versions["version_id"].eq("").any():
        raise ValueError("A policy version has an empty version_id")

    if versions["version_id"].duplicated().any():
        raise ValueError("Duplicate policy version IDs found")

    ticket_policy_ids = set(versions["policy_id"])
    missing_policies = set(tickets["policy_id"]) - ticket_policy_ids
    if missing_policies:
        raise ValueError(
            f"Tickets reference policies without versions: "
            f"{sorted(missing_policies)}"
        )

    return tickets, versions


def _select_policy_versions(versions):
    """Index current policy versions by policy ID."""
    current = versions[
        versions["is_current"].map(_as_bool)
    ].copy()

    if current["policy_id"].duplicated().any():
        raise ValueError(
            "More than one current policy version exists for a policy"
        )

    return {
        row["policy_id"]: row["version_id"]
        for row in current.to_dict("records")
    }


def generate_messages():
    """Generate scenario-specific messages and save messages.csv."""
    tickets, versions = _load_data()
    current_versions = _select_policy_versions(versions)
    valid_version_ids = set(versions["version_id"])
    messages = []

    for ticket in tickets.to_dict("records"):
        ticket_id = ticket["ticket_id"]
        scenario = ticket["scenario_type"].strip().upper()
        policy_id = ticket["policy_id"]

        if scenario not in SCENARIO_FLOWS:
            raise ValueError(
                f"Unsupported scenario {scenario!r} for {ticket_id}"
            )

        if policy_id not in current_versions:
            raise ValueError(
                f"No current policy version found for policy {policy_id}"
            )

        current_version_id = current_versions[policy_id]

        try:
            ticket_created = pd.Timestamp(ticket["created_timestamp"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid creation timestamp for {ticket_id}: "
                f"{ticket['created_timestamp']!r}"
            ) from exc

        if pd.isna(ticket_created):
            raise ValueError(f"Missing creation timestamp for {ticket_id}")

        previous_timestamp = ticket_created
        flow = SCENARIO_FLOWS[scenario]

        for sequence, (sender, message_type, template, state) in enumerate(
            flow, start=1
        ):
            # A message must follow ticket creation and earlier messages.
            sent_timestamp = previous_timestamp + pd.Timedelta(minutes=5)

            # A policy response must reference a valid policy version.
            policy_version_id = (
                current_version_id
                if message_type == "POLICY_RESPONSE"
                else ""
            )

            content = template.format(
                subject=ticket["ticket_subject"].strip(),
                description=ticket["ticket_description"].strip(),
            ).strip()

            if not content:
                raise ValueError(
                    f"Empty message content for ticket {ticket_id}"
                )

            if state not in LIFECYCLE_STATES:
                raise ValueError(
                    f"Invalid message lifecycle state {state!r}"
                )

            if (
                policy_version_id
                and policy_version_id not in valid_version_ids
            ):
                raise ValueError(
                    f"Invalid policy version {policy_version_id}"
                )

            messages.append(
                {
                    "message_id": (
                        f"MSG-{ticket_id}-{sequence:03d}"
                    ),
                    "ticket_id": ticket_id,
                    "sender_type": sender,
                    "message_type": message_type,
                    "policy_version_id": policy_version_id,
                    "sent_timestamp": sent_timestamp.isoformat(),
                    "message_content": content,
                    "lifecycle_state": state,
                }
            )

            previous_timestamp = sent_timestamp

    result = pd.DataFrame(messages, columns=MESSAGE_COLUMNS)

    expected_messages = sum(
        len(SCENARIO_FLOWS[scenario]) * count
        for scenario, count in EXPECTED_SCENARIO_COUNTS.items()
    )
    if len(result) != expected_messages:
        raise ValueError(
            f"Expected {expected_messages} messages, generated {len(result)}"
        )

    if result["message_id"].duplicated().any():
        raise ValueError("Duplicate message IDs generated")

    if not result["ticket_id"].isin(tickets["ticket_id"]).all():
        raise ValueError("Generated messages contain invalid ticket references")

    # Preserve existing message history instead of overwriting it.
    if OUTPUT_FILE.exists():
        raise FileExistsError(
            f"{OUTPUT_FILE} already exists. Refusing to overwrite message history."
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)

    print(f"Tickets processed: {len(tickets)}")
    print(f"Messages generated: {len(result)}")
    print(f"Output saved to: {OUTPUT_FILE}")
    print("\nMessages by scenario:")

    scenario_by_ticket = tickets.set_index("ticket_id")["scenario_type"]
    result["scenario_type"] = result["ticket_id"].map(scenario_by_ticket)
    print(result.groupby("scenario_type").size().to_string())


if __name__ == "__main__":
    generate_messages()
