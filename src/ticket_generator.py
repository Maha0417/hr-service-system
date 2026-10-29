
import logging
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from scale_config import (
    SEED,
    TICKET_COUNT,
    SCENARIO_COUNTS,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_FILE = DATA_DIR / "tickets.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
TICKET_STATUSES = {
    "OPEN", "IN_PROGRESS", "WAITING_FOR_INFO",
    "RESOLVED", "CLOSED",
}
TICKET_ID_PATTERN = re.compile(r"TKT-2026-[0-9]{6}")

PRIORITY_BY_CATEGORY = {
    "Benefits": "LOW",
    "Leave": "MEDIUM",
    "Payroll": "MEDIUM",
    "Onboarding": "LOW",
    "Employee Relations": "HIGH",
}

NORMAL_TEMPLATES = {
    "Benefits": (
        "Benefits Enrollment Question",
        "How do I enroll in company health insurance?",
    ),
    "Leave": (
        "Leave Eligibility Question",
        "Can I carry forward unused annual leave?",
    ),
    "Payroll": (
        "Payroll Inquiry",
        "My salary amount looks incorrect this month.",
    ),
    "Onboarding": (
        "New Hire Question",
        "What documents are required for onboarding?",
    ),
    "Employee Relations": (
        "Employee Relations Concern",
        "I need help with a workplace concern.",
    ),
}

SPECIAL_SCENARIOS = {
    "AMBIGUOUS": (
        "Ambiguous: Leave Request",
        "Can I take leave?",
        True,
    ),
    "MISSING_CONTEXT": (
        "Missing Context: Benefits Request",
        "When does my benefit start?",
        True,
    ),
    "CONFIDENTIAL": (
        "Confidential Employee Relations Concern",
        "I need to report workplace harassment. Please handle "
        "this concern confidentially.",
        True,
    ),
    "OUTDATED_POLICY": (
        "Outdated Policy Reference: Leave",
        "I found a 2024 leave policy document stating I can "
        "carry forward 20 days. Is that still applicable?",
        False,
    ),
}


def load_source_data():
    """Load source CSVs and validate master/reference data."""
    logger.info("Loading source data...")

    required_files = {
        "employees": DATA_DIR / "employees.csv",
        "categories": DATA_DIR / "categories.csv",
        "policies": DATA_DIR / "policy_documents.csv",
        "departments": DATA_DIR / "departments.csv",
    }

    for name, path in required_files.items():
        if not path.is_file():
            raise FileNotFoundError(
                f"Required {name} file not found: {path}"
            )

    employees = pd.read_csv(
        required_files["employees"], dtype=str
    )
    categories = pd.read_csv(
        required_files["categories"], dtype=str
    )
    policies = pd.read_csv(
        required_files["policies"], dtype=str
    )
    departments = pd.read_csv(
        required_files["departments"], dtype=str
    )

    required_columns = {
        "employees": {"employee_id", "department_id"},
        "categories": {
            "category_id", "category_name", "sensitive_flag",
            "default_queue", "active_flag",
        },
        "policies": {"policy_id", "policy_category"},
        "departments": {"department_id"},
    }

    frames = {
        "employees": employees,
        "categories": categories,
        "policies": policies,
        "departments": departments,
    }

    for name, frame in frames.items():
        missing = required_columns[name] - set(frame.columns)
        if missing:
            raise ValueError(
                f"{name} is missing columns: {sorted(missing)}"
            )
        if frame.empty:
            raise ValueError(f"{name} contains no records.")

    for name, frame, key in (
        ("employees", employees, "employee_id"),
        ("categories", categories, "category_id"),
        ("policies", policies, "policy_id"),
        ("departments", departments, "department_id"),
    ):
        if frame[key].isna().any() or frame[key].str.strip().eq("").any():
            raise ValueError(f"{name}.{key} contains blank values.")
        if frame[key].duplicated().any():
            raise ValueError(f"{name}.{key} contains duplicate IDs.")

    if not employees["department_id"].isin(
        departments["department_id"]
    ).all():
        raise ValueError("An employee references an unknown department.")

    if not categories["sensitive_flag"].isin({"Y", "N"}).all():
        raise ValueError("Category sensitive_flag must be Y or N.")

    if not categories["active_flag"].eq("Y").all():
        raise ValueError("Inactive categories cannot receive new tickets.")

    if (
        categories["default_queue"].isna().any()
        or categories["default_queue"].str.strip().eq("").any()
    ):
        raise ValueError("Category default_queue contains blank values.")

    category_names = set(categories["category_name"])
    policy_categories = set(policies["policy_category"])

    if not category_names.issubset(set(NORMAL_TEMPLATES)):
        raise ValueError("A category has no normal ticket template.")

    if not category_names.issubset(policy_categories):
        raise ValueError("A category has no matching policy.")

    if "Employee Relations" not in category_names:
        raise ValueError("Employee Relations category is required.")

    if "Leave" not in category_names:
        raise ValueError("Leave category is required for the policy scenario.")

    return employees, categories, policies


def validate_tickets(tickets, employees, categories, policies):
    """Validate ticket structure, references, scenarios, and rules."""
    logger.info("Validating generated tickets...")

    if len(tickets) != TICKET_COUNT:
        raise ValueError(f"Expected exactly {TICKET_COUNT} tickets.")

    if tickets["ticket_id"].duplicated().any():
        raise ValueError("Duplicate ticket IDs found.")

    if not tickets["ticket_id"].map(
        lambda value: bool(TICKET_ID_PATTERN.fullmatch(value))
    ).all():
        raise ValueError("Ticket ID format is invalid.")

    for column, source, source_key in (
        ("employee_id", employees, "employee_id"),
        ("category_id", categories, "category_id"),
        ("policy_id", policies, "policy_id"),
    ):
        if not tickets[column].isin(source[source_key]).all():
            raise ValueError(f"Invalid foreign-key reference: {column}")

    if not tickets["priority"].isin(PRIORITIES).all():
        raise ValueError("Invalid ticket priority.")

    if not tickets["ticket_status"].isin(TICKET_STATUSES).all():
        raise ValueError("Invalid ticket status.")

    if not tickets["lifecycle_state"].isin({"ACTIVE", "CLOSED"}).all():
        raise ValueError("Invalid lifecycle state.")

    if not tickets["sensitive_flag"].isin({"Y", "N"}).all():
        raise ValueError("Invalid sensitive flag.")

    if not tickets["requires_clarification"].isin({True, False}).all():
        raise ValueError("Invalid requires_clarification value.")

    category_lookup = categories.set_index("category_id")
    policy_lookup = policies.set_index("policy_id")

    special_prefixes = {
        "AMBIGUOUS": "Ambiguous:",
        "MISSING_CONTEXT": "Missing Context:",
        "CONFIDENTIAL": "Confidential Employee Relations",
        "OUTDATED_POLICY": "Outdated Policy Reference:",
    }

    for ticket in tickets.to_dict("records"):
        category = category_lookup.loc[ticket["category_id"]]
        policy = policy_lookup.loc[ticket["policy_id"]]
        category_name = category["category_name"]

        if ticket["sensitive_flag"] != category["sensitive_flag"]:
            raise ValueError("Sensitive flag does not match category.")

        if ticket["current_assignment_group"] != category["default_queue"]:
            raise ValueError("Assignment group does not match category queue.")

        if ticket["priority"] != PRIORITY_BY_CATEGORY[category_name]:
            raise ValueError("Priority does not match category rules.")

        if policy["policy_category"] != category_name:
            raise ValueError("Policy category does not match ticket category.")

        if category_name == "Employee Relations":
            if ticket["sensitive_flag"] != "Y":
                raise ValueError("Employee Relations must be sensitive.")
            if ticket["current_assignment_group"] != "HR_PARTNER":
                raise ValueError("Employee Relations must route to HR_PARTNER.")

        subject = ticket["ticket_subject"]
        clarification = ticket["requires_clarification"]

        if subject.startswith(special_prefixes["AMBIGUOUS"]):
            if not clarification:
                raise ValueError("Ambiguous requests require clarification.")

        elif subject.startswith(special_prefixes["MISSING_CONTEXT"]):
            if not clarification:
                raise ValueError("Missing-context requests require clarification.")

        elif subject.startswith(special_prefixes["CONFIDENTIAL"]):
            if not clarification or category_name != "Employee Relations":
                raise ValueError(
                    "Confidential scenarios require clarification "
                    "and Employee Relations classification."
                )

        elif subject.startswith(special_prefixes["OUTDATED_POLICY"]):
            if clarification:
                raise ValueError(
                    "Outdated-policy references must not automatically "
                    "require clarification."
                )

    expected_counts = {
        scenario: SCENARIO_COUNTS[scenario]
        for scenario in (
            "AMBIGUOUS",
            "MISSING_CONTEXT",
            "CONFIDENTIAL",
            "OUTDATED_POLICY",
        )
    }

    for scenario, prefix in special_prefixes.items():
        actual = tickets["ticket_subject"].str.startswith(prefix).sum()
        if actual != expected_counts[scenario]:
            raise ValueError(
                f"{scenario}: expected {expected_counts[scenario]}, "
                f"found {actual}."
            )

    clarification_count = int(
        tickets["requires_clarification"].sum()
    )

    expected_clarifications = (
        SCENARIO_COUNTS["AMBIGUOUS"]
        + SCENARIO_COUNTS["MISSING_CONTEXT"]
        + SCENARIO_COUNTS["CONFIDENTIAL"]
    )
    if clarification_count != expected_clarifications:
        raise ValueError(
            f"Expected {expected_clarifications} clarification tickets, "
            f"found {clarification_count}."
        )


def generate_tickets():
    """Generate a reproducible 50-ticket validation dataset."""
    rng = random.Random(SEED)
    employees, categories, policies = load_source_data()

    categories_by_name = {
        row["category_name"]: row
        for _, row in categories.iterrows()
    }

    policies_by_category = {
        name: group["policy_id"].tolist()
        for name, group in policies.groupby("policy_category")
    }

    employee_records = employees.to_dict("records")

    scenario_plan = [
        scenario
        for scenario, count in SCENARIO_COUNTS.items()
        for _ in range(count)
    ]

    rng.shuffle(scenario_plan)
    tickets = []

    for i, scenario in enumerate(scenario_plan, start=1):
        if scenario == "CONFIDENTIAL":
            category_name = "Employee Relations"
            subject, description, clarification = (
                SPECIAL_SCENARIOS["CONFIDENTIAL"]
            )

        elif scenario == "OUTDATED_POLICY":
            category_name = "Leave"
            subject, description, clarification = (
                SPECIAL_SCENARIOS["OUTDATED_POLICY"]
            )

        elif scenario in {"AMBIGUOUS", "MISSING_CONTEXT"}:
            eligible_categories = [
                name for name in categories_by_name
                if name != "Employee Relations"
            ]
            category_name = rng.choice(eligible_categories)
            subject, description, clarification = SPECIAL_SCENARIOS[scenario]

        else:
            category_name = rng.choice(list(categories_by_name))
            subject, description = NORMAL_TEMPLATES[category_name]
            clarification = False

        category = categories_by_name[category_name]
        matching_policies = policies_by_category.get(category_name, [])

        if not matching_policies:
            raise ValueError(
                f"No policy found for category {category_name!r}."
            )

        employee = rng.choice(employee_records)
        policy_id = rng.choice(matching_policies)

        created_at = datetime(2026, 1, 1) + timedelta(hours=i)

        tickets.append({
            "ticket_id": f"TKT-2026-{i:06d}",
            "scenario_type": scenario,
            "employee_id": employee["employee_id"],
            "category_id": category["category_id"],
            "policy_id": policy_id,
            "ticket_subject": subject,
            "ticket_description": description,
            "priority": PRIORITY_BY_CATEGORY[category_name],
            "ticket_status": "OPEN",
            "sensitive_flag": category["sensitive_flag"],
            "requires_clarification": clarification,
            "created_timestamp": created_at.isoformat(),
            "current_assignment_group": category["default_queue"],
            "lifecycle_state": "ACTIVE",
        })

    tickets_df = pd.DataFrame(tickets)

    validate_tickets(tickets_df, employees, categories, policies)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tickets_df.to_csv(OUTPUT_FILE, index=False)

    clarification_count = int(tickets_df["requires_clarification"].sum())

    logger.info(
        "Scenario distribution: 30 normal, 5 ambiguous, "
        "5 missing-context, 5 confidential, 5 outdated-policy."
    )
    logger.info(
        "Clarification required: %s/%s (%.0f%%)",
        clarification_count,
        len(tickets_df),
        clarification_count / len(tickets_df) * 100,
    )
    logger.info(
        "Generated and validated %s tickets: %s",
        len(tickets_df),
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    try:
        generate_tickets()
    except (OSError, ValueError, KeyError, IndexError) as exc:
        logger.error("Ticket generation failed: %s", exc)
        raise
