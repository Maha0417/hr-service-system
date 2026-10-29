import random
from pathlib import Path

import pandas as pd
from faker import Faker


# Reproducibility
SEED = 20261022

random.seed(SEED)
Faker.seed(SEED)

# Project paths
OUTPUT_DIR = Path("data/csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Master department data
DEPARTMENTS = [
    "HR",
    "Engineering",
    "Finance",
    "Sales",
    "Marketing",
    "IT",
    "Operations",
    "Legal",
    "Recruiting",
    "Support",
]


def generate_departments():
    departments = []

    for i, department_name in enumerate(DEPARTMENTS, start=1):
        departments.append(
            {
                "department_id": f"DEP-{i:03}",
                "department_name": department_name,
            }
        )

    df = pd.DataFrame(departments)

    # Validation
    assert len(df) == 10
    assert df["department_id"].is_unique
    assert df["department_name"].is_unique

    return df


if __name__ == "__main__":
    department_df = generate_departments()

    output_file = OUTPUT_DIR / "departments.csv"
    department_df.to_csv(output_file, index=False)

    print(f"Generated {len(department_df)} departments")
    print(f"Saved to: {output_file}")