
from pathlib import Path

import pandas as pd

from scale_config import ANOMALIES_PER_TYPE


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "csv"
OUTPUT_PATH = DATA_DIR / "anomalies.csv"

REQUIRED_FILES = {
    "tickets": DATA_DIR / "tickets.csv",
    "ground_truth": DATA_DIR / "ground_truth.csv",
    "policy_versions": DATA_DIR / "policy_versions.csv",
    "categories": DATA_DIR / "categories.csv",
    "sla_records": DATA_DIR / "sla_records.csv",
}

OUTPUT_COLUMNS = [
    "anomaly_id",
    "entity_type",
    "entity_id",
    "issue_type",
    "expected_outcome",
    "actual_outcome",
    "severity",
    "ground_truth_id",
]

ANOMALY_TYPES = [
    "obsolete_policy_reference",
    "sensitive_case_routed_general_queue",
    "sla_business_hours_error",
    "unsupported_claim",
]


def load_sources():
    """Load and validate the baseline source datasets."""
    for name, path in REQUIRED_FILES.items():
        if not path.exists():
            raise FileNotFoundError(f"Required source file is missing: {path}")

    sources = {
        name: pd.read_csv(path, dtype=str, keep_default_na=False)
        for name, path in REQUIRED_FILES.items()
    }

    required_columns = {
        "tickets": {"ticket_id", "policy_id", "category_id", "priority",
                    "sensitive_flag", "current_assignment_group"},
        "ground_truth": {"ground_truth_id", "entity_type", "entity_id",
                         "expected_route", "expected_policy_version",
                         "expected_sla_status", "severity"},
        "policy_versions": {"version_id", "policy_id", "version_number",
                            "is_current", "status", "expiration_date"},
        "categories": {"category_id", "category_name", "default_queue"},
        "sla_records": {"ticket_id", "business_hours_only"},
    }

    for name, columns in required_columns.items():
        missing = columns - set(sources[name].columns)
        if missing:
            raise ValueError(
                f"{name} is missing required columns: {sorted(missing)}"
            )

    for name, key in [
        ("tickets", "ticket_id"),
        ("ground_truth", "ground_truth_id"),
        ("policy_versions", "version_id"),
        ("categories", "category_id"),
        ("sla_records", "ticket_id"),
    ]:
        if sources[name][key].duplicated().any():
            raise ValueError(f"{name} contains duplicate {key} values.")

    return sources


