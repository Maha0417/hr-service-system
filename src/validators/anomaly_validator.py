
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from scale_config import ANOMALIES_PER_TYPE


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "csv"
OUTPUT_PATH = ROOT / "output" / "validation" / "anomaly_validation_report.json"

ANOMALY_TYPES = {
    "obsolete_policy_reference",
    "sensitive_case_routed_general_queue",
    "sla_business_hours_error",
    "unsupported_claim",
}

REQUIRED_COLUMNS = [
    "anomaly_id",
    "entity_type",
    "entity_id",
    "issue_type",
    "expected_outcome",
    "actual_outcome",
    "severity",
    "ground_truth_id",
]


def load_csv(name):
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Required dataset is missing: {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main():
    anomalies = load_csv("anomalies.csv")
    tickets = load_csv("tickets.csv")
    ground_truth = load_csv("ground_truth.csv")
    policy_versions = load_csv("policy_versions.csv")
    categories = load_csv("categories.csv")
    sla_records = load_csv("sla_records.csv")

    checks = []

    def record_check(name, passed, details):
        checks.append({
            "check": name,
            "status": "PASS" if passed else "FAIL",
            "details": details,
        })

    # 1. Required columns
    missing = sorted(set(REQUIRED_COLUMNS) - set(anomalies.columns))
    record_check(
        "required_columns",
        not missing,
        f"Missing columns: {missing}" if missing else "All required columns exist.",
    )

    # Stop if the schema cannot support safe validation.
    if missing:
        raise ValueError(f"Anomaly dataset is missing columns: {missing}")

    # 2. Expected record count for the selected dataset scale
    expected_total = ANOMALIES_PER_TYPE * len(ANOMALY_TYPES)
    record_check(
        "expected_record_count",
        len(anomalies) == expected_total,
        f"Found {len(anomalies)} records; expected {expected_total}.",
    )

    # 3. All four required types are present
    actual_types = set(anomalies["issue_type"])
    record_check(
        "all_anomaly_types_present",
        actual_types == ANOMALY_TYPES,
        f"Found types: {sorted(actual_types)}",
    )

    # 4. Expected number of records for every anomaly type
    counts = Counter(anomalies["issue_type"])
    correct_counts = all(
        counts.get(kind, 0) == ANOMALIES_PER_TYPE
        for kind in ANOMALY_TYPES
    )
    record_check(
        "expected_count_per_type",
        correct_counts and set(counts) == ANOMALY_TYPES,
        f"Expected {ANOMALIES_PER_TYPE} per type; counts: {dict(counts)}",
    )

    # 5. Unique, nonblank anomaly IDs
    ids_valid = (
        anomalies["anomaly_id"].str.strip().ne("").all()
        and anomalies["anomaly_id"].is_unique
    )
    record_check(
        "anomaly_ids_unique_and_nonblank",
        ids_valid,
        "Anomaly IDs are unique and nonblank."
        if ids_valid else "Duplicate or blank anomaly IDs found.",
    )

    ticket_ids = set(tickets["ticket_id"])
    gt_by_id = ground_truth.set_index("ground_truth_id").to_dict("index")
    gt_by_ticket = ground_truth.set_index("entity_id").to_dict("index")
    ticket_by_id = tickets.set_index("ticket_id").to_dict("index")
    version_by_id = policy_versions.set_index("version_id").to_dict("index")
    category_by_id = categories.set_index("category_id").to_dict("index")
    sla_by_ticket = sla_records.set_index("ticket_id").to_dict("index")

    # 6. Entity references exist
    entity_refs_valid = (
        anomalies["entity_type"].eq("TICKET").all()
        and anomalies["entity_id"].isin(ticket_ids).all()
    )
    record_check(
        "valid_entity_references",
        entity_refs_valid,
        "All anomalies reference existing tickets."
        if entity_refs_valid else "Invalid entity type or ticket reference found.",
    )

    # 7. Ground Truth references exist and match the entity
    gt_links_valid = True
    for row in anomalies.to_dict("records"):
        gt = gt_by_id.get(row["ground_truth_id"])
        if not gt or gt["entity_id"] != row["entity_id"]:
            gt_links_valid = False
            break

    record_check(
        "ground_truth_links_valid",
        gt_links_valid,
        "Every Ground Truth ID exists and matches its ticket."
        if gt_links_valid else "Missing or mismatched Ground Truth link found.",
    )

    # 8. Expected and actual outcomes differ
    outcomes_differ = all(
        row["expected_outcome"].strip()
        and row["actual_outcome"].strip()
        and row["expected_outcome"].strip()
        != row["actual_outcome"].strip()
        for row in anomalies.to_dict("records")
    )
    record_check(
        "expected_actual_outcomes_differ",
        outcomes_differ,
        "Every anomaly has distinct, nonblank expected and actual outcomes."
        if outcomes_differ else "An empty or identical expected/actual outcome exists.",
    )

    obsolete_rows = anomalies[
        anomalies["issue_type"] == "obsolete_policy_reference"
    ]
    obsolete_valid = len(obsolete_rows) == ANOMALIES_PER_TYPE
    for row in obsolete_rows.to_dict("records"):
        match = re.search(r"\bVER-[A-Z0-9-]+\b", row["actual_outcome"])
        gt = gt_by_id.get(row["ground_truth_id"])
        ticket = ticket_by_id.get(row["entity_id"])

        if not match or not gt or not ticket:
            obsolete_valid = False
            break

        actual_version = version_by_id.get(match.group(0))
        expected_version = version_by_id.get(gt["expected_policy_version"])

        if not actual_version or not expected_version:
            obsolete_valid = False
            break

        if (
            actual_version["status"].upper() != "EXPIRED"
            or actual_version["is_current"].lower() not in {"false", "0", "no", "n"}
            or actual_version["policy_id"] != ticket["policy_id"]
            or expected_version["policy_id"] != ticket["policy_id"]
            or expected_version["status"].upper() != "CURRENT"
            or expected_version["is_current"].lower() not in {"true", "1", "yes", "y"}
            or actual_version["policy_id"] != expected_version["policy_id"]
        ):
            obsolete_valid = False
            break

    # 9. Obsolete policy versions exist and are expired
    record_check(
        "obsolete_versions_exist_and_are_expired",
        obsolete_valid,
        "All five anomalies reference expired versions of the same policy "
        "whose expected version is current."
        if obsolete_valid else "An obsolete-policy reference is invalid.",
    )

    sensitive_rows = anomalies[
        anomalies["issue_type"] == "sensitive_case_routed_general_queue"
    ]
    sensitive_valid = len(sensitive_rows) == ANOMALIES_PER_TYPE

    for row in sensitive_rows.to_dict("records"):
        ticket = ticket_by_id.get(row["entity_id"])
        gt = gt_by_id.get(row["ground_truth_id"])
        if not ticket or not gt:
            sensitive_valid = False
            break

        category = category_by_id.get(ticket["category_id"], {})
        if (
            ticket["sensitive_flag"].strip().upper() not in {"Y", "TRUE", "1"}
            or gt["expected_route"] != "HR_PARTNER"
            or category.get("category_name") != "Employee Relations"
            or "BENEFITS_TEAM" not in row["actual_outcome"]
        ):
            sensitive_valid = False
            break

    # 10. Sensitive routing anomalies target sensitive HR Partner cases
    record_check(
        "sensitive_routing_anomalies_valid",
        sensitive_valid,
        "All five anomalies concern sensitive Employee Relations tickets "
        "expected to route to HR_PARTNER but incorrectly routed to BENEFITS_TEAM."
        if sensitive_valid else "A sensitive-case routing anomaly failed validation.",
    )

    sla_rows = anomalies[
        anomalies["issue_type"] == "sla_business_hours_error"
    ]
    sla_valid = len(sla_rows) == ANOMALIES_PER_TYPE

    for row in sla_rows.to_dict("records"):
        sla = sla_by_ticket.get(row["entity_id"])
        expected_text = row["expected_outcome"].lower()
        actual_text = row["actual_outcome"].lower()

        if (
            not sla
            or sla["business_hours_only"].strip().lower()
            not in {"false", "0", "no", "n"}
            or "all elapsed hours" not in expected_text
            or "exclude non-business hours" not in actual_text
            or "business_hours_only is false" not in actual_text
        ):
            sla_valid = False
            break

    # 11. SLA anomalies describe a documented calculation-rule violation
    record_check(
        "sla_business_hours_rule_violation_documented",
        sla_valid,
        "All five anomalies describe incorrectly excluding non-business hours "
        "where the source rule counts all elapsed hours."
        if sla_valid else "An SLA anomaly does not match the documented source rule.",
    )

    unsupported_rows = anomalies[
        anomalies["issue_type"] == "unsupported_claim"
    ]
    unsupported_valid = len(unsupported_rows) == ANOMALIES_PER_TYPE

    for row in unsupported_rows.to_dict("records"):
        gt = gt_by_id.get(row["ground_truth_id"])
        expected_version = (
            version_by_id.get(gt["expected_policy_version"]) if gt else None
        )
        actual_text = row["actual_outcome"].lower()
        expected_text = row["expected_outcome"].lower()

        if (
            not expected_version
            or expected_version["status"].upper() != "CURRENT"
            or "without a supporting policy citation" not in actual_text
            or "with evidence" not in expected_text
        ):
            unsupported_valid = False
            break

    # 12. Unsupported claims explicitly lack supporting citations
    record_check(
        "unsupported_claims_marked",
        unsupported_valid,
        "All five claims are explicitly marked as lacking a supporting policy citation."
        if unsupported_valid else "An unsupported claim is missing its evidence warning.",
    )

    # 13. Severity is nonblank
    severity_valid = anomalies["severity"].str.strip().ne("").all()
    record_check(
        "severity_values_nonblank",
        severity_valid,
        "Every anomaly has a severity."
        if severity_valid else "One or more anomalies have blank severity.",
    )

    # 14. Anomalies are linked to ticket Ground Truth records
    gt_entity_types_valid = all(
        gt_by_id.get(row["ground_truth_id"], {}).get("entity_type") == "TICKET"
        for row in anomalies.to_dict("records")
    )
    record_check(
        "ground_truth_entity_types_valid",
        gt_entity_types_valid,
        "All linked Ground Truth records describe tickets."
        if gt_entity_types_valid else "A linked Ground Truth record has the wrong entity type.",
    )

    # 15. Every anomaly's expected route/policy fields are grounded
    grounding_valid = True
    for row in anomalies.to_dict("records"):
        gt = gt_by_id.get(row["ground_truth_id"])
        if not gt:
            grounding_valid = False
            break

        if row["issue_type"] == "obsolete_policy_reference":
            if gt["expected_policy_version"] not in row["expected_outcome"]:
                grounding_valid = False
                break
        elif row["issue_type"] == "sensitive_case_routed_general_queue":
            if gt["expected_route"] not in row["expected_outcome"]:
                grounding_valid = False
                break
        elif row["issue_type"] == "unsupported_claim":
            if gt["expected_policy_version"] not in row["expected_outcome"]:
                grounding_valid = False
                break
        elif row["issue_type"] == "sla_business_hours_error":
            if row["entity_id"] not in sla_by_ticket:
                grounding_valid = False
                break

    record_check(
        "expected_outcomes_grounded_in_sources",
        grounding_valid,
        "Expected outcomes are linked to Ground Truth or the applicable SLA rule."
        if grounding_valid else "An expected outcome could not be grounded in its source.",
    )

    passed = sum(check["status"] == "PASS" for check in checks)
    failed = len(checks) - passed

    report = {
        "validator": "anomaly_validator",
        "dataset": "data/csv/anomalies.csv",
        "total_anomalies": len(anomalies),
        "anomaly_type_counts": dict(sorted(Counter(anomalies["issue_type"]).items())),
        "checks_total": len(checks),
        "checks_passed": passed,
        "checks_failed": failed,
        "overall_status": "PASS" if failed == 0 else "FAIL",
        "checks": checks,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Anomaly validation: {report['overall_status']}")
    print(f"Total anomalies: {len(anomalies)}")
    print(f"Checks passed: {passed}/{len(checks)}")
    print(f"Checks failed: {failed}")
    for check in checks:
        print(f"[{check['status']}] {check['check']}: {check['details']}")
    print(f"\nReport saved to: {OUTPUT_PATH}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
