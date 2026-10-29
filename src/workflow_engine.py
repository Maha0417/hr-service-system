"""
HR Service System
Deterministic Workflow Engine

Responsibilities:
- Category-based routing
- Priority assignment
- Sensitive-case handling
- Clarification decisions
- Lifecycle transition validation
- SLA-based escalation decisions

Uses workflow_rules.py as the single source of truth.
"""

from typing import Any

from src.workflow_rules import (
    ROUTING_RULES,
    PRIORITY_RULES,
    LIFECYCLE_STATES,
    ALLOWED_TRANSITIONS,
    CLARIFICATION_SCENARIOS,
    ESCALATION_RULES,
)


def decide_routing(
    category_name: str,
    sensitive_flag: bool = False,
) -> dict[str, Any]:
    """Determine the responsible queue and explain the decision."""

    if sensitive_flag or category_name == "Employee Relations":
        return {
            "assigned_group": "HR_PARTNER",
            "reason": "SENSITIVE_CASE_ROUTING",
        }

    assigned_group = ROUTING_RULES.get(category_name)

    if assigned_group is None:
        return {
            "assigned_group": "HR_PARTNER",
            "reason": "UNKNOWN_CATEGORY_REQUIRES_HR_REVIEW",
        }

    return {
        "assigned_group": assigned_group,
        "reason": "CATEGORY_BASED_ROUTING",
    }


def decide_priority(category_name: str) -> str:
    """Return the configured priority for a category."""

    return PRIORITY_RULES.get(category_name, "HIGH")


def requires_clarification(scenario_type: str) -> bool:
    """Determine whether the scenario requires clarification."""

    return scenario_type.strip().upper() in CLARIFICATION_SCENARIOS


def validate_transition(current_state: str, next_state: str) -> bool:
    """Check a lifecycle transition against the configured rules."""

    current = current_state.strip().upper()
    next_value = next_state.strip().upper()

    if current not in LIFECYCLE_STATES:
        raise ValueError(f"Unknown lifecycle state: {current}")

    if next_value not in LIFECYCLE_STATES:
        raise ValueError(f"Unknown lifecycle state: {next_value}")

    return next_value in ALLOWED_TRANSITIONS[current]


def decide_escalation(
    priority: str,
    elapsed_hours: float,
) -> dict[str, Any]:
    """Evaluate elapsed hours against the configured escalation threshold."""

    normalized_priority = priority.strip().upper()

    if normalized_priority not in ESCALATION_RULES:
        raise ValueError(f"Unknown priority: {normalized_priority}")

    if elapsed_hours < 0:
        raise ValueError("Elapsed hours cannot be negative.")

    threshold = ESCALATION_RULES[normalized_priority]
    should_escalate = elapsed_hours >= threshold

    return {
        "should_escalate": should_escalate,
        "priority": normalized_priority,
        "threshold_hours": threshold,
        "elapsed_hours": elapsed_hours,
        "reason": (
            "ESCALATION_THRESHOLD_EXCEEDED"
            if should_escalate
            else "WITHIN_ESCALATION_THRESHOLD"
        ),
    }


def evaluate_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a ticket and return its explainable workflow decisions."""

    required_fields = {
        "category_name",
        "scenario_type",
        "sensitive_flag",
        "lifecycle_state",
    }

    missing = required_fields - ticket.keys()

    if missing:
        raise ValueError(f"Missing ticket fields: {sorted(missing)}")

    sensitive_value = str(ticket["sensitive_flag"]).strip().upper()
    if sensitive_value not in {"Y", "N", "TRUE", "FALSE", "1", "0"}:
        raise ValueError("sensitive_flag must be Y/N, TRUE/FALSE, or 1/0.")

    sensitive = sensitive_value in {"Y", "TRUE", "1"}

    category_name = str(ticket["category_name"]).strip()
    scenario_type = str(ticket["scenario_type"]).strip().upper()
    current_state = str(ticket["lifecycle_state"]).strip().upper()

    if not category_name:
        raise ValueError("category_name cannot be empty.")

    if current_state not in LIFECYCLE_STATES:
        raise ValueError(f"Unknown lifecycle state: {current_state}")

    routing = decide_routing(category_name, sensitive)
    clarification = requires_clarification(scenario_type)

    return {
        "ticket_id": ticket.get("ticket_id"),
        "assigned_group": routing["assigned_group"],
        "routing_reason": routing["reason"],
        "priority": decide_priority(category_name),
        "requires_clarification": clarification,
        "recommended_state": (
            "IN_PROGRESS" if sensitive
            else "WAITING_FOR_INFO" if clarification
            else "IN_PROGRESS"
        ),
        "current_state": current_state,
        "decision_status": "EVALUATED",
    }