from pathlib import Path
import logging

import pandas as pd


# --------------------------------------------------
# Configuration
# --------------------------------------------------

POLICY_FILE = Path("data/csv/policy_documents.csv")
OUTPUT_DIR = Path("data/csv")
OUTPUT_FILE = OUTPUT_DIR / "policy_versions.csv"


# --------------------------------------------------
# Logging Configuration
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Load Policy Data
# --------------------------------------------------

def load_policies():
    """Load and validate policy master data."""

    logger.info("Loading policy data from %s", POLICY_FILE)

    if not POLICY_FILE.exists():
        raise FileNotFoundError(
            f"Policy file not found: {POLICY_FILE}. "
            "Run policy_generator.py first."
        )

    policies = pd.read_csv(POLICY_FILE)

    required_columns = {
        "policy_id",
        "policy_name",
        "policy_category",
    }

    missing_columns = required_columns - set(policies.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if policies["policy_id"].duplicated().any():
        raise ValueError(
            "Duplicate policy_id found in policy_documents.csv."
        )

    logger.info(
        "Loaded %d policies successfully",
        len(policies),
    )

    return policies


# --------------------------------------------------
# Generate Policy Versions
# --------------------------------------------------

def generate_policy_versions():
    """Generate three versions for every policy."""

    policies = load_policies()

    logger.info("Generating policy versions")

    versions = []

    for _, policy in policies.iterrows():

        policy_id = policy["policy_id"]

        # Version 1 - Expired
        versions.append(
            {
                "version_id": f"VER-{policy_id}-01",
                "policy_id": policy_id,
                "version_number": 1,
                "effective_date": "2024-01-01",
                "expiration_date": "2024-12-31",
                "is_current": False,
                "status": "EXPIRED",
                "change_summary": (
                    "Initial policy version"
                ),
            }
        )

        # Version 2 - Expired
        versions.append(
            {
                "version_id": f"VER-{policy_id}-02",
                "policy_id": policy_id,
                "version_number": 2,
                "effective_date": "2025-01-01",
                "expiration_date": "2025-12-31",
                "is_current": False,
                "status": "EXPIRED",
                "change_summary": (
                    "Policy updated with revised guidelines"
                ),
            }
        )

        # Version 3 - Current
        versions.append(
            {
                "version_id": f"VER-{policy_id}-03",
                "policy_id": policy_id,
                "version_number": 3,
                "effective_date": "2026-01-01",
                "expiration_date": None,
                "is_current": True,
                "status": "CURRENT",
                "change_summary": (
                    "Current policy version with updated rules"
                ),
            }
        )

    version_df = pd.DataFrame(versions)

    # --------------------------------------------------
    # Validation
    # --------------------------------------------------

    logger.info("Validating generated policy versions")

    assert len(version_df) == 150

    assert version_df["version_id"].is_unique

    assert version_df["policy_id"].isin(
        policies["policy_id"]
    ).all()

    versions_per_policy = (
        version_df.groupby("policy_id")
        .size()
    )

    assert (versions_per_policy == 3).all()

    current_versions = version_df[
        version_df["is_current"] == True
    ]

    assert len(current_versions) == 50

    current_per_policy = (
        current_versions.groupby("policy_id")
        .size()
    )

    assert (current_per_policy == 1).all()

    assert set(version_df["status"]) == {
        "EXPIRED",
        "CURRENT",
    }

    logger.info(
        "Policy version validation successful"
    )

    return version_df


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    """Generate and save policy versions."""

    try:
        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        version_df = generate_policy_versions()

        version_df.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        logger.info(
            "Generated %d policy versions",
            len(version_df),
        )

        logger.info(
            "Saved to: %s",
            OUTPUT_FILE,
        )

    except FileNotFoundError as error:
        logger.error("Input file error: %s", error)
        raise

    except ValueError as error:
        logger.error("Validation error: %s", error)
        raise

    except AssertionError as error:
        logger.error(
            "Generated data validation failed: %s",
            error,
        )
        raise

    except Exception:
        logger.exception(
            "Unexpected error while generating policy versions"
        )
        raise


if __name__ == "__main__":
    main()