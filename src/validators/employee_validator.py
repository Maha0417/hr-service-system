
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "validation"
SOURCE_FILE = DATA_DIR / "employees.csv"
DEPARTMENTS_FILE = DATA_DIR / "departments.csv"
REPORT_FILE = OUTPUT_DIR / "employee_validation_report.json"

REQUIRED_COLUMNS = [
    "employee_id",
    "first_name",
    "last_name",
    "email",
    "department_id",
    "department_name",
    "job_title",
    "employment_type",
    "employment_status",
    "location",
    "hire_date",
]


def add_check(checks, name, condition, details):
    checks.append({
        "check": name,
        "status": "PASS" if condition else "FAIL",
        "details": details,
    })


def validate_employees():
    if not SOURCE_FILE.is_file():
        raise FileNotFoundError(f"Missing dataset: {SOURCE_FILE}")
    if not DEPARTMENTS_FILE.is_file():
        raise FileNotFoundError(f"Missing dataset: {DEPARTMENTS_FILE}")

    employees = pd.read_csv(SOURCE_FILE, dtype=str).fillna("")
    departments = pd.read_csv(DEPARTMENTS_FILE, dtype=str).fillna("")

    checks = []
    columns_present = all(c in employees.columns for c in REQUIRED_COLUMNS)

    add_check(
        checks,
        "required_columns",
        columns_present,
        f"Required columns: {REQUIRED_COLUMNS}",
    )

    if columns_present:
        employee_ids = employees["employee_id"].str.strip()
        add_check(
            checks,
            "employee_ids_unique_and_nonblank",
            employee_ids.ne("").all() and employee_ids.is_unique,
            "Employee IDs must be nonblank and unique.",
        )

        emails = employees["email"].str.strip().str.lower()
        add_check(
            checks,
            "emails_nonblank_and_unique",
            emails.ne("").all() and emails.is_unique,
            "Employee emails must be nonblank and unique.",
        )

        nonblank_fields = [
            "first_name",
            "last_name",
            "department_id",
            "department_name",
            "job_title",
            "employment_type",
            "employment_status",
            "location",
            "hire_date",
        ]
        blank_fields = [
            column
            for column in nonblank_fields
            if employees[column].str.strip().eq("").any()
        ]
        add_check(
            checks,
            "required_values_nonblank",
            not blank_fields,
            f"Columns containing blank values: {blank_fields}",
        )

        department_ids = set(departments["department_id"].str.strip())
        employee_department_ids = set(
            employees["department_id"].str.strip()
        )
        unknown_departments = sorted(
            employee_department_ids - department_ids
        )
        add_check(
            checks,
            "department_references_valid",
            not unknown_departments,
            f"Unknown department IDs: {unknown_departments}",
        )

        department_names = dict(zip(
            departments["department_id"].str.strip(),
            departments["department_name"].str.strip(),
        ))
        mismatches = employees[
            employees.apply(
                lambda row: department_names.get(
                    row["department_id"].strip()
                ) != row["department_name"].strip(),
                axis=1,
            )
        ]["employee_id"].tolist()
        add_check(
            checks,
            "department_names_match_ids",
            not mismatches,
            f"Employees with mismatched department names: {mismatches[:20]}",
        )

        hire_dates = pd.to_datetime(
            employees["hire_date"], errors="coerce"
        )
        add_check(
            checks,
            "hire_dates_valid",
            hire_dates.notna().all(),
            f"Invalid hire-date row indexes: "
            f"{employees.index[hire_dates.isna()].tolist()[:20]}",
        )

    failed = sum(check["status"] == "FAIL" for check in checks)
    report = {
        "validator": "employee_validator",
        "dataset": str(SOURCE_FILE.relative_to(PROJECT_ROOT)),
        "total_records": len(employees),
        "checks_total": len(checks),
        "checks_passed": len(checks) - failed,
        "checks_failed": failed,
        "errors": [],
        "checks": checks,
        "status": "PASS" if failed == 0 else "FAIL",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Employee validation: {report['status']}")
    print(f"Records: {len(employees)}")
    print(f"Checks passed: {report['checks_passed']}")
    print(f"Checks failed: {report['checks_failed']}")
    print(f"Report saved: {REPORT_FILE}")

    for check in checks:
        if check["status"] == "FAIL":
            print(f"[FAIL] {check['check']}: {check['details']}")

    return report


if __name__ == "__main__":
    result = validate_employees()
    sys.exit(0 if result["status"] == "PASS" else 1)
