
"""
HR Service System
SLA Validator

Validates SLA records against tickets, messages, and documented rules.
"""

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "validation"

TICKETS_FILE = DATA_DIR / "tickets.csv"
MESSAGES_FILE = DATA_DIR / "messages.csv"
SLA_FILE = DATA_DIR / "sla_records.csv"
REPORT_FILE = OUTPUT_DIR / "sla_validation_report.json"

EVALUATION_TIMESTAMP = pd.Timestamp("2026-10-28T00:00:00")

SLA_TARGETS = {
    "LOW": 72,
    "MEDIUM": 48,
    "HIGH": 24,
    "CRITICAL": 8,
}

EXPECTED_COLUMNS = [
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

VALID_RESPONSE_TYPES = {
    "HR",
    "HR_PARTNER",
    "IT",
    "OPERATIONS",
    "MANAGER",
}

RESOLUTION_TYPES = {
    "RESOLUTION_MESSAGE",
    "RESOLUTION",
    "RESOLVED",
    "CLOSURE",
    "CLOSED",
}


def load_data():
    """Load source files and validate required columns."""
    for path in (TICKETS_FILE, MESSAGES_FILE, SLA_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Required file not found: {path}")

    tickets = pd.read_csv(TICKETS_FILE, dtype=str).fillna("")
    messages = pd.read_csv(MESSAGES_FILE, dtype=str).fillna("")
    sla = pd.read_csv(SLA_FILE, dtype=str).fillna("")

    required_ticket_columns = {
        "ticket_id",
        "priority",
        "created_timestamp",
    }
    required_message_columns = {
        "ticket_id",
        "sender_type",
        "message_type",
        "sent_timestamp",
    }

    if not required_ticket_columns.issubset(tickets.columns):
        raise ValueError("tickets.csv is missing required columns.")

    if not required_message_columns.issubset(messages.columns):
        raise ValueError("messages.csv is missing required columns.")

    if not set(EXPECTED_COLUMNS).issubset(sla.columns):
        missing = sorted(set(EXPECTED_COLUMNS) - set(sla.columns))
        raise ValueError(f"sla_records.csv is missing columns: {missing}")

    return tickets, messages, sla


def get_expected_first_response(messages_for_ticket, created_timestamp):
    """Find the earliest qualifying response after ticket creation."""
    if messages_for_ticket.empty:
        return ""

    qualifying = messages_for_ticket[
        messages_for_ticket["sender_type"].str.upper().isin(
            VALID_RESPONSE_TYPES
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


def get_expected_resolution(messages_for_ticket, created_timestamp):
    """Find the latest explicit resolution event after creation."""
    if messages_for_ticket.empty:
        return ""

    candidates = messages_for_ticket[
        messages_for_ticket["message_type"].str.upper().isin(
            RESOLUTION_TYPES
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


def parse_timestamp(value):
    """Parse a timestamp, returning NaT for blank or invalid values."""
    if not str(value).strip():
        return pd.NaT
    return pd.to_datetime(value, errors="coerce")


def validate_data(tickets, messages, sla):
    """Run validation checks and return a report."""
    checks = []

    def record_check(name, passed, details=""):
        checks.append(
            {
                "check": name,
                "status": "PASS" if passed else "FAIL",
                "details": details,
            }
        )

    ticket_ids = set(tickets["ticket_id"])
    sla_ticket_ids = set(sla["ticket_id"])

    record_check(
        "SLA record count equals ticket count",
        len(sla) == len(tickets),
        f"SLA records={len(sla)}, tickets={len(tickets)}",
    )

    record_check(
        "SLA IDs are unique",
        sla["sla_id"].is_unique,
        f"Unique IDs={sla['sla_id'].nunique()}, records={len(sla)}",
    )

    record_check(
        "One SLA record per ticket",
        sla["ticket_id"].is_unique
        and sla_ticket_ids == ticket_ids,
        (
            f"Unique SLA ticket IDs={len(sla_ticket_ids)}, "
            f"source ticket IDs={len(ticket_ids)}"
        ),
    )

    record_check(
        "Ticket IDs are unique in source",
        tickets["ticket_id"].is_unique,
    )

    record_check(
        "SLA records reference existing tickets",
        sla_ticket_ids.issubset(ticket_ids),
    )

    ticket_lookup = tickets.set_index("ticket_id", drop=False)
    message_groups = {
        ticket_id: group.copy()
        for ticket_id, group in messages.groupby("ticket_id")
    }

    target_errors = []
    creation_errors = []
    response_errors = []
    resolution_errors = []
    elapsed_errors = []
    breach_errors = []
    reason_errors = []
    timestamp_errors = []

    for _, row in sla.iterrows():
        ticket_id = row["ticket_id"]

        if ticket_id not in ticket_lookup.index:
            continue

        ticket = ticket_lookup.loc[ticket_id]
        ticket_priority = ticket["priority"].strip().upper()
        row_priority = row["priority"].strip().upper()

        if row_priority != ticket_priority:
            target_errors.append(
                f"{ticket_id}: priority mismatch"
            )

        if ticket_priority not in SLA_TARGETS:
            target_errors.append(
                f"{ticket_id}: unsupported priority {ticket_priority}"
            )
            continue

        expected_target = SLA_TARGETS[ticket_priority]

        try:
            response_target = float(row["response_target_hours"])
            resolution_target = float(row["resolution_target_hours"])
            if (
                response_target != expected_target
                or resolution_target != expected_target
            ):
                target_errors.append(
                    f"{ticket_id}: target does not match priority rule"
                )
        except (TypeError, ValueError):
            target_errors.append(
                f"{ticket_id}: invalid SLA target value"
            )

        ticket_created = parse_timestamp(ticket["created_timestamp"])
        row_created = parse_timestamp(row["created_timestamp"])

        if pd.isna(ticket_created) or pd.isna(row_created):
            creation_errors.append(
                f"{ticket_id}: invalid creation timestamp"
            )
            continue

        if ticket_created != row_created:
            creation_errors.append(
                f"{ticket_id}: creation timestamp mismatch"
            )

        messages_for_ticket = message_groups.get(
            ticket_id, pd.DataFrame(columns=messages.columns)
        )

        expected_response = get_expected_first_response(
            messages_for_ticket, ticket_created
        )
        actual_response = row["first_response_timestamp"].strip()

        if actual_response != expected_response:
            response_errors.append(
                f"{ticket_id}: first response timestamp mismatch"
            )

        expected_resolution = get_expected_resolution(
            messages_for_ticket, ticket_created
        )
        actual_resolution = row["resolved_timestamp"].strip()

        if actual_resolution != expected_resolution:
            resolution_errors.append(
                f"{ticket_id}: resolution timestamp mismatch"
            )

        if actual_response:
            response_time = parse_timestamp(actual_response)
            if (
                pd.isna(response_time)
                or response_time < ticket_created
            ):
                timestamp_errors.append(
                    f"{ticket_id}: invalid first response timestamp"
                )

        if actual_resolution:
            resolution_time = parse_timestamp(actual_resolution)
            if (
                pd.isna(resolution_time)
                or resolution_time < ticket_created
            ):
                timestamp_errors.append(
                    f"{ticket_id}: invalid resolution timestamp"
                )
            end_timestamp = resolution_time
        else:
            end_timestamp = EVALUATION_TIMESTAMP

        if end_timestamp < ticket_created:
            timestamp_errors.append(
                f"{ticket_id}: evaluation precedes ticket creation"
            )
            continue

        expected_elapsed = round(
            (end_timestamp - ticket_created).total_seconds() / 3600,
            4,
        )

        try:
            actual_elapsed = float(row["elapsed_hours"])
            if abs(actual_elapsed - expected_elapsed) > 0.0001:
                elapsed_errors.append(
                    f"{ticket_id}: elapsed hours mismatch"
                )
        except (TypeError, ValueError):
            elapsed_errors.append(
                f"{ticket_id}: invalid elapsed hours"
            )
            continue

        expected_breach = expected_elapsed > expected_target
        actual_breach = row["sla_breached"].strip().lower()

        if actual_breach not in {"true", "false"}:
            breach_errors.append(
                f"{ticket_id}: invalid breach flag"
            )
        elif (actual_breach == "true") != expected_breach:
            breach_errors.append(
                f"{ticket_id}: breach flag does not match elapsed time"
            )

        reason = row["breach_reason"].strip()
        if expected_breach and not reason:
            reason_errors.append(
                f"{ticket_id}: breach reason is missing"
            )
        elif not expected_breach and reason:
            reason_errors.append(
                f"{ticket_id}: reason present despite no breach"
            )

        business_hours_value = row["business_hours_only"].strip().lower()
        if business_hours_value not in {"true", "false"}:
            timestamp_errors.append(
                f"{ticket_id}: invalid business_hours_only value"
            )

    record_check(
        "Priority and SLA targets match documented rules",
        not target_errors,
        "; ".join(target_errors[:10]),
    )
    record_check(
        "Creation timestamps match source tickets",
        not creation_errors,
        "; ".join(creation_errors[:10]),
    )
    record_check(
        "First response timestamps match messages",
        not response_errors,
        "; ".join(response_errors[:10]),
    )
    record_check(
        "Resolution timestamps match explicit resolution messages",
        not resolution_errors,
        "; ".join(resolution_errors[:10]),
    )
    record_check(
        "Timestamps are valid and chronological",
        not timestamp_errors,
        "; ".join(timestamp_errors[:10]),
    )
    record_check(
        "Elapsed hours match resolution or evaluation timestamp",
        not elapsed_errors,
        "; ".join(elapsed_errors[:10]),
    )
    record_check(
        "Breach flags match elapsed hours and resolution targets",
        not breach_errors,
        "; ".join(breach_errors[:10]),
    )
    record_check(
        "Breach reasons match breach outcomes",
        not reason_errors,
        "; ".join(reason_errors[:10]),
    )

    failures = [check for check in checks if check["status"] == "FAIL"]

    return {
        "status": "PASS" if not failures else "FAIL",
        "total_checks": len(checks),
        "passed_checks": len(checks) - len(failures),
        "failed_checks": len(failures),
        "ticket_count": len(tickets),
        "sla_record_count": len(sla),
        "breach_count": int(
            sla["sla_breached"].str.lower().eq("true").sum()
        ),
        "checks": checks,
    }


def main():
    tickets, messages, sla = load_data()
    report = validate_data(tickets, messages, sla)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(f"SLA validation status: {report['status']}")
    print(f"Checks passed: {report['passed_checks']}")
    print(f"Checks failed: {report['failed_checks']}")
    print(f"Tickets: {report['ticket_count']}")
    print(f"SLA records: {report['sla_record_count']}")
    print(f"SLA breaches: {report['breach_count']}")
    print(f"Report saved to: {REPORT_FILE}")

    for check in report["checks"]:
        print(f"[{check['status']}] {check['check']}")
        if check["details"]:
            print(f"    {check['details']}")

    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
