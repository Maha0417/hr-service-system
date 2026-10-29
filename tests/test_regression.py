import json
from pathlib import Path

import pandas as pd
import pytest

from src.workflow_engine import evaluate_ticket, decide_escalation
from src.policy_lookup import lookup_policy


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "csv"


@pytest.fixture(scope="module")
def datasets():
    tickets = pd.read_csv(DATA / "tickets.csv", dtype=str).fillna("")
    categories = pd.read_csv(DATA / "categories.csv", dtype=str).fillna("")
    ground_truth = pd.read_csv(DATA / "ground_truth.csv", dtype=str).fillna("")
    assignments = pd.read_csv(DATA / "assignments.csv", dtype=str).fillna("")
    return tickets, categories, ground_truth, assignments


def test_all_tickets_have_unique_ids(datasets):
    tickets, _, _, _ = datasets
    assert len(tickets) == 5000
    assert tickets["ticket_id"].ne("").all()
    assert tickets["ticket_id"].is_unique


def test_all_tickets_match_ground_truth_routing_and_clarification(datasets):
    tickets, categories, ground_truth, _ = datasets
    category_map = categories.set_index("category_id")["category_name"].to_dict()
    truth = ground_truth.set_index("entity_id")

    assert tickets["ticket_id"].isin(truth.index).all()

    for row in tickets.to_dict("records"):
        result = evaluate_ticket({
            "ticket_id": row["ticket_id"],
            "category_name": category_map[row["category_id"]],
            "scenario_type": row["scenario_type"],
            "sensitive_flag": row["sensitive_flag"],
            "lifecycle_state": row["ticket_status"],
        })
        expected = truth.loc[row["ticket_id"]]
        assert result["assigned_group"] == expected["expected_route"], row["ticket_id"]
        assert result["requires_clarification"] == (
            str(expected["expected_clarification"]).strip().lower() == "true"
        ), row["ticket_id"]


def test_all_tickets_resolve_to_expected_current_policy(datasets):
    tickets, _, ground_truth, _ = datasets
    truth = ground_truth.set_index("entity_id")

    for row in tickets.to_dict("records"):
        result = lookup_policy(row["policy_id"])
        assert result["version_id"] == truth.loc[
            row["ticket_id"], "expected_policy_version"
        ], row["ticket_id"]
        assert result["article_id"]
        assert result["citation"]


def test_sensitive_cases_route_to_hr_partner(datasets):
    tickets, categories, _, _ = datasets
    category_map = categories.set_index("category_id")["category_name"].to_dict()

    for row in tickets.to_dict("records"):
        sensitive = str(row["sensitive_flag"]).strip().upper() in {
            "Y", "TRUE", "YES", "1"
        } or row["scenario_type"].upper() == "CONFIDENTIAL"

        if sensitive or category_map[row["category_id"]] == "Employee Relations":
            result = evaluate_ticket({
                "ticket_id": row["ticket_id"],
                "category_name": category_map[row["category_id"]],
                "scenario_type": row["scenario_type"],
                "sensitive_flag": "Y" if sensitive else "N",
                "lifecycle_state": row["ticket_status"],
            })
            assert result["assigned_group"] == "HR_PARTNER", row["ticket_id"]


@pytest.mark.parametrize(
    ("priority", "elapsed", "expected"),
    [
        ("LOW", 71, False),
        ("LOW", 72, True),
        ("MEDIUM", 47, False),
        ("MEDIUM", 48, True),
        ("HIGH", 23, False),
        ("HIGH", 24, True),
        ("CRITICAL", 7, False),
        ("CRITICAL", 8, True),
    ],
)
def test_sla_threshold_boundaries(priority, elapsed, expected):
    assert decide_escalation(priority, elapsed)["should_escalate"] is expected


def test_saved_runtime_escalation_is_consistent():
    runtime_file = ROOT / "data" / "runtime" / "processed_requests.jsonl"
    if not runtime_file.exists():
        pytest.skip("No runtime records exist yet")

    records = [
        json.loads(line)
        for line in runtime_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(
        (r for r in records if r["ticket_id"] == "TKT-2026-000004"),
        None,
    )
    if record is None:
        pytest.skip("The known escalation test ticket has not been processed")

    escalation_events = [
        event for event in record["events"]
        if event["event_type"] == "SLA_ESCALATION"
    ]
    assert record["sla"]["should_escalate"] is True
    assert record["decision"]["original_assigned_group"] == "LEAVE_TEAM"
    assert record["decision"]["assigned_group"] == "HR_PARTNER"
    assert record["decision"]["sla_escalation_destination"] == "HR_PARTNER"
    assert len(escalation_events) == 1
    assert escalation_events[0]["assigned_group"] == "HR_PARTNER"
