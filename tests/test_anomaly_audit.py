import json
from pathlib import Path

import pandas as pd

from src.anomaly_audit import (
    evaluate_policy_reference,
    evaluate_sensitive_routing,
    evaluate_sla_record,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "csv"
REPORT = ROOT / "output" / "anomaly_audit" / "anomaly_audit_report.json"

EXPECTED_TYPES = {
    "obsolete_policy_reference",
    "sensitive_case_routed_general_queue",
    "sla_business_hours_error",
    "unsupported_claim",
}


def test_anomaly_dataset_has_expected_types_and_counts():
    anomalies = pd.read_csv(DATA / "anomalies.csv", dtype=str).fillna("")
    counts = anomalies["issue_type"].value_counts().to_dict()

    assert len(anomalies) == 200
    assert anomalies["anomaly_id"].is_unique
    assert set(counts) == EXPECTED_TYPES
    assert all(counts[issue_type] == 50 for issue_type in EXPECTED_TYPES)


def test_anomaly_references_are_present():
    anomalies = pd.read_csv(DATA / "anomalies.csv", dtype=str).fillna("")
    tickets = pd.read_csv(DATA / "tickets.csv", dtype=str).fillna("")
    ground_truth = pd.read_csv(DATA / "ground_truth.csv", dtype=str).fillna("")

    assert anomalies["entity_id"].isin(set(tickets["ticket_id"])).all()
    assert anomalies["ground_truth_id"].isin(
        set(ground_truth["ground_truth_id"])
    ).all()


def test_audit_report_is_read_only_and_has_all_types():
    assert REPORT.is_file()
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report["report_type"] == "READ_ONLY_ANOMALY_AUDIT"
    assert report["source_datasets_modified"] is False
    assert report["runtime_database_modified"] is False
    assert report["total_labelled_anomalies"] == 200
    assert set(report["summary_by_type"]) == EXPECTED_TYPES
    assert report["unexpected_anomaly_types"] == []


def test_audit_status_counts_reconcile():
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert len(report["records"]) == 200

    for issue_type, summary in report["summary_by_type"].items():
        assert summary["labelled"] == 50
        assert (
            summary["MATCH"]
            + summary["MISMATCH"]
            + summary["FAIL"]
            + summary["INCONCLUSIVE"]
            == summary["labelled"]
        )


def test_unsupported_claims_are_not_proven_by_citation_ids_alone():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    summary = report["summary_by_type"]["unsupported_claim"]

    assert summary["labelled"] == 50
    assert (
        summary["MATCH"]
        + summary["MISMATCH"]
        + summary["FAIL"]
        + summary["INCONCLUSIVE"]
        == 50
    )
    assert any(
        "semantic" in limitation.lower()
        for limitation in report["limitations"]
    )


def test_sla_detector_handles_controlled_faults_and_valid_records():
    faulty_record = {
        "elapsed_hours": "50",
        "resolution_target_hours": "48",
        "business_hours_only": "False",
        "sla_breached": "False",
    }

    status, _, evidence = evaluate_sla_record(faulty_record)

    assert status == "MATCH"
    assert evidence["calculated_clock_hour_breach"] is True
    assert evidence["stored_breach"] is False

    valid_record = {
        "elapsed_hours": "50",
        "resolution_target_hours": "48",
        "business_hours_only": "False",
        "sla_breached": "True",
    }

    status, _, evidence = evaluate_sla_record(valid_record)

    assert status == "MISMATCH"
    assert evidence["calculated_clock_hour_breach"] is True
    assert evidence["stored_breach"] is True

    business_hours_record = {
        "elapsed_hours": "50",
        "resolution_target_hours": "48",
        "business_hours_only": "True",
        "sla_breached": "True",
    }

    status, _, evidence = evaluate_sla_record(business_hours_record)

    assert status == "MATCH"
    assert evidence["business_hours_only"] is True


def test_policy_detector_distinguishes_expired_and_valid_versions():
    versions = {
        "PV_OLD": {
            "status": "EXPIRED",
            "effective_date": "2024-01-01",
            "expiration_date": "2025-12-31",
        },
        "PV_CURRENT": {
            "status": "APPROVED",
            "effective_date": "2026-01-01",
            "expiration_date": "2026-12-31",
        },
    }

    expired_records = pd.DataFrame([
        {"policy_version_id": "PV_OLD"},
    ])

    status, _, evidence = evaluate_policy_reference(
        expired_records,
        "2026-06-01",
        versions,
        "PV_CURRENT",
    )

    assert status == "MATCH"
    assert evidence["expired_or_date_invalid_versions"] == ["PV_OLD"]

    valid_records = pd.DataFrame([
        {"policy_version_id": "PV_CURRENT"},
    ])

    status, _, evidence = evaluate_policy_reference(
        valid_records,
        "2026-06-01",
        versions,
        "PV_CURRENT",
    )

    assert status == "MISMATCH"
    assert evidence["expired_or_date_invalid_versions"] == []


def test_sensitive_routing_detector_flags_general_queue():
    ticket = {
        "sensitive_flag": "True",
        "category_id": "CAT_BENEFITS",
        "scenario_type": "STANDARD",
    }
    category = {
        "category_name": "Benefits",
    }
    assignments = pd.DataFrame([
        {
            "assigned_group": "HR_PARTNER",
            "assigned_timestamp": "2026-01-01T09:00:00",
        },
        {
            "assigned_group": "BENEFITS_TEAM",
            "assigned_timestamp": "2026-01-02T09:00:00",
        },
    ])

    status, reason, evidence = evaluate_sensitive_routing(
        assignments,
        ticket,
        category,
        "HR_PARTNER",
    )

    assert status == "MATCH"
    assert "not HR_PARTNER" in reason
    assert evidence["sensitive_case"] is True
    assert evidence["latest_recorded_assignment_group"] == "BENEFITS_TEAM"
    assert evidence["expected_route"] == "HR_PARTNER"


def test_sensitive_routing_accepts_latest_hr_partner_assignment():
    ticket = {
        "sensitive_flag": "True",
        "category_id": "CAT_BENEFITS",
        "scenario_type": "STANDARD",
    }
    category = {
        "category_name": "Benefits",
    }
    assignments = pd.DataFrame([
        {
            "assigned_group": "BENEFITS_TEAM",
            "assigned_timestamp": "2026-01-01T09:00:00",
        },
        {
            "assigned_group": "HR_PARTNER",
            "assigned_timestamp": "2026-01-02T09:00:00",
        },
    ])

    status, _, evidence = evaluate_sensitive_routing(
        assignments,
        ticket,
        category,
        "HR_PARTNER",
    )

    assert status == "MISMATCH"
    assert evidence["latest_recorded_assignment_group"] == "HR_PARTNER"


def test_sensitive_routing_is_inconclusive_without_assignment_history():
    ticket = {
        "sensitive_flag": "True",
        "category_id": "CAT_BENEFITS",
        "scenario_type": "STANDARD",
    }
    category = {
        "category_name": "Benefits",
    }
    assignments = pd.DataFrame(
        columns=["assigned_group", "assigned_timestamp"]
    )

    status, _, evidence = evaluate_sensitive_routing(
        assignments,
        ticket,
        category,
        "HR_PARTNER",
    )

    assert status == "INCONCLUSIVE"
    assert evidence["sensitive_case"] is True
    assert evidence["latest_recorded_assignment_group"] == ""