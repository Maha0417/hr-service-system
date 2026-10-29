from pathlib import Path

p = Path("README.md")
s = p.read_text(encoding="utf-8-sig")

old_count = "- Ticket events: 19,000"
assert s.count(old_count) == 1, "Expected one outdated event count; no changes made."

s = s.replace(old_count, "- Ticket events: 29,000", 1)

old_limit = "- The ticket event dataset contains 19,000 events. Its alignment with the two newly added message types must be evaluated separately before claiming complete message-to-event traceability."
new_limit = "- The ticket event history contains 29,000 events across 5,000 tickets. All 23,000 messages have unique event references, with no missing or duplicate message references found in the explicit traceability check."

assert s.count(old_limit) == 1, "Expected old traceability note not found; no changes made."
s = s.replace(old_limit, new_limit, 1)

old_intro = "routine HR requests,apply versioned policy sources"
if old_intro in s:
    s = s.replace(old_intro, "routine HR requests, apply versioned policy sources", 1)

p.write_text(s, encoding="utf-8")
print("README updated successfully.")
print("Event count updated to 29,000.")
print("Traceability note updated.")
