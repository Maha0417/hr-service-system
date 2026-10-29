
"""
HR Service System
Ground Truth Validator

Validates the baseline ground-truth dataset against source records
and documented workflow and SLA rules.
Writes a JSON validation report.
"""

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflow_rules import ROUTING_RULES, CLARIFICATION_SCENARIOS
from src.sla_generator import SLA_TARGETS, EVALUATION_TIMESTAMP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "csv"

GROUND_TRUTH_FILE = DATA_DIR / "ground_truth.csv"
TICKETS_FILE = DATA_DIR / "tickets.csv"
CATEGORIES_FILE = DATA_DIR / "categories.csv"
VERSIONS_FILE = DATA_DIR / "policy_versions.csv"
RESOLUTIONS_FILE = DATA_DIR / "resolutions.csv"
MESSAGES_FILE = DATA_DIR / "messages.csv"

REPORT_FILE = (
    PROJECT_ROOT
    / "output"
    / "validation"
    / "ground_truth_validation_report.json"
)

REQUIRED_COLUMNS = [
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

VALID_SLA_STATUSES = {"BREACHED", "WITHIN_SLA"}
VALID_RESOLUTION_STATUSES = {"PENDING", "RESOLVED"}

RESOLUTION_MESSAGE_TYPES = {
    "RESOLUTION_MESSAGE",
    "RESOLUTION",
    "RESOLVED",
    "CLOSURE",
    "CLOSED",
}


def load_csv(path):
    """Load a CSV file while preserving empty values as strings."""
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )

    return pd.read_csv(
        path,
        dtype=str,
    ).fillna("")


def parse_boolean(value):
    """Parse supported boolean representations."""
    normalized = str(value).strip().lower()

    if normalized in {"true", "1", "yes", "y"}:
        return True

    if normalized in {"false", "0", "no", "n"}:
        return False

    raise ValueError(
        f"Invalid boolean value: {value!r}"
    )


def add_check(checks, name, passed, details):
    """Record the outcome of one validation check."""
    checks.append(
        {
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        }
    )


def calculate_sla_status(ticket, resolution, resolution_message):
    """Calculate SLA status independently from the SLA output CSV."""
    ticket_id = ticket["ticket_id"]
    priority = ticket["priority"].strip().upper()

    if priority not in SLA_TARGETS:
        raise ValueError(
            f"Unsupported priority {priority!r} for {ticket_id}."
        )

    created = pd.to_datetime(
        ticket["created_timestamp"],
        errors="raise",
    )

    if created > EVALUATION_TIMESTAMP:
        raise ValueError(
            f"Ticket {ticket_id} was created after the "
            "SLA evaluation timestamp."
        )

    status = resolution["resolution_status"].strip().upper()
    resolution_timestamp = resolution["resolved_timestamp"].strip()

    if status == "RESOLVED":
        if not resolution_timestamp:
            raise ValueError(
                f"Resolved ticket {ticket_id} has no timestamp."
            )

        if resolution_message is None:
            raise ValueError(
                f"Resolved ticket {ticket_id} has no resolution message."
            )

        end = pd.to_datetime(
            resolution_timestamp,
            errors="raise",
        )

        if end != resolution_message:
            raise ValueError(
                f"Resolution timestamp mismatch for {ticket_id}."
            )

    elif status == "PENDING":
        if resolution_timestamp:
            raise ValueError(
                f"Pending ticket {ticket_id} has a resolution timestamp."
            )

        if resolution_message is not None:
            raise ValueError(
                f"Pending ticket {ticket_id} has a resolution message."
            )

        end = EVALUATION_TIMESTAMP

    else:
        raise ValueError(
            f"Invalid resolution status {status!r} for {ticket_id}."
        )

    elapsed_hours = (end - created).total_seconds() / 3600

    if elapsed_hours < 0:
        raise ValueError(
            f"Negative elapsed time for {ticket_id}."
        )

    target_hours = SLA_TARGETS[priority]

    if elapsed_hours > target_hours:
        return "BREACHED"

    return "WITHIN_SLA"


def build_report(checks, record_count):
    """Build a JSON-serializable validation report."""
    failed = sum(
        check["status"] == "FAIL"
        for check in checks
    )

    return {
        "dataset": "ground_truth.csv",
        "records_checked": record_count,
        "total_checks": len(checks),
        "passed_checks": len(checks) - failed,
        "failed_checks": failed,
        "overall_status": "PASS" if failed == 0 else "FAIL",
        "checks": checks,
    }


