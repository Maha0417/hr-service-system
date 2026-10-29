import pandas as pd

from src.workflow_engine import evaluate_ticket

categories = pd.read_csv("data/csv/categories.csv")
tickets = pd.read_csv("data/csv/tickets.csv", dtype=str).fillna("")
ground_truth = pd.read_csv("data/csv/ground_truth.csv", dtype=str).fillna("")

category_map = categories.set_index("category_id")["category_name"].to_dict()
tickets["category_name"] = tickets["category_id"].map(category_map)

data = tickets.merge(
    ground_truth[["entity_id", "expected_route", "expected_clarification"]],
    left_on="ticket_id",
    right_on="entity_id",
    how="left",
    validate="one_to_one",
)

route_mismatches = []
clarification_mismatches = []

for _, row in data.iterrows():
    decision = evaluate_ticket({
        "ticket_id": row["ticket_id"],
        "category_name": row["category_name"],
        "scenario_type": row["scenario_type"],
        "sensitive_flag": row["sensitive_flag"],
        "lifecycle_state": row["ticket_status"],
    })

    if decision["assigned_group"] != row["expected_route"]:
        route_mismatches.append(row["ticket_id"])

    expected = str(row["expected_clarification"]).strip().lower() == "true"
    if decision["requires_clarification"] != expected:
        clarification_mismatches.append(row["ticket_id"])

print("Tickets compared:", len(data))
print("Missing ground-truth records:", int(data["entity_id"].eq("").sum()))
print("Route mismatches:", len(route_mismatches))
print("Clarification mismatches:", len(clarification_mismatches))
print("First route mismatches:", route_mismatches[:10])
print("First clarification mismatches:", clarification_mismatches[:10])
