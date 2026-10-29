import pandas as pd

from src.policy_lookup import lookup_policy

tickets = pd.read_csv("data/csv/tickets.csv", dtype=str).fillna("")
ground_truth = pd.read_csv("data/csv/ground_truth.csv", dtype=str).fillna("")

data = tickets.merge(
    ground_truth[["entity_id", "expected_policy_version"]],
    left_on="ticket_id",
    right_on="entity_id",
    how="left",
    validate="one_to_one",
)

mismatches = []
errors = []

for _, row in data.iterrows():
    try:
        result = lookup_policy(row["policy_id"])

        if result["version_id"] != row["expected_policy_version"]:
            mismatches.append({
                "ticket_id": row["ticket_id"],
                "policy_id": row["policy_id"],
                "expected": row["expected_policy_version"],
                "actual": result["version_id"],
            })
    except Exception as exc:
        errors.append((row["ticket_id"], str(exc)))

print("Tickets compared:", len(data))
print("Missing ground-truth policy references:", int(data["expected_policy_version"].eq("").sum()))
print("Version mismatches:", len(mismatches))
print("Lookup errors:", len(errors))
print("First mismatches:", mismatches[:5])
print("First errors:", errors[:5])
