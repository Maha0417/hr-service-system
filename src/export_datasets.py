from pathlib import Path
import json
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = ROOT / "data" / "csv"
JSON_DIR = ROOT / "data" / "json"
SQL_DIR = ROOT / "data" / "sql"
DB_FILE = SQL_DIR / "hr_service_system.sqlite"

DATASETS = [
    "departments",
    "employees",
    "categories",
    "policy_documents",
    "policy_versions",
    "knowledge_articles",
    "tickets",
    "messages",
    "assignments",
    "sla_records",
    "resolutions",
    "ticket_events",
    "ground_truth",
    "anomalies",
]

JSON_DIR.mkdir(parents=True, exist_ok=True)
SQL_DIR.mkdir(parents=True, exist_ok=True)

frames = {}
for name in DATASETS:
    path = CSV_DIR / f"{name}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset missing: {path}")

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    frames[name] = df

    json_path = JSON_DIR / f"{name}.json"
    df.to_json(
        json_path,
        orient="records",
        indent=2,
        force_ascii=False,
    )
    print(f"JSON: {name}.json — {len(df)} records")

if DB_FILE.exists():
    DB_FILE.unlink()

with sqlite3.connect(DB_FILE) as connection:
    for name, df in frames.items():
        df.to_sql(name, connection, if_exists="fail", index=False)

        # Add a primary-key-like unique index only when the ID column
        # is present, nonblank, and unique for that table.
        id_column = f"{name[:-1]}_id" if name.endswith("s") else f"{name}_id"
        candidates = [
            id_column,
            "ticket_id" if name == "tickets" else "",
            "message_id" if name == "messages" else "",
            "assignment_id" if name == "assignments" else "",
            "event_id" if name == "ticket_events" else "",
            "ground_truth_id" if name == "ground_truth" else "",
            "anomaly_id" if name == "anomalies" else "",
            "version_id" if name == "policy_versions" else "",
            "article_id" if name == "knowledge_articles" else "",
            "policy_id" if name == "policy_documents" else "",
            "department_id" if name == "departments" else "",
            "employee_id" if name == "employees" else "",
            "category_id" if name == "categories" else "",
            "resolution_id" if name == "resolutions" else "",
            "sla_id" if name == "sla_records" else "",
        ]
        for column in candidates:
            if (
                column in df.columns
                and df[column].ne("").all()
                and df[column].is_unique
            ):
                connection.execute(
                    f'CREATE UNIQUE INDEX "ux_{name}_{column}" '
                    f'ON "{name}" ("{column}")'
                )
                break

    connection.commit()

with sqlite3.connect(DB_FILE) as connection:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if tables != set(DATASETS):
        raise RuntimeError(f"Unexpected SQLite tables: {sorted(tables)}")

    for name, df in frames.items():
        sql_count = connection.execute(
            f'SELECT COUNT(*) FROM "{name}"'
        ).fetchone()[0]
        if sql_count != len(df):
            raise RuntimeError(
                f"{name}: CSV has {len(df)} rows, SQL has {sql_count}"
            )

manifest = {
    "dataset_count": len(DATASETS),
    "exports": {
        name: {
            "records": len(frames[name]),
            "columns": list(frames[name].columns),
            "json_file": f"data/json/{name}.json",
            "sql_table": name,
        }
        for name in DATASETS
    },
    "sqlite_database": "data/sql/hr_service_system.sqlite",
}

(ROOT / "output" / "dataset_export_manifest.json").write_text(
    json.dumps(manifest, indent=2),
    encoding="utf-8",
)

print("\nEXPORT SUMMARY")
print(f"Datasets exported: {len(DATASETS)}")
print(f"JSON directory: {JSON_DIR}")
print(f"SQLite database: {DB_FILE}")
print(f"Manifest: {ROOT / 'output' / 'dataset_export_manifest.json'}")
print("Row-count verification: PASS")
