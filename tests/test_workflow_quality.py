import pandas as pd

categories = pd.read_csv("data/csv/categories.csv")
tickets = pd.read_csv("data/csv/tickets.csv", dtype=str).fillna("")
assignments = pd.read_csv(
    "data/csv/assignments.csv", dtype=str
).fillna("")

category_map = categories.set_index("category_id")["category_name"].to_dict()

tickets["category_name"] = tickets["category_id"].map(category_map)

initial = assignments[
    assignments["assignment_reason"] == "INITIAL_ROUTING"
].drop_duplicates("ticket_id", keep="first")

data = tickets.merge(
    initial[["ticket_id", "assigned_group"]],
    on="ticket_id",
    how="left",
    validate="one_to_one",
)

sensitive = data["sensitive_flag"].str.upper().isin(["Y", "TRUE", "1"])
confidential = data["scenario_type"].str.upper().eq("CONFIDENTIAL")
must_reach_hr = sensitive | confidential

print("Tickets:", len(data))
print("Tickets missing initial assignment:", data["assigned_group"].eq("").sum())
print("Sensitive/confidential tickets:", int(must_reach_hr.sum()))
print(
    "Sensitive/confidential tickets outside HR_PARTNER:",
    int((must_reach_hr & data["assigned_group"].ne("HR_PARTNER")).sum()),
)
print(
    "Employee Relations tickets outside HR_PARTNER:",
    int(
        (
            data["category_name"].eq("Employee Relations")
            & data["assigned_group"].ne("HR_PARTNER")
        ).sum()
    ),
)
print("\nInitial assignment counts:")
print(data["assigned_group"].value_counts(dropna=False).to_string())