
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "csv"
VALIDATION_DIR = PROJECT_ROOT / "output" / "validation"
OUTPUT_DIR = PROJECT_ROOT / "output" / "metrics"
OUTPUT_FILE = OUTPUT_DIR / "project_metrics.json"
MASTER_REPORT_FILE = (
    VALIDATION_DIR / "master_validation_report.json"
)

DATASETS = {
    "department_count": "departments.csv",
    "employee_count": "employees.csv",
    "policy_document_count": "policy_documents.csv",
    "policy_version_count": "policy_versions.csv",
    "knowledge_article_count": "knowledge_articles.csv",
    "ticket_count": "tickets.csv",
    "message_count": "messages.csv",
    "assignment_count": "assignments.csv",
    "sla_record_count": "sla_records.csv",
    "resolution_count": "resolutions.csv",
    "ticket_event_count": "ticket_events.csv",
    "anomaly_count": "anomalies.csv",
}


def load_csv(filename):
    path = DATA_DIR / filename

    if not path.is_file():
        raise FileNotFoundError(
            f"Required dataset not found: {path}"
        )

    return pd.read_csv(path)


def calculate_rate(numerator, denominator):
    """Return a percentage rounded to two decimal places."""
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def load_validation_metrics():
    if not MASTER_REPORT_FILE.is_file():
        raise FileNotFoundError(
            f"Master validation report not found: "
            f"{MASTER_REPORT_FILE}"
        )

    with MASTER_REPORT_FILE.open(
        "r", encoding="utf-8"
    ) as file:
        report = json.load(file)

    validators = report.get("validators", {})

    if not isinstance(validators, dict) or not validators:
        raise ValueError(
            "Master validation report has no usable "
            "'validators' section."
        )

    checks_passed = 0
    checks_failed = 0
    checks_total = 0

    for name, result in validators.items():
        if not isinstance(result, dict):
            raise ValueError(
                f"Invalid validator report entry: {name}"
            )

        if result.get("status") == "MISSING":
            continue

        if result.get("status") not in {"PASS", "FAIL"}:
            raise ValueError(
                f"Unexpected validation status for {name}: "
                f"{result.get('status')}"
            )

        passed = int(result.get("checks_passed", 0))
        failed = int(result.get("checks_failed", 0))
        total = int(result.get("checks_total", passed + failed))

        if passed + failed > total:
            raise ValueError(
                f"Inconsistent check totals for validator: {name}"
            )

        checks_passed += passed
        checks_failed += failed
        checks_total += total

    return {
        "validation_checks_passed": checks_passed,
        "validation_failures": checks_failed,
        "validation_checks_total": checks_total,
        "master_validation_status": report.get(
            "overall_status", "UNKNOWN"
        ),
        "validators_passed": report.get("validators_passed"),
        "validators_failed": report.get("validators_failed"),
        "validators_missing": report.get("validators_missing"),
    }


def generate_metrics():
    # 1. Dataset counts
    datasets = {
        metric: load_csv(filename)
        for metric, filename in DATASETS.items()
    }

    dataset_metrics = {
        metric: int(len(frame))
        for metric, frame in datasets.items()
    }

    tickets = datasets["ticket_count"]
    assignments = datasets["assignment_count"]
    sla_records = datasets["sla_record_count"]
    resolutions = datasets["resolution_count"]
    anomalies = datasets["anomaly_count"]

    # 2. Workflow metrics
    ticket_total = len(tickets)

    clarification_count = int(
        tickets["requires_clarification"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
        .sum()
    )

    sensitive_count = int(
        tickets["sensitive_flag"]
        .astype(str)
        .str.strip()
        .str.upper()
        .isin({"Y", "YES", "TRUE", "1"})
        .sum()
    )

    resolved_statuses = (
        resolutions["resolution_status"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    resolved_ticket_ids = set(
        resolutions.loc[
            resolved_statuses == "RESOLVED", "ticket_id"
        ].dropna().astype(str)
    )

    ticket_ids = set(tickets["ticket_id"].dropna().astype(str))
    resolved_ticket_count = len(resolved_ticket_ids & ticket_ids)

    breached_statuses = (
        sla_records["sla_breached"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    breached_count = int(
        breached_statuses.isin({"true", "1", "yes"}).sum()
    )

    escalation_count = int(
        assignments["assignment_reason"]
        .astype(str)
        .str.strip()
        .str.upper()
        .eq("ESCALATION")
        .sum()
    )

    workflow_metrics = {
        "clarification_rate": calculate_rate(
            clarification_count, ticket_total
        ),
        "resolution_rate": calculate_rate(
            resolved_ticket_count, ticket_total
        ),
        "sla_breach_rate": calculate_rate(
            breached_count, len(sla_records)
        ),
        "sensitive_case_rate": calculate_rate(
            sensitive_count, ticket_total
        ),
        "assignment_escalation_rate": calculate_rate(
            escalation_count, len(assignments)
        ),
    }

    # 3. Quality metrics from the master validation report
    validation_metrics = load_validation_metrics()

    if "issue_type" not in anomalies.columns:
        raise ValueError(
            "The anomalies dataset has no 'issue_type' column."
        )

    quality_metrics = {
        **validation_metrics,
        "anomaly_types": int(
            anomalies["issue_type"].nunique()
        ),
        "ground_truth_records": dataset_metrics.get(
            "ground_truth_record_count",
            len(load_csv("ground_truth.csv")),
        ),
    }

    # 4. Definitions make denominators and interpretation explicit
    metric_definitions = {
        "clarification_rate": (
            "Percentage of tickets with requires_clarification=True "
            "out of all tickets."
        ),
        "resolution_rate": (
            "Percentage of tickets with a RESOLVED resolution record "
            "out of all tickets. Unique ticket IDs are counted."
        ),
        "sla_breach_rate": (
            "Percentage of SLA records where sla_breached is true "
            "out of all SLA records."
        ),
        "sensitive_case_rate": (
            "Percentage of tickets flagged sensitive (Y/YES/TRUE/1) "
            "out of all tickets."
        ),
        "assignment_escalation_rate": (
            "Percentage of assignment records whose "
            "assignment_reason is ESCALATION out of all assignments."
        ),
        "rates_unit": "Percent, rounded to two decimal places.",
    }

    result = {
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "dataset_metrics": dataset_metrics,
        "workflow_metrics": workflow_metrics,
        "quality_metrics": quality_metrics,
        "metric_definitions": metric_definitions,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("\n=== PROJECT METRICS ===")
    print(
        f"Datasets counted: {len(dataset_metrics)}"
    )

    for name, count in dataset_metrics.items():
        print(f"{name}: {count}")

    print("\nWorkflow rates:")
    for name, rate in workflow_metrics.items():
        print(f"{name}: {rate}%")

    print("\nQuality metrics:")
    for name, value in quality_metrics.items():
        print(f"{name}: {value}")

    print(f"\nMetrics report saved: {OUTPUT_FILE}")
    return result


if __name__ == "__main__":
    try:
        generate_metrics()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"Metrics generation failed: {exc}", file=sys.stderr)
        sys.exit(1)