def build_anomalies(sources):
    tickets = sources["tickets"]
    ground_truth = sources["ground_truth"]
    versions = sources["policy_versions"]
    categories = sources["categories"]
    sla_records = sources["sla_records"]

    gt_by_ticket = ground_truth.set_index("entity_id").to_dict("index")
    ticket_by_id = tickets.set_index("ticket_id").to_dict("index")
    version_by_id = versions.set_index("version_id").to_dict("index")
    category_by_id = categories.set_index("category_id").to_dict("index")
    sla_by_ticket = sla_records.set_index("ticket_id").to_dict("index")

    anomalies = []

    def add_anomaly(ticket_id, issue_type, expected, actual, severity=None):
        if ticket_id not in ticket_by_id:
            raise ValueError(f"Unknown ticket reference: {ticket_id}")
        if ticket_id not in gt_by_ticket:
            raise ValueError(f"No Ground Truth record for {ticket_id}")
        if expected.strip() == actual.strip():
            raise ValueError(
                f"Expected and actual outcomes must differ for {ticket_id}"
            )

        gt = gt_by_ticket[ticket_id]
        anomalies.append({
            "anomaly_id": f"ANOM-{len(anomalies) + 1:03d}",
            "entity_type": "TICKET",
            "entity_id": ticket_id,
            "issue_type": issue_type,
            "expected_outcome": expected,
            "actual_outcome": actual,
            "severity": severity or gt["severity"],
            "ground_truth_id": gt["ground_truth_id"],
        })

    # 1. Obsolete policy reference: five tickets whose policy has
    # both a current version and a verified expired version.
    obsolete_candidates = []
    for ticket in tickets.to_dict("records"):
        ticket_id = ticket["ticket_id"]
        gt = gt_by_ticket.get(ticket_id)
        if not gt:
            continue

        expected_version_id = gt["expected_policy_version"]
        current_version = version_by_id.get(expected_version_id)
        if not current_version:
            continue
        if current_version["policy_id"] != ticket["policy_id"]:
            continue
        if current_version["status"].upper() != "CURRENT":
            continue
        if current_version["is_current"].strip().lower() not in {
            "true", "1", "yes", "y"
        }:
            continue

        expired = versions[
            (versions["policy_id"] == ticket["policy_id"])
            & (versions["status"].str.upper() == "EXPIRED")
            & (versions["is_current"].str.lower().isin(["false", "0", "no", "n"]))
        ]
        if not expired.empty:
            expired = expired.sort_values("version_number")
            obsolete_candidates.append(
                (ticket_id, expected_version_id, expired.iloc[0]["version_id"])
            )

    if len(obsolete_candidates) < ANOMALIES_PER_TYPE:
        raise ValueError(
            f"Need at least {ANOMALIES_PER_TYPE} tickets with both current and expired policy versions."
        )

    for ticket_id, expected_version, expired_version in obsolete_candidates[:ANOMALIES_PER_TYPE]:
        add_anomaly(
            ticket_id,
            "obsolete_policy_reference",
            f"Reference current policy version {expected_version}.",
            f"Incorrectly reference expired policy version {expired_version}.",
            "HIGH",
        )

    # 2. Sensitive tickets that Ground Truth routes to HR_PARTNER.
    sensitive_candidates = []
    for ticket in tickets.to_dict("records"):
        ticket_id = ticket["ticket_id"]
        gt = gt_by_ticket.get(ticket_id)
        if not gt or ticket["sensitive_flag"].strip().upper() not in {"Y", "TRUE", "1"}:
            continue

        category = category_by_id.get(ticket["category_id"], {})
        if gt["expected_route"] != "HR_PARTNER":
            continue
        if category.get("category_name") != "Employee Relations":
            continue

        sensitive_candidates.append((ticket_id, gt["expected_route"]))

    if len(sensitive_candidates) < ANOMALIES_PER_TYPE:
        raise ValueError(
            f"Need {ANOMALIES_PER_TYPE} sensitive Employee Relations tickets expected to route to HR_PARTNER; "
            f"found {len(sensitive_candidates)}."
        )

    for ticket_id, expected_route in sensitive_candidates[:ANOMALIES_PER_TYPE]:
        add_anomaly(
            ticket_id,
            "sensitive_case_routed_general_queue",
            f"Route the sensitive case to {expected_route}.",
            "Incorrectly route the sensitive case to BENEFITS_TEAM, a general queue.",
            "CRITICAL",
        )

    # 3. SLA business-hours error. Preserve baseline SLA records.
    sla_candidates = [
        ticket_id for ticket_id in ticket_by_id
        if ticket_id in sla_by_ticket
        and sla_by_ticket[ticket_id]["business_hours_only"].strip().lower()
        in {"false", "0", "no", "n"}
    ]
    if len(sla_candidates) < ANOMALIES_PER_TYPE:
        raise ValueError(f"Need {ANOMALIES_PER_TYPE} tickets whose SLA rules count elapsed hours.")

    for ticket_id in sla_candidates[:ANOMALIES_PER_TYPE]:
        add_anomaly(
            ticket_id,
            "sla_business_hours_error",
            "Count all elapsed hours, including non-business hours, under the configured SLA rule.",
            "Incorrectly exclude non-business hours even though business_hours_only is False.",
            "HIGH",
        )

    # 4. Unsupported policy claims. Do not invent policy contents:
    # explicitly mark the claim as unsupported and uncited.
    for ticket in tickets.to_dict("records"):
        ticket_id = ticket["ticket_id"]
        gt = gt_by_ticket.get(ticket_id)
        if not gt:
            continue

        expected_version = gt["expected_policy_version"]
        if expected_version not in version_by_id:
            continue

        add_anomaly(
            ticket_id,
            "unsupported_claim",
            f"Only state entitlements supported by current policy version {expected_version}, with evidence.",
            "Assert an additional employee benefit as fact without a supporting policy citation.",
            "HIGH",
        )

        if sum(a["issue_type"] == "unsupported_claim" for a in anomalies) == ANOMALIES_PER_TYPE:
            break

    if len(anomalies) != ANOMALIES_PER_TYPE * len(ANOMALY_TYPES):
        raise ValueError(f"Expected {ANOMALIES_PER_TYPE * len(ANOMALY_TYPES)} anomalies; generated {len(anomalies)}.")

    result = pd.DataFrame(anomalies, columns=OUTPUT_COLUMNS)

    counts = result["issue_type"].value_counts().to_dict()
    expected_counts = {issue_type: ANOMALIES_PER_TYPE for issue_type in ANOMALY_TYPES}
    if counts != expected_counts:
        raise ValueError(
            f"Incorrect anomaly distribution. Expected {expected_counts}, got {counts}"
        )

    return result


def main():
    if OUTPUT_PATH.exists():
        raise FileExistsError(
            f"{OUTPUT_PATH} already exists. Inspect it before regenerating; "
            "the existing dataset will not be overwritten."
        )

    sources = load_sources()
    anomalies = build_anomalies(sources)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    anomalies.to_csv(OUTPUT_PATH, index=False)

    print(f"Anomaly generation successful: {OUTPUT_PATH}")
    print(f"Total anomalies: {len(anomalies)}")
    print("\nAnomalies by type:")
    print(anomalies["issue_type"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
