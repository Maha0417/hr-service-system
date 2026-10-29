
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data" / "csv"
OUTPUT_DIR = PROJECT_ROOT / "output" / "validation"
SOURCE_FILE = DATA_DIR / "departments.csv"
REPORT_FILE = OUTPUT_DIR / "department_validation_report.json"

REQUIRED_COLUMNS = ["department_id", "department_name"]


def validate_departments():
    checks = []
    errors = []

    if not SOURCE_FILE.is_file():
        raise FileNotFoundError(f"Missing dataset: {SOURCE_FILE}")

    df = pd.read_csv(SOURCE_FILE, dtype=str).fillna("")

    checks.append({
        "check": "required_columns",
        "status": "PASS" if all(c in df.columns for c in REQUIRED_COLUMNS) else "FAIL",
        "details": f"Required columns: {REQUIRED_COLUMNS}",
    })

    columns_present = all(c in df.columns for c in REQUIRED_COLUMNS)

    if columns_present:
        checks.append({
            "check": "dataset_not_empty",
            "status": "PASS" if len(df) > 0 else "FAIL",
            "details": f"Found {len(df)} departments.",
        })

        ids = df["department_id"].str.strip()
        checks.append({
            "check": "department_ids_unique_and_nonblank",
            "status": "PASS" if ids.ne("").all() and ids.is_unique else "FAIL",
            "details": "Department IDs must be nonblank and unique.",
        })

        names = df["department_name"].str.strip()
        checks.append({
            "check": "department_names_nonblank",
            "status": "PASS" if names.ne("").all() else "FAIL",
            "details": "Department names must not be blank.",
        })

    failed = sum(c["status"] == "FAIL" for c in checks)
    report = {
        "validator": "department_validator",
        "dataset": str(SOURCE_FILE.relative_to(PROJECT_ROOT)),
        "total_records": len(df),
        "checks_total": len(checks),
        "checks_passed": len(checks) - failed,
        "checks_failed": failed,
        "errors": errors,
        "checks": checks,
        "status": "PASS" if failed == 0 else "FAIL",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Department validation: {report['status']}")
    print(f"Records: {len(df)}")
    print(f"Checks passed: {report['checks_passed']}")
    print(f"Checks failed: {report['checks_failed']}")
    print(f"Report saved: {REPORT_FILE}")

    return report


if __name__ == "__main__":
    result = validate_departments()
    sys.exit(0 if result["status"] == "PASS" else 1)
