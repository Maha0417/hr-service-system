"""Process an HR ticket through the deterministic workflow and record its decisions."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.logger import get_logger
from src.policy_lookup import lookup_policy
from src.workflow_engine import evaluate_ticket, decide_escalation


logger = get_logger(__name__)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "csv"
RUNTIME_DIR = ROOT / "data" / "runtime"
OUTPUT_FILE = RUNTIME_DIR / "processed_requests.jsonl"


def load_csv(filename):
    path = DATA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset is missing: {path}")
    return pd.read_csv(path, dtype=str).fillna("")


def process_ticket(ticket_id):
    tickets = load_csv("tickets.csv")
    categories = load_csv("categories.csv")

    ticket_matches = tickets[tickets["ticket_id"] == ticket_id]
    if len(ticket_matches) != 1:
        raise ValueError(
            f"Expected exactly one ticket for {ticket_id}; "
            f"found {len(ticket_matches)}"
        )

    ticket = ticket_matches.iloc[0].to_dict()

    category_matches = categories[
        categories["category_id"] == ticket["category_id"]
    ]
    if len(category_matches) != 1:
        raise ValueError(
            f"Could not uniquely resolve category {ticket['category_id']}"
        )

    category_name = category_matches.iloc[0]["category_name"]
    scenario = ticket["scenario_type"].strip().upper()

    # Confidential cases must be handled as sensitive, regardless of category.
    sensitive = (
        str(ticket.get("sensitive_flag", "N")).strip().upper()
        in {"Y", "TRUE", "YES", "1"}
        or scenario == "CONFIDENTIAL"
    )

    operational_state = str(ticket.get("ticket_status", "OPEN")).upper()
    decision = evaluate_ticket({
        "ticket_id": ticket_id,
        "category_name": category_name,
        "scenario_type": scenario,
        "sensitive_flag": "Y" if sensitive else "N",
        "lifecycle_state": operational_state,
    })

    # Validate the ticket timestamp before selecting its applicable policy version.
    created = pd.to_datetime(ticket["created_timestamp"], errors="coerce", utc=True)
    if pd.isna(created):
        raise ValueError(f"Ticket {ticket_id} has no valid creation timestamp")

    policy = lookup_policy(
        ticket["policy_id"],
        as_of_date=created,
    )

    now = datetime.now(timezone.utc)
    elapsed_hours = max(
        0.0, (now - created.to_pydatetime()).total_seconds() / 3600
    )
    sla_decision = decide_escalation(decision["priority"], elapsed_hours)

    # Preserve the original routing decision and record any SLA reassignment.
    decision["original_assigned_group"] = decision["assigned_group"]
    decision["sla_escalation_destination"] = None

    if sla_decision["should_escalate"]:
        decision["assigned_group"] = "HR_PARTNER"
        decision["sla_escalation_destination"] = "HR_PARTNER"
        decision["routing_reason"] = (
            decision["routing_reason"] + "|SLA_ESCALATION"
        )

    # Preserve source datasets. Runtime processing is stored separately.
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open("r", encoding="utf-8") as existing:
            for line in existing:
                if line.strip() and json.loads(line).get("ticket_id") == ticket_id:
                    raise ValueError(
                        f"Ticket {ticket_id} was already processed. "
                        "Existing runtime history was preserved."
                    )

    processed_at = now.isoformat()
    messages = []
    events = []
    sequence = 0

    def add_message(sender, message_type, content, state):
        nonlocal sequence
        sequence += 1
        message_id = f"RMSG-{ticket_id}-{sequence:03d}"
        sent_at = ""

        message = {
            "message_id": message_id,
            "ticket_id": ticket_id,
            "sender_type": sender,
            "message_type": message_type,
            "sent_timestamp": sent_at,
            "message_content": content,
            "lifecycle_state": state,
            "policy_version_id": (
                policy["version_id"] if message_type == "POLICY_RESPONSE"
                and not sensitive else ""
            ),
        }
        messages.append(message)
        event = {
            "event_id": f"REVT-{ticket_id}-{sequence:03d}",
            "ticket_id": ticket_id,
            "event_type": message_type,
            "event_timestamp": sent_at,
            "message_id": message_id,
            "state": state,
        }
        if message_type == "SLA_ESCALATION":
            event["assigned_group"] = "HR_PARTNER"
            event["reason"] = sla_decision["reason"]
        events.append(event)

    add_message(
        "EMPLOYEE",
        "INITIAL_REQUEST",
        str(ticket["ticket_subject"]) + ". " + str(ticket["ticket_description"]),
        "OPEN",
    )

    if sensitive:
        add_message(
            "SYSTEM",
            "ESCALATION_NOTICE",
            "Sensitive case routed to HR_PARTNER for confidential handling.",
            "IN_PROGRESS",
        )
        add_message(
            "HR_PARTNER",
            "CONFIDENTIAL_ACKNOWLEDGEMENT",
            "Your confidential request has been received by the HR Partner. "
            "It remains in progress and will be handled through the "
            "appropriate confidential process.",
            "IN_PROGRESS",
        )
    elif decision["requires_clarification"]:
        add_message(
            "HR_AGENT",
            "CLARIFICATION_REQUEST",
            "Additional details are required before this request "
            "can be processed accurately. The ticket is waiting "
            "for the employee's response.",
            "WAITING_FOR_INFO",
        )
    else:
        add_message(
            "HR_AGENT",
            "POLICY_RESPONSE",
            f"Guidance for {ticket['ticket_subject']}: "
            f"{policy['article_title']}. "
            f"Current policy citation: {policy['citation']}",
            "IN_PROGRESS",
        )
    if sla_decision["should_escalate"]:
        add_message(
            "SYSTEM",
            "SLA_ESCALATION",
            (
                f"SLA threshold exceeded: {sla_decision['elapsed_hours']:.2f} "
                f"hours elapsed against a {sla_decision['threshold_hours']}-hour "
                f"threshold. Escalation assigned to HR_PARTNER."
            ),
            decision["recommended_state"],
        )

    # Assign chronological timestamps after the complete message flow is known.
    message_count = len(messages)
    first_message_at = now - timedelta(minutes=max(message_count - 1, 0))

    for index, message in enumerate(messages):
        sent_at = (first_message_at + timedelta(minutes=index)).isoformat()
        message["sent_timestamp"] = sent_at

    event_times = {
        message["message_id"]: message["sent_timestamp"]
        for message in messages
    }
    for event in events:
        message_id = event.get("message_id")
        if message_id in event_times:
            event["event_timestamp"] = event_times[message_id]

    events.append({
        "event_id": f"REVT-{ticket_id}-DECISION",
        "ticket_id": ticket_id,
        "event_type": "WORKFLOW_DECISION_RECORDED",
        "event_timestamp": processed_at,
        "message_id": "",
        "state": decision["recommended_state"],
    })

    record = {
        "ticket_id": ticket_id,
        "processed_at": processed_at,
        "scenario_type": scenario,
        "category_name": category_name,
        "decision": decision,
        "policy": policy,
        "sla": sla_decision,
        "messages": messages,
        "events": events,
        "record_status": "PROCESSED",
    }

    from src.runtime_store import (
        initialize_runtime_store,
        save_processed_record,
    )

    initialize_runtime_store()
    save_processed_record(record)

    with OUTPUT_FILE.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Ticket processed: {ticket_id}")
    print(f"Category: {category_name}")
    print(f"Assigned group: {decision['assigned_group']}")
    print(f"Priority: {decision['priority']}")
    print(f"Clarification required: {decision['requires_clarification']}")
    print(f"Current policy version: {policy['version_id']}")
    print(f"SLA escalation required: {sla_decision['should_escalate']}")
    print(f"Messages recorded: {len(messages)}")
    print(f"Events recorded: {len(events)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m src.request_processor TICKET-ID")
        raise SystemExit(2)

    try:
        process_ticket(sys.argv[1])
    except Exception:
        logger.exception(
            "Ticket processing failed for ticket ID: %s",
            sys.argv[1],
        )
        raise