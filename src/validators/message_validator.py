
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "validation"

MESSAGES_FILE = DATA_DIR / "messages.csv"
TICKETS_FILE = DATA_DIR / "tickets.csv"
VERSIONS_FILE = DATA_DIR / "policy_versions.csv"

REPORT_FILE = OUTPUT_DIR / "message_validation_report.json"

REQUIRED_COLUMNS = [
    "message_id",
    "ticket_id",
    "sender_type",
    "message_type",
    "policy_version_id",
    "sent_timestamp",
    "message_content",
    "lifecycle_state",
]

ALLOWED_SENDER_TYPES = {
    "EMPLOYEE",
    "HR_AGENT",
    "HR_PARTNER",
    "MANAGER",
    "IT_PARTNER",
    "SYSTEM",
}

ALLOWED_MESSAGE_TYPES = {
    "INITIAL_REQUEST",
    "POLICY_RESPONSE",
    "CLARIFICATION_REQUEST",
    "CLARIFICATION_RESPONSE",
    "ESCALATION_NOTICE",
    "RESOLUTION_MESSAGE",
    "STATUS_UPDATE",
    "EMPLOYEE_ACKNOWLEDGEMENT",
}


def add_check(checks, name, condition, details):
    checks.append({
        "check": name,
        "status": "PASS" if condition else "FAIL",
        "details": details,
    })


def validate_messages():
    for path in (MESSAGES_FILE, TICKETS_FILE, VERSIONS_FILE):
        if not path.is_file():
            raise FileNotFoundError(f"Missing required dataset: {path}")

    messages = pd.read_csv(MESSAGES_FILE, dtype=str).fillna("")
    tickets = pd.read_csv(TICKETS_FILE, dtype=str).fillna("")
    versions = pd.read_csv(VERSIONS_FILE, dtype=str).fillna("")

    checks = []
    columns_present = all(
        column in messages.columns for column in REQUIRED_COLUMNS
    )

    add_check(
        checks,
        "required_columns",
        columns_present,
        f"Required columns: {REQUIRED_COLUMNS}",
    )

    if columns_present:
        message_ids = messages["message_id"].str.strip()
        add_check(
            checks,
            "message_ids_unique_and_nonblank",
            message_ids.ne("").all() and message_ids.is_unique,
            "Message IDs must be nonblank and unique.",
        )

        add_check(
            checks,
            "message_dataset_not_empty",
            not messages.empty,
            f"Found {len(messages)} messages.",
        )

        ticket_ids = set(tickets["ticket_id"].str.strip())
        referenced_tickets = set(messages["ticket_id"].str.strip())
        unknown_tickets = sorted(
            referenced_tickets - ticket_ids
        )
        blank_ticket_refs = int(
            messages["ticket_id"].str.strip().eq("").sum()
        )
        add_check(
            checks,
            "ticket_references_valid",
            not unknown_tickets and blank_ticket_refs == 0,
            f"Unknown ticket IDs: {unknown_tickets[:20]}; "
            f"blank references: {blank_ticket_refs}",
        )

        version_id_column = (
            "version_id"
            if "version_id" in versions.columns
            else "policy_version_id"
            if "policy_version_id" in versions.columns
            else None
        )

        if version_id_column:
            valid_version_ids = set(
                versions[version_id_column].str.strip()
            )
            policy_messages = messages[
                messages["message_type"].str.strip().eq("POLICY_RESPONSE")
            ]
            referenced_versions = set(
                policy_messages["policy_version_id"].str.strip()
            )
            referenced_versions.discard("")
            unknown_versions = sorted(
                referenced_versions - valid_version_ids
            )
            add_check(
                checks,
                "policy_response_version_references_valid",
                not unknown_versions,
                f"Unknown policy version IDs: {unknown_versions[:20]}",
            )
        else:
            add_check(
                checks,
                "policy_response_version_references_valid",
                False,
                "Policy versions dataset has no recognized version ID column.",
            )

        sender_values = set(messages["sender_type"].str.strip())
        invalid_senders = sorted(
            sender_values - ALLOWED_SENDER_TYPES
        )
        add_check(
            checks,
            "sender_types_valid",
            not invalid_senders,
            f"Unexpected sender types: {invalid_senders}",
        )

        message_type_values = set(messages["message_type"].str.strip())
        invalid_types = sorted(
            message_type_values - ALLOWED_MESSAGE_TYPES
        )
        add_check(
            checks,
            "message_types_valid",
            not invalid_types,
            f"Unexpected message types: {invalid_types}",
        )

        blank_content = int(
            messages["message_content"].str.strip().eq("").sum()
        )
        add_check(
            checks,
            "message_content_nonblank",
            blank_content == 0,
            f"Messages with blank content: {blank_content}",
        )

        timestamps = pd.to_datetime(
            messages["sent_timestamp"], errors="coerce"
        )
        add_check(
            checks,
            "sent_timestamps_valid",
            timestamps.notna().all(),
            f"Invalid timestamp row indexes: "
            f"{messages.index[timestamps.isna()].tolist()[:20]}",
        )

        blank_states = int(
            messages["lifecycle_state"].str.strip().eq("").sum()
        )
        add_check(
            checks,
            "lifecycle_states_nonblank",
            blank_states == 0,
            f"Messages with blank lifecycle states: {blank_states}",
        )

    failed = sum(check["status"] == "FAIL" for check in checks)

    report = {
        "validator": "message_validator",
        "dataset": str(MESSAGES_FILE.relative_to(PROJECT_ROOT)),
        "total_records": len(messages),
        "checks_total": len(checks),
        "checks_passed": len(checks) - failed,
        "checks_failed": failed,
        "errors": [],
        "checks": checks,
        "status": "PASS" if failed == 0 else "FAIL",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(f"Message validation: {report['status']}")
    print(f"Records: {len(messages)}")
    print(f"Checks passed: {report['checks_passed']}")
    print(f"Checks failed: {report['checks_failed']}")
    print(f"Report saved: {REPORT_FILE}")

    for check in checks:
        if check["status"] == "FAIL":
            print(f"[FAIL] {check['check']}: {check['details']}")

    return report


if __name__ == "__main__":
    result = validate_messages()
    sys.exit(0 if result["status"] == "PASS" else 1)
