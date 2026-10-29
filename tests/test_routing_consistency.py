import pandas as pd

from src.workflow_engine import evaluate_ticket

categories = pd.read_csv("data/csv/categories.csv")
tickets = pd.read_csv("data/csv/tickets.csv", dtype=str).fillna("")
assignments = pd.read_csv("data/csv/assignments.csv", dtype=str).fillna("")

category_map = categories.set_index("category_id")["category_name"].to_dict()
tickets["category_name"] = tickets["category_id"].map(category_map)

initial = assignments[
    assignments["assignment_reason"].eq("INITIAL_ROUTING")
].drop_duplicates("ticket_id", keep="first")

data = tickets.merge(
    initial[["ticket_id", "assigned_group"]],
    on="ticket_id",
    how="left",
    validate="one_to_one",
)

mismatches = []

for _, row in data.iterrows():
    decision = evaluate_ticket({
        "ticket_id": row["ticket_id"],
        "category_name": row["category_name"],
        "scenario_type": row["scenario_type"],
        "sensitive_flag": row["sensitive_flag"],
        "lifecycle_state": row["ticket_status"],
    })

    if decision["assigned_group"] != row["assigned_group"]:
        mismatches.append({
            "ticket_id": row["ticket_id"],
            "category": row["category_name"],
            "sensitive_flag": row["sensitive_flag"],
            "engine_route": decision["assigned_group"],
            "stored_route": row["assigned_group"],
        })

print("Tickets compared:", len(data))
print("Routing mismatches:", len(mismatches))
print("First 10 mismatches:")
for item in mismatches[:10]:
    print(item)
