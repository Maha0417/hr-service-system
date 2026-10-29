from pathlib import Path
import shutil

p = Path("src/ticket_event_generator.py")
s = p.read_text(encoding="utf-8")

backup = Path("src/ticket_event_generator.py.pre_traceability_fix.bak")
if backup.exists():
    raise FileExistsError(f"Backup already exists: {backup}")

old_creation = '''        add_event(
            ticket_id,
            ticket["created_timestamp"],
            "",
            "OPEN",
            "TICKET_CREATED",
            "Ticket created in the source ticket dataset.",
            "tickets.csv",
        )'''

new_creation = '''        initial_message = next(
            (
                message
                for message in message_groups.get(ticket_id, [])
                if message["message_type"] == "INITIAL_REQUEST"
            ),
            None,
        )

        add_event(
            ticket_id,
            ticket["created_timestamp"],
            "",
            "OPEN",
            "TICKET_CREATED",
            "Ticket created in the source ticket dataset.",
            "tickets.csv",
            message_id=initial_message["message_id"] if initial_message else "",
        )'''

old_resolution = '''                resolution_messages = [
                    message
                    for message in message_groups.get(ticket_id, [])
                    if message["message_type"] == "RESOLUTION_MESSAGE"
                ]

                related_message_id = (
                    resolution_messages[-1]["message_id"]
                    if resolution_messages
                    else ""
                )

                add_event(
                    ticket_id,
                    timestamp,
                    current_state,
                    "RESOLVED",
                    "TICKET_RESOLVED",
                    "Resolution recorded in resolutions.csv.",
                    "resolutions.csv",
                    message_id=related_message_id,
                )'''

new_resolution = '''                add_event(
                    ticket_id,
                    timestamp,
                    current_state,
                    "RESOLVED",
                    "TICKET_RESOLVED",
                    "Resolution recorded in resolutions.csv.",
                    "resolutions.csv",
                )'''

if s.count(old_creation) != 1:
    raise ValueError("Expected exactly one ticket-creation block; no changes made.")
if s.count(old_resolution) != 1:
    raise ValueError("Expected exactly one resolution block; no changes made.")

shutil.copy2(p, backup)
s = s.replace(old_creation, new_creation, 1)
s = s.replace(old_resolution, new_resolution, 1)
p.write_text(s, encoding="utf-8")

print("Patch applied successfully.")
print(f"Backup created: {backup}")
print("Ticket creation events now link initial requests.")
print("Resolution events no longer duplicate resolution-message links.")
