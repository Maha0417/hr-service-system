
"""
HR Service System
Assignment History Validator

Validates assignment records against tickets, categories, and workflow rules.
Does not modify source CSV files.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from scale_config import SCENARIO_COUNTS

from scale_config import SCENARIO_COUNTS

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.workflow_rules import ROUTING_RULES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "validation"

TICKETS_FILE = DATA_DIR / "tickets.csv"
CATEGORIES_FILE = DATA_DIR / "categories.csv"
ASSIGNMENTS_FILE = DATA_DIR / "assignments.csv"
REPORT_FILE = OUTPUT_DIR / "assignment_validation_report.json"

REQUIRED_ASSIGNMENT_COLUMNS = {
    "assignment_id",
    "ticket_id",
    "assigned_group",
    "assigned_to",
    "assignment_reason",
    "assigned_timestamp",
    "assignment_status",
    "previous_assignment_id",
}

REQUIRED_TICKET_COLUMNS = {
    "ticket_id",
    "category_id",
    "created_timestamp",
    "sensitive_flag",
}

REQUIRED_CATEGORY_COLUMNS = {"category_id", "category_name"}

ALLOWED_STATUSES = {"ACTIVE", "COMPLETED"}


def validate_assignments():
    """Run assignment validation checks and return a structured report."""
    errors = []
    warnings = []
    checks = []

    def record_check(name, passed, details=""):
        checks.append(
            {
                "check": name,
                "passed": bool(passed),
                "details": details,
            }
        )
        if not passed:
            errors.append(f"{name}: {details}")

    for path in (TICKETS_FILE, CATEGORIES_FILE, ASSIGNMENTS_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Required file not found: {path}")

    tickets = pd.read_csv(TICKETS_FILE, dtype=str).fillna("")
    categories = pd.read_csv(CATEGORIES_FILE, dtype=str).fillna("")
    assignments = pd.read_csv(ASSIGNMENTS_FILE, dtype=str).fillna("")

    record_check(
        "Required assignment columns",
        REQUIRED_ASSIGNMENT_COLUMNS.issubset(assignments.columns),
        f"Missing: {sorted(REQUIRED_ASSIGNMENT_COLUMNS - set(assignments.columns))}",
    )
    record_check(
        "Required ticket columns",
        REQUIRED_TICKET_COLUMNS.issubset(tickets.columns),
        f"Missing: {sorted(REQUIRED_TICKET_COLUMNS - set(tickets.columns))}",
    )
    record_check(
        "Required category columns",
        REQUIRED_CATEGORY_COLUMNS.issubset(categories.columns),
        f"Missing: {sorted(REQUIRED_CATEGORY_COLUMNS - set(categories.columns))}",
    )

    # Stop dependent checks if required columns are missing.
    if (
        not REQUIRED_ASSIGNMENT_COLUMNS.issubset(assignments.columns)
        or not REQUIRED_TICKET_COLUMNS.issubset(tickets.columns)
        or not REQUIRED_CATEGORY_COLUMNS.issubset(categories.columns)
    ):
        return save_report(assignments, checks, errors, warnings)

    record_check(
        "Assignment IDs are unique",
        not assignments["assignment_id"].duplicated().any(),
        f"Records: {len(assignments)}; unique IDs: "
        f"{assignments['assignment_id'].nunique()}",
    )

    record_check(
        "Ticket IDs are unique",
        not tickets["ticket_id"].duplicated().any(),
        f"Unique ticket IDs: {tickets['ticket_id'].nunique()}",
    )

    valid_ticket_ids = set(tickets["ticket_id"])
    orphan_assignments = assignments[
        ~assignments["ticket_id"].isin(valid_ticket_ids)
    ]

    record_check(
        "Assignment ticket foreign keys",
        orphan_assignments.empty,
        f"Orphan assignment rows: {len(orphan_assignments)}",
    )

    category_lookup = categories.set_index("category_id")["category_name"].to_dict()
    ticket_lookup = tickets.set_index("ticket_id").to_dict("index")

    unknown_categories = []
    incorrect_routes = []
    invalid_statuses = []
    invalid_timestamps = []
    timestamps_before_creation = []
    broken_previous_links = []
    cross_ticket_previous_links = []
    non_chronological_history = []
    duplicate_ticket_timestamps = []

    assignment_ids = set(assignments["assignment_id"])
    assignment_by_id = assignments.set_index("assignment_id", drop=False)

    for _, row in assignments.iterrows():
        assignment_id = row["assignment_id"]
        ticket_id = row["ticket_id"]
        assigned_group = row["assigned_group"]
        status = row["assignment_status"]

        if status not in ALLOWED_STATUSES:
            invalid_statuses.append(assignment_id)

        if ticket_id not in ticket_lookup:
            continue

        ticket = ticket_lookup[ticket_id]
        category_name = category_lookup.get(ticket["category_id"])

        if category_name is None:
            unknown_categories.append(ticket_id)
        else:
            expected_group = ROUTING_RULES.get(category_name)

            # Initial routing must match the configured routing rule.
            if (
                row["assignment_reason"] == "INITIAL_ROUTING"
                and assigned_group != expected_group
            ):
                incorrect_routes.append(
                    {
                        "assignment_id": assignment_id,
                        "ticket_id": ticket_id,
                        "expected": expected_group,
                        "actual": assigned_group,
                    }
                )

            # Employee Relations is always assigned to HR_PARTNER.
            if category_name == "Employee Relations" and assigned_group != "HR_PARTNER":
                incorrect_routes.append(
                    {
                        "assignment_id": assignment_id,
                        "ticket_id": ticket_id,
                        "expected": "HR_PARTNER",
                        "actual": assigned_group,
                    }
                )

        try:
            assigned_timestamp = pd.to_datetime(
                row["assigned_timestamp"], errors="raise"
            )
            created_timestamp = pd.to_datetime(
                ticket["created_timestamp"], errors="raise"
            )

            if assigned_timestamp < created_timestamp:
                timestamps_before_creation.append(assignment_id)
        except (ValueError, TypeError, KeyError):
            invalid_timestamps.append(assignment_id)

        previous_id = row["previous_assignment_id"]

        if previous_id:
            if previous_id not in assignment_ids:
                broken_previous_links.append(
                    {"assignment_id": assignment_id, "previous_id": previous_id}
                )
            else:
                previous_row = assignment_by_id.loc[previous_id]

                if isinstance(previous_row, pd.DataFrame):
                    previous_row = previous_row.iloc[0]

                if previous_row["ticket_id"] != ticket_id:
                    cross_ticket_previous_links.append(assignment_id)

    record_check(
        "Category references are valid",
        not unknown_categories,
        f"Unknown category references: {len(set(unknown_categories))}",
    )
    record_check(
        "Routing rules are respected",
        not incorrect_routes,
        f"Incorrect routing records: {len(incorrect_routes)}",
    )
    record_check(
        "Assignment statuses are valid",
        not invalid_statuses,
        f"Invalid status records: {len(invalid_statuses)}",
    )
    record_check(
        "Assignment timestamps are valid",
        not invalid_timestamps,
        f"Invalid timestamps: {len(invalid_timestamps)}",
    )
    record_check(
        "Assignments do not precede ticket creation",
        not timestamps_before_creation,
        f"Timestamp violations: {len(timestamps_before_creation)}",
    )
    record_check(
        "Previous assignment references exist",
        not broken_previous_links,
        f"Missing previous links: {len(broken_previous_links)}",
    )
    record_check(
        "Previous assignments belong to the same ticket",
        not cross_ticket_previous_links,
        f"Cross-ticket links: {len(cross_ticket_previous_links)}",
    )

    # Validate chronological order and unique timestamps per ticket.
    for ticket_id, group in assignments.groupby("ticket_id"):
        parsed = pd.to_datetime(group["assigned_timestamp"], errors="coerce")

        if parsed.isna().any():
            continue

        ordered = parsed.sort_values()

        if not parsed.reset_index(drop=True).equals(ordered.reset_index(drop=True)):
            non_chronological_history.append(ticket_id)

        if parsed.duplicated().any():
            duplicate_ticket_timestamps.append(ticket_id)

    record_check(
        "Assignment history is chronological",
        not non_chronological_history,
        f"Tickets with non-chronological rows: {len(set(non_chronological_history))}",
    )
    record_check(
        "Timestamps are unique per ticket",
        not duplicate_ticket_timestamps,
        f"Tickets with duplicate timestamps: {len(set(duplicate_ticket_timestamps))}",
    )

    # Every ticket should have exactly one initial assignment.
    initial_counts = assignments[
        assignments["assignment_reason"] == "INITIAL_ROUTING"
    ].groupby("ticket_id").size()

    tickets_without_one_initial = [
        ticket_id
        for ticket_id in tickets["ticket_id"]
        if initial_counts.get(ticket_id, 0) != 1
    ]

    record_check(
        "Exactly one initial assignment per ticket",
        not tickets_without_one_initial,
        f"Tickets failing initial-assignment count: {len(tickets_without_one_initial)}",
    )

    # Each reassignment should point to the immediately preceding event.
    broken_chains = []

    for ticket_id, group in assignments.groupby("ticket_id"):
        group = group.copy()
        group["_timestamp"] = pd.to_datetime(
            group["assigned_timestamp"], errors="coerce"
        )
        group = group.sort_values(
            ["_timestamp", "assignment_id"]
        ).reset_index(drop=True)

        for index in range(1, len(group)):
            expected_previous = group.iloc[index - 1]["assignment_id"]
            actual_previous = group.iloc[index]["previous_assignment_id"]

            if actual_previous != expected_previous:
                broken_chains.append(
                    {
                        "ticket_id": ticket_id,
                        "assignment_id": group.iloc[index]["assignment_id"],
                        "expected_previous": expected_previous,
                        "actual_previous": actual_previous,
                    }
                )

    record_check(
        "Reassignment chain continuity",
        not broken_chains,
        f"Broken chain links: {len(broken_chains)}",
    )

    escalation_records = assignments[
        assignments["assignment_reason"] == "ESCALATION"
    ]

    record_check(
        "Outdated-policy Leave escalations",
        len(escalation_records) == SCENARIO_COUNTS["OUTDATED_POLICY"]
        and (
            escalation_records["assigned_group"] == "SENIOR_LEAVE_TEAM"
        ).all(),
        f"Escalation records: {len(escalation_records)}",
    )

    report = build_report(assignments, checks, errors, warnings)
    return report


def build_report(assignments, checks, errors, warnings):
    return {
        "status": "PASS" if not errors else "FAIL",
        "total_assignments": int(len(assignments)),
        "unique_assignment_ids": int(assignments["assignment_id"].nunique()),
        "tickets_covered": int(assignments["ticket_id"].nunique()),
        "checks_passed": sum(1 for check in checks if check["passed"]),
        "checks_failed": sum(1 for check in checks if not check["passed"]),
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def save_report(assignments, checks, errors, warnings):
    """Write a JSON validation report and return it."""
    report = build_report(assignments, checks, errors, warnings)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Assignment validation: {report['status']}")
    print(f"Total assignments: {report['total_assignments']}")
    print(f"Checks passed: {report['checks_passed']}")
    print(f"Checks failed: {report['checks_failed']}")
    print(f"Report saved to: {REPORT_FILE}")

    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"- {error}")

    return report


def main():
    """Run assignment validation and save its report."""
    report = validate_assignments()
    save_report(
        pd.read_csv(ASSIGNMENTS_FILE, dtype=str).fillna(""),
        report["checks"],
        report["errors"],
        report["warnings"],
    )


if __name__ == "__main__":
    main()
