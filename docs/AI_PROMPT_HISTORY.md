# AI Prompt History and Development Disclosure

 1. Project Information

Project: HR Service System
Purpose: Build a data-driven HR request management system that applies versioned policies, routes sensitive cases, manages ticket lifecycles and SLAs, and maintains traceable records of decisions and changes.

This document records how AI assistance was used during development. It distinguishes prompts that are directly supported by the available conversation history from reconstructed summaries of development activities. It is not presented as a complete export of every AI conversation.

2. AI Tools Used
The AI tools used during this project were:

- **ChatGPT:** Used for step-by-step implementation guidance, debugging assistance, reviewing test output, organizing development tasks, and improving documentation.
- **Microsoft Copilot:** Used for AI-assisted development support. The specific prompts and contributions from Copilot should be documented from the available conversation history.

**Development period covered:** October 2026.

**Record limitation:** This document includes original prompts that can be verified from the available conversation and reconstructed summaries of development phases. It is not a complete transcript of every interaction with ChatGPT and Microsoft Copilot. Reconstructed summaries are not presented as verbatim prompts.


## 3. Original Prompts Supported by the Available Conversation

The following prompts are preserved as originally phrased in the available conversation.

### Prompt 1 — Understanding the project timeline

> How many days does it take to complete it?

**Purpose:** Understand the expected development timeline for the assigned project.

### Prompt 2 — Beginning implementation

> lets start tell me step by step what to do like help me understand this project better so i can start with implementation

**Purpose:** Begin implementation with a structured, incremental workflow instead of attempting to build the entire system at once.

These are the original prompts that can be directly supported by the available conversation history. The phase summaries in the next section are reconstructed descriptions, not additional verbatim quotations.

## 4. Development Prompt History by Phase

The following entries summarize the kinds of AI assistance used during the corresponding development phases. They are not a complete transcript of the original prompts. The original conversation records should be consulted wherever exact wording is required.

### Phase 1 — Requirements and architecture

**Development objective:** Understand the HR Service System requirements and translate them into an implementable architecture.

**AI assistance:** Help interpret the business context, identify the main entities and actors, organize the implementation sequence, and identify the core workflow requirements.

**Engineering focus:** Establish a data-first design before adding AI-based answering or retrieval functionality.

**Resulting direction:** Build master data and policy reference data first, then dependent records and workflow behavior.

### Phase 2 — Environment and project structure

**Development objective:** Establish the Python project structure and development environment.

**AI assistance:** Provide step-by-step guidance on creating the project directories, setting up a virtual environment, installing dependencies, and organizing source code, data, outputs, and tests.

**Engineering focus:** Keep generated datasets, implementation modules, validation reports, and test code organized and reproducible.

### Phase 3 — Master and reference data generation

**Development objective:** Create the foundational data required by the HR workflow.

**AI assistance:** Provide implementation guidance for Python data generators, data relationships, validation, and reproducible CSV outputs.

**Data entities included:** Departments, employees, categories, policy documents, policy versions, and knowledge articles.

**Recorded project scale:**

- Departments: 10
- Employees: 1,000
- Categories: 5
- Policy documents: 50
- Policy versions: 150
- Knowledge articles: 150

**Engineering focus:** Maintain referential integrity and ensure dependent records refer to valid master and reference records.

### Phase 4 — Dependent records and workflow datasets

**Development objective:** Generate the records needed to represent a functioning HR service workflow.

**AI assistance:** Help structure ticket generation, message generation, assignments, SLA records, resolution records, ticket events, and labelled evaluation records.

**Recorded project scale:**

- Tickets: 5,000
- Messages: 23,000
- Assignments: 5,500
- SLA records: 5,000
- Resolution records: 5,000
- Ticket events: 29,000
- Labelled ground-truth records: 5,000
- Labelled anomaly/evaluation records: 200

**Scenario categories:** Normal requests, ambiguous requests, requests with missing context, confidential requests, and outdated-policy scenarios.

**Engineering focus:** Make generated data suitable for validation and workflow evaluation without treating labels as proof that an operational defect exists.

### Phase 5 — Centralized workflow rules

**Development objective:** Define consistent rules for ticket routing, priorities, lifecycle states, allowed transitions, clarification handling, and escalation thresholds.

**AI assistance:** Help organize workflow rules into a central module and identify how other modules should use those rules.

**Engineering decision:** Keep deterministic business decisions in explicit Python rules wherever possible rather than delegating routing and lifecycle decisions entirely to a language model.

**Reasoning:** Explicit rules are easier to inspect, test, reproduce, and explain to reviewers.

### Phase 6 — Ticket processing and runtime behavior

**Development objective:** Connect the data layer and workflow rules to an executable ticket-processing workflow.

**AI assistance:** Provide implementation guidance for request processing, policy and knowledge references, assignments, message handling, state changes, event history, and command-line execution.

**Engineering focus:** Preserve traceability by recording meaningful state changes and avoiding silent overwrites of existing runtime history.

**Verification approach:** Use targeted commands, inspect ticket states and history, and execute automated tests. The recorded tests are evidence of the behavior covered by those tests, not proof that every possible workflow is correct.

### Phase 7 — Logging, persistence, and exports

**Development objective:** Make runtime behavior inspectable and retain project outputs in accessible formats.

