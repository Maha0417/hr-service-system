# HR Service System

A data-driven workflow project that handles routine HR requests, applies versioned policy sources, routes sensitive cases correctly, tracks SLAs, and keeps a complete, traceable ticket history.

This repository contains the full-mode dataset used for validation and evaluation.

---

## 1. What This Project Does

The system takes an HR ticket and processes it step by step:

- Reads the request and finds the right policy version and knowledge article
- Asks for clarification when the request is unclear or incomplete
- Routes confidential cases to the right person (HR Partner) instead of the general queue
- Assigns the ticket, tracks the SLA, and escalates when needed
- Records every message, assignment, event and resolution for full traceability

Everything is built on generated datasets, so the whole flow can be checked and reproduced.

---

## 2. Dataset Scale

| Item | Count |
|---|---:|
| Employees | 1,000 |
| Departments | 10 |
| Categories | 5 |
| Policy documents | 50 |
| Policy versions | 150 |
| Knowledge articles | 150 |
| Tickets | 5,000 |
| Messages | 23,000 |
| Assignments | 5,500 |
| SLA records | 5,000 |
| Resolution records | 5,000 |
| Ticket events | 29,000 |
| Ground-truth records | 5,000 |
| Labelled anomaly/evaluation records | 200 |

---

## 3. Ticket Scenarios

| Scenario | Tickets | What it represents |
|---|---:|---|
| NORMAL | 3,000 | Routine requests |
| AMBIGUOUS | 500 | Requests that need clarification |
| MISSING_CONTEXT | 500 | Requests with important details missing |
| CONFIDENTIAL | 500 | Sensitive requests |
| OUTDATED_POLICY | 500 | Requests referring to old policy information |
| **Total** | **5,000** | |

---

## 4. Messages and Traceability

The 23,000 messages cover initial requests, policy responses, clarification exchanges, escalation notices, resolution messages, status updates and employee acknowledgements.

Scenario-specific handling:

- Confidential follow-up messages are assigned to the **HR Partner** sender type.
- Outdated-policy messages ask to check the **current approved policy version**.

Traceability summary:

- All message IDs are unique and every message points to an existing ticket.
- All 23,000 messages have unique event references. The explicit traceability check found no missing or duplicate references.
- The 29,000 ticket events are spread across the 5,000 tickets.
- Messages were validated for required fields, valid ticket references, sender and message types, non-blank content, lifecycle states, valid timestamps and policy-version references.

---

## 5. Anomaly Evaluation

The file `data/csv/anomalies.csv` has **200 labelled anomaly/evaluation records**, 50 in each category:

- `obsolete_policy_reference`
- `sensitive_case_routed_general_queue`
- `sla_business_hours_error`
- `unsupported_claim`

Each record has an anomaly ID, entity type, entity ID, issue type, expected outcome, actual outcome, severity, and ground-truth reference.

**Please note:** these records are for audit and evaluation. They are **not** 200 confirmed faults in the operational ticket data. An audit outcome can be MATCH, MISMATCH or INCONCLUSIVE, depending on the evidence available to the evaluator.

---

## 6. Folder Layout

```text
data/csv/                            CSV source datasets
data/json/                           JSON exports
data/sql/hr_service_system.sqlite    SQLite database
output/validation/                   Validation reports
output/dataset_export_manifest.json  Export manifest
src/                                 Generators, workflow rules, validators, export utilities
```

The CSV files are the source of truth. The JSON and SQLite exports are created from them.

---

## 7. Architecture

```text
Master and Reference Data
          |
          v
Ticket and Message Datasets
          |
          v
Workflow Rules and Request Processing
          |
          +----> Policy and Knowledge References
          |
          +----> Assignment and SLA Handling
          |
          v
Runtime State and Event History
          |
          v
Validation, Audit, and Export Artifacts
```

This is the high-level workflow. It is not a claim that every component runs as a deployed service.

---

## 8. Challenge Requirement Coverage

| Requirement | Implementation evidence |
|---|---|
| Master and reference data | CSV datasets for employees, departments, categories, policies, versions and knowledge articles |
| Ticket lifecycle | Ticket states and runtime processing |
| Policy traceability | Policy-version and knowledge-article references in response records |
| Sensitive-case routing | Workflow rules and assignment records |
| Clarification handling | Ticket/message workflow and lifecycle states |
| SLA handling | SLA records and escalation events |
| Traceability | Messages, assignments, ticket events and resolution records |
| Validation | Validation reports and automated tests |
| Anomaly evaluation | Labelled anomaly records and audit report |
| Runtime observability | Console/file logging and runtime summary/history commands |

---

## 9. Setup and How to Run

Use Python 3.11 or a compatible version supported by the project dependencies.

From the project root, create and activate a virtual environment.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Then use these commands. `TKT-2026-000008` is only an **example ticket ID**; replace it with any eligible ticket.

```bash
# View the runtime summary
python -m src.main summary

# Process a ticket that is not yet processed in the current runtime store
python -m src.main process TKT-2026-000008

# View the history of a ticket
python -m src.main history TKT-2026-000008

# Run the automated tests
python -m pytest -q
```

**Note:** The example ticket may already be processed in your runtime store. A ticket that is already recorded in the runtime history will be rejected on purpose. This protects the existing state and avoids duplicate processing.

---

## 10. Validation and Export Results

Latest recorded results:

| Check | Result |
|---|---|
| Master validation | PASS |
| Validators passed | 10 / 10 |
| Master checks passed | 115 / 115 |
| Master validation errors | 0 |
| Message validation | PASS (10 / 10 checks) |
| JSON datasets exported | 14 |
| Dataset tables exported to SQLite | 14 |
| CSV-to-SQL row-count verification | PASS |
| Automated tests | 23 passed (latest recorded run) |

The expanded message history was validated independently first, and then included in the passing master validation.

If the datasets or code change, please regenerate and rerun the relevant checks.

---

## 11. Scope and Future Enhancements

This project demonstrates an end-to-end HR Service System workflow built around structured data, policy-driven decision-making, ticket lifecycle management, routing, SLA tracking, and traceable runtime events. The implementation includes generated datasets, validation checks, automated tests, and reproducible local execution steps.

Potential future enhancements include:

- **Expanded validation:** Extend automated tests to cover additional edge cases and combinations of business rules as the workflow evolves.
- **Database integrity:** Strengthen relational constraints and add further integrity checks as the data model grows.
- **Workflow coverage:** Expand end-to-end scenario testing to cover additional policy, clarification, escalation, and resolution paths.
- **Production readiness:** Add deployment-specific security controls, monitoring, operational safeguards, and infrastructure configuration before production use.
---

## 12. AI Usage Disclosure

This project was developed through hands-on implementation, testing, debugging, and iterative refinement. AI tools were used as a supporting resource for troubleshooting, exploring implementation approaches, improving documentation, and reviewing test results. The project structure, workflow implementation, datasets, validation artifacts, and test outcomes are available in the repository for review and verification.

The final implementation and its behavior should be assessed using the source code, generated artifacts, automated tests, and reproducible commands provided in this repository.
