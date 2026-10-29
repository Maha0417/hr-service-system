from pathlib import Path
import pandas as pd

DATA = Path("data/csv")
messages_path = DATA / "messages.csv"
tickets_path = DATA / "tickets.csv"
output_path = DATA / "messages_expanded.csv"

messages = pd.read_csv(messages_path, dtype=str).fillna("")
tickets = pd.read_csv(tickets_path, dtype=str).fillna("")

if output_path.exists():
    raise FileExistsError(
        f"{output_path} already exists; refusing to overwrite it."
    )

required_messages = {
    "message_id", "ticket_id", "sender_type", "message_type",
    "policy_version_id", "sent_timestamp", "message_content",
    "lifecycle_state",
}
if not required_messages.issubset(messages.columns):
    raise ValueError("messages.csv is missing required columns")

if messages["message_id"].duplicated().any():
    raise ValueError("Existing message IDs are not unique")

if set(messages["ticket_id"]) - set(tickets["ticket_id"]):
    raise ValueError("Existing messages reference unknown tickets")

ticket_lookup = tickets.set_index("ticket_id").to_dict("index")
extra = []

for ticket_id, group in messages.groupby("ticket_id", sort=False):
    ticket = ticket_lookup[ticket_id]
    scenario = ticket["scenario_type"].strip().upper()
    subject = str(ticket["ticket_subject"]).strip()
    sender = "HR_PARTNER" if scenario == "CONFIDENTIAL" else "HR_AGENT"

    latest = group.copy()
    latest["_parsed_time"] = pd.to_datetime(
        latest["sent_timestamp"], errors="raise"
    )
    last_time = latest["_parsed_time"].max()
    next_sequence = len(group) + 1

    if scenario == "CONFIDENTIAL":
        update_text = (
            f"Confidential case update for {subject}: "
            "the HR Partner is reviewing the request through the "
            "appropriate confidential process."
        )
        acknowledgement_text = (
            "Thank you for the update. I understand that my request "
            "is being handled through the confidential HR process."
        )
    elif scenario == "OUTDATED_POLICY":
        update_text = (
            f"Progress update for {subject}: the request is being "
            "reviewed against the current approved policy version."
        )
        acknowledgement_text = (
            "Thank you for confirming that the current approved policy "
            "will be used for my request."
        )
    elif scenario in {"AMBIGUOUS", "MISSING_CONTEXT"}:
        update_text = (
            f"Progress update for {subject}: the submitted details "
            "have been reviewed and the request is being processed."
        )
        acknowledgement_text = (
            "Thank you for the update. I understand the next steps "
            "for my request."
        )
    else:
        update_text = (
            f"Progress update for {subject}: the HR team is processing "
            "the request under the applicable policy."
        )
        acknowledgement_text = (
            "Thank you for the update. I understand the current status "
            "and next steps for my request."
        )

    for offset, (sender_type, message_type, content) in enumerate([
        (sender, "STATUS_UPDATE", update_text),
        ("EMPLOYEE", "EMPLOYEE_ACKNOWLEDGEMENT", acknowledgement_text),
    ], start=1):
        sent = last_time + pd.Timedelta(minutes=5 * offset)
        extra.append({
            "message_id": f"MSG-{ticket_id}-{next_sequence + offset - 1:03d}",
            "ticket_id": ticket_id,
            "sender_type": sender_type,
            "message_type": message_type,
            "policy_version_id": "",
            "sent_timestamp": sent.isoformat(),
            "message_content": content,
            "lifecycle_state": "IN_PROGRESS",
        })

expanded = pd.concat(
    [messages, pd.DataFrame(extra, columns=messages.columns)],
    ignore_index=True,
)

if expanded["message_id"].duplicated().any():
    raise ValueError("Expanded dataset contains duplicate message IDs")

if expanded["message_content"].str.strip().eq("").any():
    raise ValueError("Expanded dataset contains blank message content")

if not set(expanded["ticket_id"]).issubset(set(tickets["ticket_id"])):
    raise ValueError("Expanded dataset contains invalid ticket references")

expanded.to_csv(output_path, index=False)

print(f"Original messages: {len(messages)}")
print(f"Additional messages: {len(extra)}")
print(f"Expanded messages: {len(expanded)}")
print(f"Unique message IDs: {expanded['message_id'].nunique()}")
print(f"Tickets covered: {expanded['ticket_id'].nunique()}")
print(f"Expanded file: {output_path}")
