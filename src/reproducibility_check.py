
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SEED = 20261022
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = (
    PROJECT_ROOT
    / "output"
    / "reproducibility"
    / "reproducibility_report.json"
)

DATASETS = [
    "departments.csv",
    "employees.csv",
    "categories.csv",
    "policy_documents.csv",
    "policy_versions.csv",
    "knowledge_articles.csv",
    "tickets.csv",
    "messages.csv",
    "assignments.csv",
    "sla_records.csv",
    "resolutions.csv",
    "ticket_events.csv",
    "ground_truth.csv",
    "anomalies.csv",
]

GENERATION_PIPELINE = [
    "master_data.py",
    "category_generator.py",
    "employee_generator.py",
    "policy_generator.py",
    "policy_version_generator.py",
    "knowledge_article_generator.py",
    "ticket_generator.py",
    "message_generator.py",
    "assignment_generator.py",
    "sla_generator.py",
    "resolution_generator.py",
    "ticket_event_generator.py",
    "ground_truth_generator.py",
    "anomaly_injector.py",
]


def create_seed_initializer(workspace):
    """Set consistent seeds for each generator process."""

    initializer = """
import random
random.seed(20261022)

try:
    import numpy as np
    np.random.seed(20261022)
except ImportError:
    pass

try:
    from faker import Faker
    Faker.seed(20261022)
except ImportError:
    pass
"""
    (workspace / "sitecustomize.py").write_text(
        initializer.strip() + "\n",
        encoding="utf-8",
    )


def prepare_workspace(workspace):
    """Copy source code only; never copy or modify live CSVs."""

    shutil.copytree(
        PROJECT_ROOT / "src",
        workspace / "src",
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
        ),
    )

    data_dir = workspace / "data" / "csv"
    data_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # The assignment generator appends rows without writing a header.
    # Seed each isolated workspace with the required header-only file.
    assignment_columns = [
        "assignment_id",
        "ticket_id",
        "assigned_group",
        "assigned_to",
        "assignment_reason",
        "assigned_timestamp",
        "assignment_status",
        "previous_assignment_id",
    ]

    (data_dir / "assignments.csv").write_text(
        ",".join(assignment_columns) + "\n",
        encoding="utf-8",
    )

    create_seed_initializer(workspace)


def run_pipeline(workspace, run_number):
    """Execute the full pipeline in an isolated workspace."""

    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")

    environment["PYTHONPATH"] = (
        str(workspace)
        + (
            os.pathsep + existing_pythonpath
            if existing_pythonpath
            else ""
        )
    )
    environment["PYTHONHASHSEED"] = str(SEED)
    environment["PYTHONUTF8"] = "1"

    result = {
        "run": run_number,
        "seed": SEED,
        "success": False,
        "completed_generators": [],
        "failed_generator": None,
        "error": None,
    }

    for generator in GENERATION_PIPELINE:
        script_path = workspace / "src" / generator

        try:
            process = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except Exception as error:
            result["failed_generator"] = generator
            result["error"] = str(error)
            return result

        if process.returncode != 0:
            result["failed_generator"] = generator
            result["error"] = (
                f"Exit code: {process.returncode}\n"
                f"STDOUT:\n{process.stdout[-4000:]}\n"
                f"STDERR:\n{process.stderr[-4000:]}"
            )
            return result

        result["completed_generators"].append(generator)

    result["success"] = True
    return result


def inspect_dataset(workspace, filename):
    """Return the CSV record count and MD5 checksum."""

    path = workspace / "data" / "csv" / filename

    if not path.is_file():
        return {
            "row_count": None,
            "md5": None,
            "error": "CSV file was not generated",
        }

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            row_count = max(
                sum(1 for _ in csv.reader(file)) - 1,
                0,
            )

        digest = hashlib.md5()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return {
            "row_count": row_count,
            "md5": digest.hexdigest(),
            "error": None,
        }

    except Exception as error:
        return {
            "row_count": None,
            "md5": None,
            "error": str(error),
        }


def main():
    print("=" * 65)
    print("HR SERVICE SYSTEM - REPRODUCIBILITY CHECK")
    print(f"Seed: {SEED}")
    print("Running two isolated generation pipelines...")
    print("=" * 65)

    run_results = []
    dataset_snapshots = []

    with tempfile.TemporaryDirectory(
        prefix="hr_reproducibility_"
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)

        for run_number in (1, 2):
            workspace = temporary_root / f"run_{run_number}"
            workspace.mkdir(parents=True)

            prepare_workspace(workspace)

            print(f"\nStarting independent run {run_number}...")
            result = run_pipeline(workspace, run_number)
            run_results.append(result)

            for generator in result["completed_generators"]:
                print(f"  PASS: {generator}")

            if not result["success"]:
                print(
                    f"  FAIL: {result['failed_generator']}"
                )
                print(result["error"])

            snapshot = {
                filename: inspect_dataset(workspace, filename)
                for filename in DATASETS
            }
            dataset_snapshots.append(snapshot)

            print(
                f"Run {run_number} pipeline: "
                f"{'PASS' if result['success'] else 'FAIL'}"
            )

        dataset_results = {}
        for filename in DATASETS:
            first = dataset_snapshots[0][filename]
            second = dataset_snapshots[1][filename]

            row_counts_match = (
                first["row_count"] is not None
                and second["row_count"] is not None
                and first["row_count"] == second["row_count"]
            )

            checksums_match = (
                first["md5"] is not None
                and second["md5"] is not None
                and first["md5"] == second["md5"]
            )

            dataset_results[filename] = {
                "run_1": first,
                "run_2": second,
                "row_counts_match": row_counts_match,
                "checksums_match": checksums_match,
                "reproducible": (
                    row_counts_match and checksums_match
                ),
            }

    all_row_counts_match = all(
        item["row_counts_match"]
        for item in dataset_results.values()
    )

    all_checksums_match = all(
        item["checksums_match"]
        for item in dataset_results.values()
    )

    all_runs_succeeded = all(
        item["success"] for item in run_results
    )

    report = {
        "seed": SEED,
        "datasets_checked": len(DATASETS),
        "generation_pipeline": GENERATION_PIPELINE,
        "run_1_success": run_results[0]["success"],
        "run_2_success": run_results[1]["success"],
        "runs": run_results,
        "row_counts_match": all_row_counts_match,
        "checksums_match": all_checksums_match,
        "reproducible": (
            all_runs_succeeded
            and all_row_counts_match
            and all_checksums_match
        ),
        "datasets": dataset_results,
    }

    REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    REPORT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 65)
    print("REPRODUCIBILITY SUMMARY")
    print(f"Datasets checked: {len(DATASETS)}")
    print(f"Run 1 succeeded: {report['run_1_success']}")
    print(f"Run 2 succeeded: {report['run_2_success']}")
    print(f"Row counts match: {report['row_counts_match']}")
    print(f"MD5 checksums match: {report['checksums_match']}")
    print(f"Reproducible: {report['reproducible']}")
    print(f"Report: {REPORT_PATH}")
    print("=" * 65)

    for filename, result in dataset_results.items():
        status = (
            "PASS"
            if result["reproducible"]
            else "FAIL"
        )
        print(
            f"{status}: {filename} | "
            f"rows: {result['run_1']['row_count']} / "
            f"{result['run_2']['row_count']}"
        )

    if not report["reproducible"]:
        print(
            "\nReproducibility check did not pass. "
            "Inspect the report for pipeline errors or differences."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
