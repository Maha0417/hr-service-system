import pandas as pd

from src.workflow_engine import evaluate_ticket

categories = (
    pd.read_csv("data/csv/categories.csv")
    .set_index("category_id")["category_name"]
    .to_dict()
)

tickets = pd.read_csv(
    "data/csv/tickets.csv",
    dtype=str
).fillna("")

results = []
errors = []

for _, row in tickets.iterrows():
    ticket = {
        "ticket_id": row["ticket_id"],
        "category_name": categories[row["category_id"]],
        "scenario_type": row["scenario_type"],
        "sensitive_flag": row["sensitive_flag"],
        "lifecycle_state": row["ticket_status"],
    }

    try:
        results.append(evaluate_ticket(ticket))
    except Exception as exc:
        errors.append((row["ticket_id"], str(exc)))

print("Tickets in dataset:", len(tickets))
print("Tickets evaluated:", len(results))
print("Errors:", len(errors))

if results:
    print("\nRouting counts:")
    print(pd.Series(
        [item["assigned_group"] for item in results]
    ).value_counts().to_string())

    print("\nClarification decisions:",
          sum(item["requires_clarification"] for item in results))

    print("\nRecommended states:")
    print(pd.Series(
        [item["recommended_state"] for item in results]
    ).value_counts().to_string())

if errors:
    print("\nFirst five errors:")
    print(errors[:5])