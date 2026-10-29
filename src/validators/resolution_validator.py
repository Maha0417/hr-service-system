
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_FILE = PROJECT_ROOT / "output" / "validation" / "resolution_validation_report.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REQUIRED_RESOLUTION_COLUMNS = [
    "resolution_id",
    "ticket_id",
    "policy_version_id",
    "resolution_type",
    "resolution_status",
    "resolved_by",
    "resolved_timestamp",
    "outcome",
    "resolution_notes",
    "policy_citation",
]


def check(name, condition, details=""):
    return {
        "check": name,
        "status": "PASS" if condition else "FAIL",
        "details": details,
    }


def is_true(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def validate_resolutions():

    resolution_path = DATA_DIR / "resolutions.csv"
    tickets_path = DATA_DIR / "tickets.csv"
    versions_path = DATA_DIR / "policy_versions.csv"
    messages_path = DATA_DIR / "messages.csv"

    for path in (
        resolution_path,
        tickets_path,
        versions_path,
        messages_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Required source file missing: {path}")

    resolutions = pd.read_csv(resolution_path)
    tickets = pd.read_csv(tickets_path)
    versions = pd.read_csv(versions_path)
    messages = pd.read_csv(messages_path)

    checks = []

    missing_columns = set(REQUIRED_RESOLUTION_COLUMNS) - set(resolutions.columns)
    checks.append(check(
        "Required columns present",
        not missing_columns,
        f"Missing columns: {sorted(missing_columns)}",
    ))

    if missing_columns:
        return write_report(checks, len(resolutions))

    checks.append(check(
        "One resolution record per ticket",
        len(resolutions) == len(tickets)
        and set(resolutions["ticket_id"]) == set(tickets["ticket_id"])
        and not resolutions["ticket_id"].duplicated().any(),
        f"Found {len(resolutions)} resolutions for {len(tickets)} tickets",
    ))

    checks.append(check(
        "Unique resolution IDs",
        resolutions["resolution_id"].notna().all()
        and not resolutions["resolution_id"].duplicated().any(),
        "Resolution IDs must be populated and unique",
    ))

    checks.append(check(
        "No duplicate ticket resolution records",
        not resolutions["ticket_id"].duplicated().any(),
        "Each ticket may have at most one resolution record",
    ))

    ticket_ids = set(tickets["ticket_id"].dropna())
    resolution_ticket_ids = set(resolutions["ticket_id"].dropna())

    checks.append(check(
        "Valid ticket foreign keys",
        resolutions["ticket_id"].notna().all()
        and resolution_ticket_ids.issubset(ticket_ids),
        f"Unknown ticket IDs: {sorted(resolution_ticket_ids - ticket_ids)}",
    ))

    checks.append(check(
        "One record per source ticket",
        len(resolutions) == len(tickets)
        and resolution_ticket_ids == ticket_ids,
        f"Source tickets: {len(tickets)}; resolution tickets: "
        f"{len(resolution_ticket_ids)}",
    ))

    version_ids = set(versions["version_id"].dropna())
    referenced_versions = set(resolutions["policy_version_id"].dropna())

    resolved_mask = resolutions["resolution_status"].eq("RESOLVED")
    pending_mask = resolutions["resolution_status"].eq("PENDING")

    checks.append(check(
        "Valid policy-version foreign keys",
        referenced_versions.issubset(version_ids),
        f"Unknown version IDs: {sorted(referenced_versions - version_ids)}",
    ))

    current_versions = versions[
        versions["is_current"].map(is_true)
    ]
    current_version_ids = set(current_versions["version_id"].dropna())

    checks.append(check(
        "Resolved records use current policy versions",
        resolutions.loc[resolved_mask, "policy_version_id"].notna().all()
        and set(
            resolutions.loc[resolved_mask, "policy_version_id"].dropna()
        ).issubset(current_version_ids),
        "Every resolved record must reference a current policy version",
    ))

    checks.append(check(
        "Pending records have no applied policy version",
        resolutions.loc[pending_mask, "policy_version_id"].isna().all(),
        "Pending records must not claim a policy version was applied",
    ))

    checks.append(check(
        "Pending records have no resolution timestamp",
        resolutions.loc[pending_mask, "resolved_timestamp"].isna().all(),
        "Pending records must have a null resolution timestamp",
    ))

    checks.append(check(
        "Resolved records have timestamps",
        resolutions.loc[resolved_mask, "resolved_timestamp"].notna().all(),
        "Resolved records require a timestamp",
    ))

    valid_timestamps = True
    invalid_timestamps = []

    for _, row in resolutions.loc[resolved_mask].iterrows():
        value = row["resolved_timestamp"]
        try:
            if pd.isna(value):
                raise ValueError("Missing timestamp")
            datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            valid_timestamps = False
            invalid_timestamps.append(row["resolution_id"])

    checks.append(check(
        "Valid resolution timestamps",
        valid_timestamps,
        f"Invalid timestamps in resolution IDs: {invalid_timestamps}",
    ))

    required_text_fields = [
        "resolution_id",
        "ticket_id",
        "resolution_type",
        "resolution_status",
        "outcome",
        "resolution_notes",
        "policy_citation",
    ]

    populated = True
    for column in required_text_fields:
        values = resolutions[column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any():
            populated = False
            break

    checks.append(check(
        "Required resolution fields populated",
        populated,
        f"Checked fields: {required_text_fields}",
    ))

    checks.append(check(
        "Allowed resolution statuses",
        resolutions["resolution_status"].isin(
            {"RESOLVED", "PENDING"}
        ).all(),
        "Allowed statuses: RESOLVED, PENDING",
    ))

    # Confirm resolved records correspond to actual resolution messages.
    actual_resolution_tickets = set(
        messages.loc[
            messages["message_type"].eq("RESOLUTION_MESSAGE"), "ticket_id"
        ].dropna()
    )
    recorded_resolved_tickets = set(
        resolutions.loc[resolved_mask, "ticket_id"].dropna()
    )

    checks.append(check(
        "Resolved status matches message history",
        recorded_resolved_tickets == actual_resolution_tickets,
        f"Resolved records: {len(recorded_resolved_tickets)}; "
        f"source resolution messages: {len(actual_resolution_tickets)}",
    ))

    return write_report(checks, len(resolutions))


def write_report(checks, record_count):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    failures = sum(item["status"] == "FAIL" for item in checks)
    report = {
        "validation_status": "PASS" if failures == 0 else "FAIL",
        "total_records": record_count,
        "checks_passed": len(checks) - failures,
        "checks_failed": failures,
        "checks": checks,
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    logger.info("Validation status: %s", report["validation_status"])
    logger.info("Checks passed: %d", report["checks_passed"])
    logger.info("Checks failed: %d", report["checks_failed"])
    logger.info("Report saved to %s", OUTPUT_FILE)

    return report


if __name__ == "__main__":
    validate_resolutions()
