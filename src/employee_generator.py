from pathlib import Path
import logging
import random

import pandas as pd
from faker import Faker


# --------------------------------------------------
# Configuration
# --------------------------------------------------

SEED = 20261022
EMPLOYEE_COUNT = 1000

DEPARTMENT_FILE = Path("data/csv/departments.csv")
OUTPUT_DIR = Path("data/csv")
OUTPUT_FILE = OUTPUT_DIR / "employees.csv"


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Reproducibility
# --------------------------------------------------

random.seed(SEED)
Faker.seed(SEED)

fake = Faker()


# --------------------------------------------------
# Load Departments
# --------------------------------------------------

def load_departments():
    """Load and validate department master data."""

    logger.info(
        "Loading departments from %s",
        DEPARTMENT_FILE,
    )

    if not DEPARTMENT_FILE.exists():
        raise FileNotFoundError(
            f"Department file not found: {DEPARTMENT_FILE}. "
            "Run master_data.py first."
        )

    departments = pd.read_csv(DEPARTMENT_FILE)

    required_columns = {
        "department_id",
        "department_name",
    }

    missing_columns = required_columns - set(
        departments.columns
    )

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if departments["department_id"].duplicated().any():
        raise ValueError(
            "Duplicate department_id found."
        )

    logger.info(
        "Loaded %d departments successfully",
        len(departments),
    )

    return departments


# --------------------------------------------------
# Generate Employees
# --------------------------------------------------

def generate_employees():
    """Generate realistic employee master data."""

    departments = load_departments()

    logger.info(
        "Generating %d employees",
        EMPLOYEE_COUNT,
    )

    department_records = departments.to_dict(
        orient="records"
    )

    employees = []

    for employee_number in range(
        1,
        EMPLOYEE_COUNT + 1,
    ):

        department = random.choice(
            department_records
        )

        first_name = fake.first_name()
        last_name = fake.last_name()

        employee_id = (
            f"EMP-{employee_number:05}"
        )

        email = (
            f"{first_name.lower()}."
            f"{last_name.lower()}"
            f"{employee_number}"
            "@company.com"
        )

        employees.append(
            {
                "employee_id": employee_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "department_id": department[
                    "department_id"
                ],
                "department_name": department[
                    "department_name"
                ],
                "job_title": fake.job(),
                "employment_type": random.choice(
                    [
                        "Full-Time",
                        "Part-Time",
                        "Contract",
                        "Intern",
                    ]
                ),
                "employment_status": random.choice(
                    [
                        "Active",
                        "Active",
                        "Active",
                        "Active",
                        "On Leave",
                    ]
                ),
                "location": random.choice(
                    [
                        "Bengaluru",
                        "Hyderabad",
                        "Pune",
                        "Chennai",
                        "Mumbai",
                        "Delhi",
                    ]
                ),
                "hire_date": fake.date_between(
                    start_date="-10y",
                    end_date="-30d",
                ),
            }
        )

    employee_df = pd.DataFrame(employees)

    # --------------------------------------------------
    # Validation
    # --------------------------------------------------

    logger.info("Validating generated employees")

    assert len(employee_df) == EMPLOYEE_COUNT

    assert employee_df["employee_id"].is_unique

    assert employee_df["email"].is_unique

    assert employee_df["department_id"].isin(
        departments["department_id"]
    ).all()

    assert employee_df["department_name"].isin(
        departments["department_name"]
    ).all()

    assert employee_df["employment_type"].isin(
        {
            "Full-Time",
            "Part-Time",
            "Contract",
            "Intern",
        }
    ).all()

    assert employee_df["employment_status"].isin(
        {
            "Active",
            "On Leave",
        }
    ).all()

    assert employee_df["hire_date"].notna().all()

    logger.info(
        "Employee validation successful"
    )

    return employee_df


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    """Generate and save employee master data."""

    try:
        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        employee_df = generate_employees()

        employee_df.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        logger.info(
            "Generated %d employees",
            len(employee_df),
        )

        logger.info(
            "Saved to: %s",
            OUTPUT_FILE,
        )

    except FileNotFoundError as error:
        logger.error(
            "Input file error: %s",
            error,
        )
        raise

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
            "Unexpected error while generating employees"
        )
        raise


if __name__ == "__main__":
    main()