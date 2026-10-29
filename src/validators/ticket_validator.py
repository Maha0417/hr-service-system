
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "csv"
REPORT_FILE = PROJECT_ROOT / "output" / "validation" / "ticket_validation_report.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

TICKET_ID_PATTERN = re.compile(r"TKT-2026-[0-9]{6}")
ALLOWED_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_STATUSES = {
    "OPEN",
    "IN_PROGRESS",
    "WAITING_FOR_INFO",
    "RESOLVED",
    "CLOSED",
}


def load_csv(filename):
    """Load a required CSV file and report useful errors."""
    path = DATA_DIR / filename

    if not path.is_file():
        raise FileNotFoundError(f"Required file not found: {path}")

    frame = pd.read_csv(path, dtype=str)

    if frame.empty:
        raise ValueError(f"Required file contains no records: {path}")

    return frame


def validate_tickets():
    """Validate the saved ticket dataset independently of its generator."""
    logger.info("Loading saved datasets for validation...")

    tickets = load_csv("tickets.csv")
    employees = load_csv("employees.csv")
    categories = load_csv("categories.csv")
    policies = load_csv("policy_documents.csv")

    required_ticket_columns = {
        "ticket_id",
        "employee_id",
        "category_id",
        "policy_id",
        "priority",
        "ticket_status",
        "sensitive_flag",
        "requires_clarification",
        "scenario_type",
    }

    missing_columns = required_ticket_columns - set(tickets.columns)
    if missing_columns:
        raise ValueError(
            f"tickets.csv is missing columns: {sorted(missing_columns)}"
        )

    for frame, key, name in (
        (employees, "employee_id", "employees.csv"),
        (categories, "category_id", "categories.csv"),
        (policies, "policy_id", "policy_documents.csv"),
    ):
        if key not in frame.columns:
            raise ValueError(f"{name} is missing required column {key!r}")

    ticket_ids = tickets["ticket_id"]
    duplicate_id_count = int(ticket_ids.duplicated().sum())
    invalid_id_count = int(
        (~ticket_ids.fillna("").map(
            lambda value: bool(TICKET_ID_PATTERN.fullmatch(value))
        )).sum()
    )

    employee_ids = set(employees["employee_id"].dropna())
    category_ids = set(categories["category_id"].dropna())
    policy_ids = set(policies["policy_id"].dropna())

    invalid_employee_fk = int(
        (~tickets["employee_id"].isin(employee_ids)).sum()
    )
    invalid_category_fk = int(
        (~tickets["category_id"].isin(category_ids)).sum()
    )
    invalid_policy_fk = int(
        (~tickets["policy_id"].isin(policy_ids)).sum()
    )

    invalid_priority_count = int(
        (~tickets["priority"].isin(ALLOWED_PRIORITIES)).sum()
    )
    invalid_status_count = int(
        (~tickets["ticket_status"].isin(ALLOWED_STATUSES)).sum()
    )

        # Validate sensitive-case rules.
    category_lookup = categories.set_index("category_id")

    employee_relations_ids = set(
        categories.loc[
            categories["category_name"].eq("Employee Relations"),
            "category_id",
        ]
    )

    sensitive_rule_errors = int(
        (
            tickets["category_id"].isin(employee_relations_ids)
            & tickets["sensitive_flag"].ne("Y")
        ).sum()
    )

    # Validate category-policy consistency.
    category_lookup_by_id = categories.set_index("category_id")["category_name"]

    policy_category_lookup = policies.set_index("policy_id")["policy_category"]

    expected_ticket_categories = tickets["category_id"].map(
        category_lookup_by_id
    )

    expected_policy_categories = tickets["policy_id"].map(
        policy_category_lookup
    )

    policy_category_errors = int(
        expected_ticket_categories.ne(expected_policy_categories).sum()
    )
    # Validate clarification requirements for applicable scenarios.
    clarification_scenarios = {"AMBIGUOUS", "MISSING_CONTEXT"}

    clarification_values = (
        tickets["requires_clarification"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    clarification_required = clarification_values.isin(
        {"Y", "TRUE", "1"}
    )

    clarification_rule_errors = int(
        (
            tickets["scenario_type"].isin(clarification_scenarios)
            & ~clarification_required
        ).sum()
    )

    checks = {
        "duplicate_ticket_ids": duplicate_id_count,
        "invalid_ticket_id_formats": invalid_id_count,
        "invalid_employee_foreign_keys": invalid_employee_fk,
        "invalid_category_foreign_keys": invalid_category_fk,
        "invalid_policy_foreign_keys": invalid_policy_fk,
        "invalid_priorities": invalid_priority_count,
        "invalid_statuses": invalid_status_count,
        "policy_category_errors": policy_category_errors,
        "sensitive_rule_errors": sensitive_rule_errors,
        "clarification_rule_errors": clarification_rule_errors,
    }

    passed = all(count == 0 for count in checks.values())

    report = {
        "validation_status": "PASS" if passed else "FAIL",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ticket_count": int(len(tickets)),
        "checks": checks,
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8",
    )

    logger.info("Validation status: %s", report["validation_status"])
    logger.info("Tickets checked: %s", report["ticket_count"])
    logger.info("Report saved to: %s", REPORT_FILE)

    if not passed:
        logger.error("One or more ticket data checks failed.")

    return report


if __name__ == "__main__":
    try:
        validate_tickets()
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as exc:
        logger.error("Ticket validation failed: %s", exc)
        raise
