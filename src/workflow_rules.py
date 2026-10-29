"""
HR Service System
Workflow Rules

Single source of truth for:

- Routing
- Priorities
- Lifecycle transitions
- Clarification rules
- Escalation rules
"""

# -----------------------
# Routing Rules
# -----------------------

ROUTING_RULES = {
    "Benefits": "BENEFITS_TEAM",
    "Leave": "LEAVE_TEAM",
    "Payroll": "PAYROLL_TEAM",
    "Onboarding": "ONBOARDING_TEAM",
    "Employee Relations": "HR_PARTNER"
}

# -----------------------
# Priority Rules
# -----------------------

PRIORITY_RULES = {
    "Benefits": "LOW",
    "Leave": "MEDIUM",
    "Payroll": "MEDIUM",
    "Onboarding": "LOW",
    "Employee Relations": "HIGH"
}

# -----------------------
# Lifecycle States
# -----------------------

LIFECYCLE_STATES = [
    "OPEN",
    "WAITING_FOR_INFO",
    "IN_PROGRESS",
    "RESOLVED",
    "CLOSED"
]

# -----------------------
# Allowed State Transitions
# -----------------------

ALLOWED_TRANSITIONS = {

    "OPEN": [
        "WAITING_FOR_INFO",
        "IN_PROGRESS"
    ],

    "WAITING_FOR_INFO": [
        "IN_PROGRESS"
    ],

    "IN_PROGRESS": [
        "WAITING_FOR_INFO",
        "RESOLVED"
    ],

    "RESOLVED": [
        "CLOSED"
    ],

    "CLOSED": []
}

# -----------------------
# Clarification Rules
# -----------------------

CLARIFICATION_SCENARIOS = {
    "AMBIGUOUS",
    "MISSING_CONTEXT",
    "CONFIDENTIAL"
}

# -----------------------
# Escalation Thresholds
# (Hours)
# -----------------------

ESCALATION_RULES = {
    "LOW": 72,
    "MEDIUM": 48,
    "HIGH": 24,
    "CRITICAL": 8
}
