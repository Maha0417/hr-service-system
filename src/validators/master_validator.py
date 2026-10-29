
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_DIR = ROOT / "src" / "validators"
DATA_DIR = ROOT / "data" / "csv"
REPORT_DIR = ROOT / "output" / "validation"
MASTER_REPORT = REPORT_DIR / "master_validation_report.json"

VALIDATORS = {
    "departments": {
        "script": "department_validator.py",
        "report": "department_validation_report.json",
        "dataset": "departments.csv",
    },
    "employees": {
        "script": "employee_validator.py",
        "report": "employee_validation_report.json",
        "dataset": "employees.csv",
    },
    "tickets": {
        "script": "ticket_validator.py",
        "report": "ticket_validation_report.json",
        "dataset": "tickets.csv",
    },
    "messages": {
        "script": "message_validator.py",
        "report": "message_validation_report.json",
        "dataset": "messages.csv",
    },
    "assignments": {
        "script": "assignment_validator.py",
        "report": "assignment_validation_report.json",
        "dataset": "assignments.csv",
    },
    "sla": {
        "script": "sla_validator.py",
        "report": "sla_validation_report.json",
        "dataset": "sla_records.csv",
    },
    "resolutions": {
        "script": "resolution_validator.py",
        "report": "resolution_validation_report.json",
        "dataset": "resolutions.csv",
    },
    "ticket_events": {
        "script": "ticket_event_validator.py",
        "report": "ticket_event_validation_report.json",
        "dataset": "ticket_events.csv",
    },
    "ground_truth": {
        "script": "ground_truth_validator.py",
        "report": "ground_truth_validation_report.json",
        "dataset": "ground_truth.csv",
    },
    "anomalies": {
        "script": "anomaly_validator.py",
        "report": "anomaly_validation_report.json",
        "dataset": "anomalies.csv",
    },
}


def read_json(path):
    """Return parsed JSON, or None when the report is missing or invalid."""
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def normalize_report(report):
    """Normalize status and check counts from different validator formats."""
    if not isinstance(report, dict):
        return {
            "status": "FAIL",
            "checks_total": 0,
            "checks_passed": 0,
            "checks_failed": 1,
            "errors": ["Validation report is missing or unreadable."],
        }

    checks = report.get("checks", [])
    if not isinstance(checks, list):
        checks = []

    check_statuses = [
        str(item.get("status", "")).strip().upper()
        for item in checks
        if isinstance(item, dict)
    ]

    counted_passed = sum(
        status in {"PASS", "PASSED"} for status in check_statuses
    )
    counted_failed = sum(
        status in {"FAIL", "FAILED", "ERROR"} for status in check_statuses
    )

    passed_value = report.get(
        "checks_passed", report.get("passed_checks")
    )
    failed_value = report.get(
        "checks_failed", report.get("failed_checks")
    )
    total_value = report.get(
        "checks_total", report.get("total_checks")
    )

    passed = counted_passed if passed_value is None else int(passed_value)
    failed = counted_failed if failed_value is None else int(failed_value)
    total = len(checks) if total_value is None else int(total_value)

    raw_status = str(
        report.get("overall_status")
        or report.get("status")
        or report.get("validation_status")
        or ""
    ).strip().upper()

    if raw_status in {"PASS", "PASSED", "SUCCESS"} and failed == 0:
        status = "PASS"
    elif raw_status in {"FAIL", "FAILED", "ERROR"} or failed > 0:
        status = "FAIL"
    else:
        status = "UNKNOWN"

    errors = report.get("errors", [])
    if not isinstance(errors, list):
        errors = [str(errors)]

    # Detect contradictory reports rather than silently accepting them.
    if passed + failed > total:
        status = "FAIL"
        errors.append(
            f"Inconsistent check counts: {passed} passed + "
            f"{failed} failed exceeds {total} total."
        )

    return {
        "status": status,
        "checks_total": total,
        "checks_passed": passed,
        "checks_failed": failed,
        "errors": errors,
    }


def count_dataset_records(dataset_name):
    """Count CSV records without modifying the dataset."""
    path = DATA_DIR / dataset_name

    if not path.exists():
        return None, f"Dataset missing: {dataset_name}"

    try:
        return len(pd.read_csv(path)), None
    except Exception as exc:
        return None, f"Unable to read {dataset_name}: {exc}"


