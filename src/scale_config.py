import os

SEED = 20261022

SCALE = os.getenv("HR_DATA_SCALE", "starter").strip().lower()

SCALE_CONFIG = {
    "starter": {
        "ticket_count": 50,
        "scenario_counts": {
            "NORMAL": 30,
            "AMBIGUOUS": 5,
            "MISSING_CONTEXT": 5,
            "CONFIDENTIAL": 5,
            "OUTDATED_POLICY": 5,
        },
        "anomalies_per_type": 5,
    },
    "full": {
        "ticket_count": 5000,
        "scenario_counts": {
            "NORMAL": 3000,
            "AMBIGUOUS": 500,
            "MISSING_CONTEXT": 500,
            "CONFIDENTIAL": 500,
            "OUTDATED_POLICY": 500,
        },
        "anomalies_per_type": 50,
    },
}

if SCALE not in SCALE_CONFIG:
    raise ValueError(
        f"Invalid HR_DATA_SCALE={SCALE!r}. Choose 'starter' or 'full'."
    )

CURRENT_SCALE = SCALE_CONFIG[SCALE]
TICKET_COUNT = CURRENT_SCALE["ticket_count"]
SCENARIO_COUNTS = CURRENT_SCALE["scenario_counts"]
ANOMALIES_PER_TYPE = CURRENT_SCALE["anomalies_per_type"]