**AI assistance:** Help structure logging, SQLite persistence, JSON exports, CSV outputs, and dataset export manifests.

**Engineering focus:** Keep generated data and runtime processing evidence available for inspection and troubleshooting.

**Verification approach:** Check exported artifacts, database tables, record counts, and log outputs using the available validation commands.

### Phase 8 — Validation and regression testing

**Development objective:** Detect invalid records and regressions in the implementation.

**AI assistance:** Help organize validation modules, test cases, command execution, and interpretation of test output.

**Recorded evidence:** The latest recorded full test run completed with 23 tests passing in 75.36 seconds.

Additional recorded checks included master-data validation, foreign-key checks, message validation, and CSV-to-SQL row-count consistency.

**Important qualification:** Passing tests demonstrate that the tested cases passed under the recorded conditions. They do not independently establish that all business rules, edge cases, and runtime scenarios are correct.

### Phase 9 — Ground truth and anomaly evaluation

**Development objective:** Create labelled evaluation records and inspect whether anomaly-audit results agree with their expected outcomes.

**AI assistance:** Help organize anomaly categories, audit outputs, and evaluation reporting.

**Evaluation categories:** Obsolete policy references, sensitive cases routed to a general queue, SLA business-hours errors, and unsupported claims.

**Important qualification:** The 200 labelled anomaly/evaluation records must not be described as 200 confirmed faults injected into operational data. Labels, detector outputs, and actual operational defects are distinct concepts.

Recorded audit results included mismatches and inconclusive findings. These require careful interpretation and, where applicable, further investigation. In particular, unsupported-claim results were inconclusive, and the SLA audit requires scrutiny of its elapsed-time assumptions.

### Phase 10 — Reproducibility and documentation

**Development objective:** Document setup, execution, validation, project structure, limitations, and evaluation evidence.

**AI assistance:** Help improve the README, organize verification commands, explain the architecture, and document limitations and AI usage.

**Engineering focus:** Make it possible for another developer to understand how the project is structured, reproduce documented steps, and inspect the available evidence without relying on unsupported claims.

## 5. How AI Assistance Was Used

AI assistance supported development activities such as:

- Breaking a large assignment into manageable implementation phases.
- Explaining Python implementation patterns and project structure.
- Helping troubleshoot errors and interpret terminal output.
- Supporting the organization of data generators, workflow modules, and validators.
- Reviewing test output and suggesting additional verification.
- Improving documentation and explaining design decisions.

This disclosure does not imply that every line of code was independently authored by the candidate, nor does it claim that AI-generated code was automatically correct.

The source code, datasets, tests, reports, and repository history should be used to evaluate the actual implementation.

## 6. Engineering Decisions and Rationale

### Data-first implementation

The project began with master and reference data before proceeding to dependent records and runtime behavior. This made it possible to establish relationships and validate the data layer before introducing additional complexity.

### Deterministic business rules

Routing, priorities, lifecycle transitions, clarification requirements, and escalation behavior were organized around explicit workflow rules. This makes important business decisions easier to inspect and test.

### Traceability

Ticket history, assignments, messages, events, and policy references provide evidence of how requests move through the system. These artifacts should be inspected to confirm that traceability is maintained in each relevant workflow.

### Automated verification

Automated tests and validation commands were used to check the implementation. Test results should be interpreted within their actual coverage, and unresolved findings should remain documented.

### Explicit limitations

The project documentation distinguishes successful checks from assumptions, inconclusive results, and remaining work. This is important because a successful execution or test run does not guarantee that every business scenario has been handled correctly.

## 7. Personal Review and Validation

The candidate should use this section to record only work personally performed and understood.

- [ ] I can explain the project architecture and the purpose of its main modules.
- [ ] I can explain how master data, policy versions, knowledge articles, and tickets relate to each other.
- [ ] I can explain the routing, clarification, lifecycle, and escalation rules implemented in the code.
- [ ] I have reviewed the relevant test results and understand what the tests do and do not prove.
- [ ] I have inspected unresolved anomaly-audit results and identified which findings remain open.
- [ ] I can reproduce the documented setup and verification commands.
- [ ] I have checked the repository for credentials, secrets, and information that should not be public.
- [ ] I have reviewed the final repository contents and can explain the implementation decisions I am submitting.

These checkboxes are a verification checklist, not claims that every item has already been completed.

## 8. Limitations and Outstanding Verification

The following points must remain visible until they are resolved:

1. The available prompt record is not a complete export of every AI interaction.
2. Reconstructed phase summaries must not be presented as exact original prompts.
3. The available record may not contain every prompt submitted to ChatGPT and Microsoft Copilot; any missing prompts should be recovered or the gap disclosed.
4. Anomaly labels must not be equated with confirmed operational faults.
5. SLA calculations and audit assumptions require verification where results appear inconsistent or unexpected.
6. Test success must not be presented as proof of complete correctness.
7. The final public repository and its submission state must be verified separately.

## 9. Closing Statement

AI assistance was used as part of the development process, including implementation guidance, debugging, testing support, and documentation. The project should be evaluated through its source code, generated data, workflow behavior, tests, validation artifacts, and reproducible execution steps.

The purpose of this record is to make the development process transparent. It does not replace examination of the implementation or the candidate's ability to explain and defend the engineering decisions behind it.
