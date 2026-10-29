from pathlib import Path

import pandas as pd


# Project paths
DEPARTMENT_FILE = Path("data/csv/departments.csv")
OUTPUT_DIR = Path("data/csv")
OUTPUT_FILE = OUTPUT_DIR / "policy_documents.csv"


# Realistic HR policies
POLICIES = [
    ("Annual Leave Policy", "Leave", "All Employees"),
    ("Sick Leave Policy", "Leave", "All Employees"),
    ("Parental Leave Policy", "Leave", "All Employees"),
    ("Bereavement Leave Policy", "Leave", "All Employees"),
    ("Medical Benefits Policy", "Benefits", "All Employees"),
    ("Health Insurance Policy", "Benefits", "All Employees"),
    ("Dental Benefits Policy", "Benefits", "All Employees"),
    ("Vision Benefits Policy", "Benefits", "All Employees"),
    ("Payroll Processing Policy", "Payroll", "All Employees"),
    ("Salary Advance Policy", "Payroll", "All Employees"),
    ("Expense Reimbursement Policy", "Payroll", "All Employees"),
    ("Employee Onboarding Policy", "Onboarding", "New Hires"),
    ("Background Verification Policy", "Onboarding", "New Hires"),
    ("Probation Policy", "Onboarding", "New Hires"),
    ("Remote Work Policy", "Remote Work", "All Employees"),
    ("Hybrid Work Policy", "Remote Work", "All Employees"),
    ("Work From Home Equipment Policy", "Remote Work", "All Employees"),
    ("Business Travel Policy", "Travel", "All Employees"),
    ("Travel Reimbursement Policy", "Travel", "All Employees"),
    ("International Travel Policy", "Travel", "Managers"),
    ("Performance Review Policy", "Performance", "All Employees"),
    ("Promotion Policy", "Performance", "Managers"),
    ("Goal Setting Policy", "Performance", "Managers"),
    ("Learning and Development Policy", "Performance", "All Employees"),
    ("Employee Code of Conduct", "Employee Relations", "All Employees"),
    ("Anti-Harassment Policy", "Employee Relations", "All Employees"),
    ("Workplace Investigation Policy", "Employee Relations", "HR"),
    ("Disciplinary Action Policy", "Employee Relations", "HR"),
    ("Grievance Handling Policy", "Employee Relations", "All Employees"),
    ("Data Privacy Policy", "Compliance", "All Employees"),
    ("Information Security Policy", "Compliance", "All Employees"),
    ("Acceptable Use Policy", "Compliance", "All Employees"),
    ("Conflict of Interest Policy", "Compliance", "Managers"),
    ("Whistleblower Policy", "Compliance", "All Employees"),
    ("Overtime Policy", "Payroll", "All Employees"),
    ("Shift Allowance Policy", "Payroll", "All Employees"),
    ("Employee Referral Policy", "Recruitment", "All Employees"),
    ("Internal Mobility Policy", "Recruitment", "All Employees"),
    ("Internship Policy", "Recruitment", "Managers"),
    ("Contractor Engagement Policy", "Recruitment", "Managers"),
    ("Flexible Working Hours Policy", "Remote Work", "All Employees"),
    ("Attendance Policy", "Leave", "All Employees"),
    ("Holiday Calendar Policy", "Leave", "All Employees"),
    ("Retention Bonus Policy", "Benefits", "Managers"),
    ("Recognition and Rewards Policy", "Benefits", "All Employees"),
    ("Emergency Leave Policy", "Leave", "All Employees"),
    ("Employee Separation Policy", "Employee Relations", "HR"),
    ("Exit Clearance Policy", "Employee Relations", "HR"),
    ("Knowledge Transfer Policy", "Employee Relations", "Managers"),
    ("Manager Responsibilities Policy", "Performance", "Managers"),
]


def load_hr_department_id():
    """Load and validate the HR department from master data."""

    if not DEPARTMENT_FILE.exists():
        raise FileNotFoundError(
            f"Department file not found: {DEPARTMENT_FILE}. "
            "Run master_data.py first."
        )

    departments = pd.read_csv(DEPARTMENT_FILE)

    required_columns = {"department_id", "department_name"}

    if not required_columns.issubset(departments.columns):
        raise ValueError(
            "departments.csv is missing required columns."
        )

    hr_departments = departments[
        departments["department_name"] == "HR"
    ]

    if len(hr_departments) != 1:
        raise ValueError(
            "Expected exactly one HR department."
        )

    return hr_departments.iloc[0]["department_id"], departments


def generate_policies():
    """Generate realistic HR policy master records."""

    hr_department_id, departments = load_hr_department_id()

    valid_departments = set(departments["department_id"])

    policies = []

    for i, (name, category, audience) in enumerate(POLICIES, start=1):

        policy = {
            "policy_id": f"POL-HR-2026-{i:03}",
            "policy_name": name,
            "policy_category": category,
            "audience": audience,
            "owner_department_id": hr_department_id,
            "created_date": "2026-01-01",
            "lifecycle_state": "ACTIVE",
        }

        # Foreign-key validation
        assert policy["owner_department_id"] in valid_departments, (
            f"Invalid department ID: "
            f"{policy['owner_department_id']}"
        )

        policies.append(policy)

    policy_df = pd.DataFrame(policies)

    # Dataset validations
    assert len(policy_df) == 50
    assert policy_df["policy_id"].is_unique
    assert policy_df["owner_department_id"].isin(valid_departments).all()

    return policy_df


if __name__ == "__main__":

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    policy_df = generate_policies()

    policy_df.to_csv(OUTPUT_FILE, index=False)

    print(f"Generated {len(policy_df)} policy documents")
    print(f"Saved to: {OUTPUT_FILE}")