def run_validation():
    """Validate ground-truth records against all relevant source data."""
    ground_truth = load_csv(GROUND_TRUTH_FILE)
    tickets = load_csv(TICKETS_FILE)
    categories = load_csv(CATEGORIES_FILE)
    versions = load_csv(VERSIONS_FILE)
    resolutions = load_csv(RESOLUTIONS_FILE)
    messages = load_csv(MESSAGES_FILE)

    checks = []

    missing_columns = sorted(
        set(REQUIRED_COLUMNS) - set(ground_truth.columns)
    )

    add_check(
        checks,
        "required_columns",
        not missing_columns,
        f"Missing columns: {missing_columns}",
    )

    if missing_columns:
        return build_report(checks, len(ground_truth))

    add_check(
        checks,
        "one_record_per_ticket",
        len(ground_truth) == len(tickets)
        and set(ground_truth["entity_id"]) == set(tickets["ticket_id"])
        and not ground_truth["entity_id"].duplicated().any(),
        f"Ground-truth records: {len(ground_truth)}; tickets: {len(tickets)}. "
        "Expected exactly one record per ticket.",
    )

    unique_gt_ids = (
        not ground_truth["ground_truth_id"].duplicated().any()
        and ground_truth["ground_truth_id"].str.strip().ne("").all()
    )

    add_check(
        checks,
        "ground_truth_ids_unique",
        unique_gt_ids,
        "Ground-truth IDs must be nonblank and unique.",
    )

    unique_entity_ids = (
        not ground_truth["entity_id"].duplicated().any()
        and ground_truth["entity_id"].str.strip().ne("").all()
    )

    add_check(
        checks,
        "ticket_ids_unique",
        unique_entity_ids,
        "Each ticket must have one ground-truth record.",
    )

    source_ticket_ids = set(tickets["ticket_id"])
    ground_truth_ticket_ids = set(ground_truth["entity_id"])

    add_check(
        checks,
        "valid_ticket_references",
        ground_truth_ticket_ids == source_ticket_ids,
        (
            f"Unknown IDs: "
            f"{sorted(ground_truth_ticket_ids - source_ticket_ids)}; "
            f"missing IDs: "
            f"{sorted(source_ticket_ids - ground_truth_ticket_ids)}"
        ),
    )

    add_check(
        checks,
        "entity_type_is_ticket",
        ground_truth["entity_type"].eq("TICKET").all(),
        "All baseline entity types must be TICKET.",
    )

    ticket_map = tickets.set_index("ticket_id").to_dict("index")

    category_map = dict(
        zip(
            categories["category_id"],
            categories["category_name"],
        )
    )

    current_versions = versions[
        versions["is_current"].str.strip().str.lower().isin(
            {"true", "1", "yes", "y"}
        )
        & versions["status"].str.strip().str.upper().eq("CURRENT")
    ]

    duplicate_current_policies = current_versions[
        current_versions["policy_id"].duplicated(keep=False)
    ]["policy_id"].unique().tolist()

    current_policy_map = dict(
        zip(
            current_versions["policy_id"],
            current_versions["version_id"],
        )
    )

    version_map = versions.set_index("version_id").to_dict("index")
    resolution_map = resolutions.set_index("ticket_id").to_dict("index")

    resolution_messages = messages[
        messages["message_type"].str.strip().str.upper().isin(
            RESOLUTION_MESSAGE_TYPES
        )
    ].copy()

    resolution_messages["_parsed_timestamp"] = pd.to_datetime(
        resolution_messages["sent_timestamp"],
        errors="coerce",
    )

    message_map = {}
    duplicate_resolution_messages = []

    for ticket_id, group in resolution_messages.groupby("ticket_id"):
        if len(group) != 1:
            duplicate_resolution_messages.append(ticket_id)
            message_map[ticket_id] = None
        elif pd.isna(group.iloc[0]["_parsed_timestamp"]):
            message_map[ticket_id] = None
        else:
            message_map[ticket_id] = group.iloc[0]["_parsed_timestamp"]

    route_errors = []
    category_errors = []
    policy_errors = []
    resolution_errors = []
    sla_errors = []
    clarification_errors = []
    issue_errors = []
    severity_errors = []

    for _, record in ground_truth.iterrows():
        ticket_id = record["entity_id"]

        if ticket_id not in ticket_map:
            continue

        ticket = dict(ticket_map[ticket_id])

        # Fix: set ticket_id explicitly because the indexed dictionary
        # contains the ticket fields but not its index value.
        ticket["ticket_id"] = ticket_id

        category_name = category_map.get(
            ticket["category_id"],
            "",
        )

        policy_id = ticket["policy_id"]
        expected_route = ROUTING_RULES.get(category_name, "")

        if (
            not expected_route
            or record["expected_route"] != expected_route
        ):
            route_errors.append(ticket_id)

        if record["expected_category"] != category_name:
            category_errors.append(ticket_id)

        expected_version = current_policy_map.get(policy_id, "")
        actual_version = record["expected_policy_version"]

        if (
            not expected_version
            or actual_version != expected_version
            or actual_version not in version_map
        ):
            policy_errors.append(ticket_id)
        else:
            version = version_map[actual_version]

            if (
                version["policy_id"] != policy_id
                or version["status"].strip().upper() != "CURRENT"
                or version["is_current"].strip().lower()
                not in {"true", "1", "yes", "y"}
            ):
                policy_errors.append(ticket_id)

        expected_clarification = (
            ticket["scenario_type"].strip().upper()
            in CLARIFICATION_SCENARIOS
        )

        try:
            source_clarification = parse_boolean(
                ticket["requires_clarification"]
            )

            record_clarification = parse_boolean(
                record["expected_clarification"]
            )

            if (
                expected_clarification != source_clarification
                or record_clarification != expected_clarification
            ):
                clarification_errors.append(ticket_id)

        except ValueError:
            clarification_errors.append(ticket_id)

        resolution = resolution_map.get(ticket_id)

        if resolution is None:
            resolution_errors.append(ticket_id)
            sla_errors.append(ticket_id)

        else:
            source_status = (
                resolution["resolution_status"].strip().upper()
            )

            record_status = (
                record["expected_resolution_status"].strip().upper()
            )

            if (
                source_status not in VALID_RESOLUTION_STATUSES
                or record_status not in VALID_RESOLUTION_STATUSES
                or record_status != source_status
            ):
                resolution_errors.append(ticket_id)

            stored_sla_status = (
                record["expected_sla_status"].strip().upper()
            )

            if stored_sla_status not in VALID_SLA_STATUSES:
                sla_errors.append(ticket_id)

            else:
                try:
                    calculated_sla_status = calculate_sla_status(
                        ticket,
                        resolution,
                        message_map.get(ticket_id),
                    )

                    if stored_sla_status != calculated_sla_status:
                        sla_errors.append(ticket_id)

                except (ValueError, TypeError, KeyError):
                    sla_errors.append(ticket_id)

        if record["issue_type"] != ticket["scenario_type"]:
            issue_errors.append(ticket_id)

        if (
            record["severity"].strip().upper()
            != ticket["priority"].strip().upper()
        ):
            severity_errors.append(ticket_id)

    add_check(
        checks,
        "routes_match_workflow_rules",
        not route_errors,
        f"Mismatched ticket IDs: {route_errors}",
    )

    add_check(
        checks,
        "categories_match_source",
        not category_errors,
        f"Mismatched ticket IDs: {category_errors}",
    )

    add_check(
        checks,
        "expected_policy_versions_exist_and_are_current",
        not policy_errors and not duplicate_current_policies,
        (
            f"Mismatched ticket IDs: {sorted(set(policy_errors))}; "
            f"policies with multiple current versions: "
            f"{duplicate_current_policies}"
        ),
    )

    add_check(
        checks,
        "valid_resolution_statuses",
        not resolution_errors,
        f"Mismatched ticket IDs: {sorted(set(resolution_errors))}",
    )

    add_check(
        checks,
        "expected_sla_status_matches_business_rules",
        not sla_errors and not duplicate_resolution_messages,
        (
            f"Mismatched ticket IDs: {sorted(set(sla_errors))}; "
            f"tickets with multiple resolution messages: "
            f"{sorted(duplicate_resolution_messages)}"
        ),
    )

    add_check(
        checks,
        "clarification_matches_workflow_rules",
        not clarification_errors,
        f"Mismatched ticket IDs: {sorted(set(clarification_errors))}",
    )

    add_check(
        checks,
        "issue_type_matches_source",
        not issue_errors,
        f"Mismatched ticket IDs: {issue_errors}",
    )

    add_check(
        checks,
        "severity_matches_source_priority",
        not severity_errors,
        f"Mismatched ticket IDs: {severity_errors}",
    )

    return build_report(checks, len(ground_truth))


def main():
    """Run validation and save the JSON report."""
    try:
        report = run_validation()

    except Exception as exc:
        report = build_report(
            [
                {
                    "check": "validator_execution",
                    "status": "FAIL",
                    "details": f"{type(exc).__name__}: {exc}",
                }
            ],
            0,
        )

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_FILE.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    print(f"Overall status: {report['overall_status']}")
    print(f"Records checked: {report['records_checked']}")
    print(f"Checks passed: {report['passed_checks']}")
    print(f"Checks failed: {report['failed_checks']}")
    print(f"Report saved to: {REPORT_FILE}")

    for check in report["checks"]:
        print(
            f"[{check['status']}] {check['check']}: "
            f"{check['details']}"
        )

    if report["overall_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