def run_validator(name, config):
    """Execute a validator and collect its report and dataset count."""
    script_path = VALIDATOR_DIR / config["script"]
    report_path = REPORT_DIR / config["report"]

    record_count, dataset_error = count_dataset_records(config["dataset"])

    if not script_path.exists():
        return {
            "status": "MISSING",
            "script": str(script_path.relative_to(ROOT)),
            "report": str(report_path.relative_to(ROOT)),
            "dataset": config["dataset"],
            "record_count": record_count,
            "checks_total": 0,
            "checks_passed": 0,
            "checks_failed": 0,
            "error_count": 1 + int(dataset_error is not None),
            "errors": [
                f"Validator script missing: {config['script']}"
            ] + ([dataset_error] if dataset_error else []),
        }

    try:
        process = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "FAIL",
            "script": str(script_path.relative_to(ROOT)),
            "report": str(report_path.relative_to(ROOT)),
            "dataset": config["dataset"],
            "record_count": record_count,
            "checks_total": 0,
            "checks_passed": 0,
            "checks_failed": 1,
            "error_count": 1,
            "errors": ["Validator timed out after 180 seconds."],
        }

    report = read_json(report_path)
    normalized = normalize_report(report)
    errors = list(normalized["errors"])

    if process.returncode != 0:
        errors.append(
            f"Validator process exited with code {process.returncode}."
        )
        if normalized["status"] == "PASS":
            normalized["status"] = "FAIL"
            normalized["checks_failed"] += 1

    if report is None:
        normalized["status"] = "FAIL"
        if normalized["checks_failed"] == 0:
            normalized["checks_failed"] = 1
        errors.append("No readable validation report was produced.")

    if dataset_error:
        errors.append(dataset_error)
        normalized["status"] = "FAIL"

    return {
        "status": normalized["status"],
        "script": str(script_path.relative_to(ROOT)),
        "report": str(report_path.relative_to(ROOT)),
        "dataset": config["dataset"],
        "record_count": record_count,
        "checks_total": normalized["checks_total"],
        "checks_passed": normalized["checks_passed"],
        "checks_failed": normalized["checks_failed"],
        "error_count": len(errors),
        "errors": errors,
        "process_exit_code": process.returncode,
        "stderr": process.stderr.strip()[-2000:],
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    results = {}

    for name, config in VALIDATORS.items():
        print(f"Running validator: {name}")
        results[name] = run_validator(name, config)
        print(f"  Status: {results[name]['status']}")

    statuses = [result["status"] for result in results.values()]

    overall_status = (
        "PASS"
        if len(statuses) == len(VALIDATORS)
        and all(status == "PASS" for status in statuses)
        else "FAIL"
    )

    record_counts = {
        name: result["record_count"]
        for name, result in results.items()
    }

    check_counts = {
        "checks_total": sum(
            result["checks_total"] for result in results.values()
        ),
        "checks_passed": sum(
            result["checks_passed"] for result in results.values()
        ),
        "checks_failed": sum(
            result["checks_failed"] for result in results.values()
        ),
    }

    report = {
        "framework": "HR Service System Master Validation Framework",
        "overall_status": overall_status,
        "validator_count": len(results),
        "validators_passed": sum(
            status == "PASS" for status in statuses
        ),
        "validators_failed": sum(
            status == "FAIL" for status in statuses
        ),
        "validators_missing": sum(
            status == "MISSING" for status in statuses
        ),
        "validators_unknown": sum(
            status == "UNKNOWN" for status in statuses
        ),
        "record_counts": record_counts,
        "total_records_counted": sum(
            count for count in record_counts.values()
            if isinstance(count, int)
        ),
        "validation_counts": check_counts,
        "error_count": sum(
            result["error_count"] for result in results.values()
        ),
        "validators": results,
    }

    MASTER_REPORT.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\n=== MASTER VALIDATION SUMMARY ===")
    print(f"Overall status: {overall_status}")
    print(
        f"Validators passed: "
        f"{report['validators_passed']}/{len(results)}"
    )
    print(f"Validators failed: {report['validators_failed']}")
    print(f"Validators missing: {report['validators_missing']}")
    print(f"Validation checks: {check_counts}")
    print(f"Errors: {report['error_count']}")
    print(f"Report saved: {MASTER_REPORT}")

    if overall_status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
