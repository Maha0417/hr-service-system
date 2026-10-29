from pathlib import Path
import logging

import pandas as pd


OUTPUT_DIR = Path("data/csv")
OUTPUT_FILE = OUTPUT_DIR / "categories.csv"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


CATEGORIES = [
    {
        "category_id": "CAT-001",
        "category_name": "Benefits",
        "sensitive_flag": "N",
        "default_queue": "BENEFITS_TEAM",
        "active_flag": "Y",
    },
    {
        "category_id": "CAT-002",
        "category_name": "Leave",
        "sensitive_flag": "N",
        "default_queue": "LEAVE_TEAM",
        "active_flag": "Y",
    },
    {
        "category_id": "CAT-003",
        "category_name": "Payroll",
        "sensitive_flag": "N",
        "default_queue": "PAYROLL_TEAM",
        "active_flag": "Y",
    },
    {
        "category_id": "CAT-004",
        "category_name": "Onboarding",
        "sensitive_flag": "N",
        "default_queue": "ONBOARDING_TEAM",
        "active_flag": "Y",
    },
    {
        "category_id": "CAT-005",
        "category_name": "Employee Relations",
        "sensitive_flag": "Y",
        "default_queue": "HR_PARTNER",
        "active_flag": "Y",
    },
]


def generate_categories():
    """Generate and validate category master data."""

    logger.info("Generating category master data")

    category_df = pd.DataFrame(CATEGORIES)

    logger.info("Validating category data")

    # Record count
    assert len(category_df) == 5

    # Required columns
    required_columns = {
        "category_id",
        "category_name",
        "sensitive_flag",
        "default_queue",
        "active_flag",
    }

    assert required_columns.issubset(
        category_df.columns
    )

    # Unique IDs
    assert category_df["category_id"].is_unique

    # Unique category names
    assert category_df["category_name"].is_unique

    # Validate flags
    assert category_df["sensitive_flag"].isin(
        {"Y", "N"}
    ).all()

    assert category_df["active_flag"].isin(
        {"Y", "N"}
    ).all()

    # Validate required values are not empty
    assert category_df["default_queue"].notna().all()
    assert (
        category_df["default_queue"].str.strip() != ""
    ).all()

    logger.info(
        "Category validation successful"
    )

    return category_df


def main():
    """Generate and save category master data."""

    try:
        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        category_df = generate_categories()

        category_df.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        logger.info(
            "Generated %d categories",
            len(category_df),
        )

        logger.info(
            "Saved to: %s",
            OUTPUT_FILE,
        )

    except ValueError as error:
        logger.error(
            "Validation error: %s",
            error,
        )
        raise

    except AssertionError as error:
        logger.error(
            "Generated data validation failed: %s",
            error,
        )
        raise

    except Exception:
        logger.exception(
            "Unexpected error while generating categories"
        )
        raise


if __name__ == "__main__":
    main()