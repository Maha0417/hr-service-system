from pathlib import Path
from datetime import datetime, timezone
import json

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "csv"
OUT = ROOT / "output" / "anomaly_audit"
REPORT = OUT / "anomaly_audit_report.json"

REQUIRED_TYPES = {
    "obsolete_policy_reference",
    "sensitive_case_routed_general_queue",
    "sla_business_hours_error",
    "unsupported_claim",
}


def load_csv(name):
    path = DATA / f"{name}.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Required dataset missing: {path}")
    return pd.read_csv(path, dtype=str).fillna("")


def is_true(value):
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def is_expired(version, ticket_date):
    """Check policy status and date validity at ticket creation time."""
    status = version.get("status", "").strip().upper()
    expiration = version.get("expiration_date", "").strip()
    effective = version.get("effective_date", "").strip()
    ticket_date = str(ticket_date)[:10]

    if status == "EXPIRED":
        return True
    if effective and ticket_date < effective:
        return True
    if expiration and ticket_date > expiration:
        return True
    return False


def evaluate_policy_reference(records, ticket_date, versions, expected_version):
    """Evaluate policy citations against version validity and ground truth."""
    cited_ids = (
        sorted(set(records["policy_version_id"].astype(str)) - {""})
        if not records.empty
        else []
    )

    expired_ids = [
        version_id
        for version_id in cited_ids
        if version_id in versions
        and is_expired(versions[version_id], ticket_date)
    ]

    evidence = {
        "ticket_creation_date": str(ticket_date)[:10],
        "cited_policy_version_ids": cited_ids,
        "expired_or_date_invalid_versions": expired_ids,
        "ground_truth_expected_version": expected_version,
    }

    if not records.empty and expired_ids:
        return (
            "MATCH",
            "A cited policy version is expired or outside its effective date at ticket creation.",
            evidence,
        )

    if not records.empty and expected_version in cited_ids:
        return (
            "MISMATCH",
            "The expected policy version is cited and no expired version was detected.",
            evidence,
        )

    if not records.empty:
        return (
            "MISMATCH",
            "The cited version differs from ground truth, but no expired citation was detected.",
            evidence,
        )

    return (
        "INCONCLUSIVE",
        "No policy response exists to verify the citation.",
        evidence,
    )


def evaluate_sla_record(sla):
    """Evaluate stored SLA breach flags against the clock-hour rule."""
    try:
        elapsed = float(sla["elapsed_hours"])
        target = float(sla["resolution_target_hours"])
        business_hours_only = is_true(sla["business_hours_only"])
        stored_breach = is_true(sla["sla_breached"])
        calculated_breach = elapsed > target

        evidence = {
            "business_hours_only": business_hours_only,
            "elapsed_hours": elapsed,
            "resolution_target_hours": target,
            "stored_breach": stored_breach,
            "calculated_clock_hour_breach": calculated_breach,
        }

        if business_hours_only:
            return (
                "MATCH",
                "The SLA is configured for business-hours-only calculation, "
                "contrary to the labelled clock-hour rule.",
                evidence,
            )

        if stored_breach != calculated_breach:
            return (
                "MATCH",
                "The stored breach flag disagrees with elapsed clock hours "
                "and the configured target.",
                evidence,
            )

        return (
            "MISMATCH",
            "The SLA uses clock hours and its stored breach flag matches "
            "the clock-hour calculation.",
            evidence,
        )

    except (TypeError, ValueError, KeyError) as exc:
        return "FAIL", f"Invalid SLA fields: {exc}", {}


def evaluate_sensitive_routing(records, ticket, category, expected_route):
    """Evaluate a sensitive ticket's latest recorded assignment."""
    scenario = ticket.get("scenario_type", "").strip().upper()

    sensitive = (
        is_true(ticket.get("sensitive_flag", ""))
        or category.get("category_name", "").strip().lower()
        == "employee relations"
        or scenario == "CONFIDENTIAL"
    )

    groups = (
        sorted(set(records["assigned_group"].astype(str).str.strip()) - {""})
        if not records.empty
        else []
    )

    # Use the latest recorded assignment, not any historical assignment.
    latest_group = ""
    if not records.empty and "assigned_timestamp" in records.columns:
        ordered = records.sort_values("assigned_timestamp")
        latest_group = str(ordered.iloc[-1]["assigned_group"]).strip()

    evidence = {
        "sensitive_case": sensitive,
        "assignment_groups": groups,
        "latest_recorded_assignment_group": latest_group,
        "expected_route": expected_route,
    }

    if records.empty:
        return (
            "INCONCLUSIVE",
            "No assignment history is available.",
            evidence,
        )

    if not sensitive:
        return (
            "INCONCLUSIVE",
            "Available ticket fields do not identify this ticket as sensitive.",
            evidence,
        )

    if expected_route and expected_route != "HR_PARTNER":
        return (
            "FAIL",
            "Ground truth conflicts with the mandatory HR_PARTNER routing rule.",
            evidence,
        )

    if latest_group and latest_group != "HR_PARTNER":
        return (
            "MATCH",
            "The latest recorded assignment for a sensitive ticket is not HR_PARTNER.",
            evidence,
        )

    return (
        "MISMATCH",
        "The latest recorded assignment for this sensitive ticket is HR_PARTNER.",
        evidence,
    )


def main():
    anomalies = load_csv("anomalies")
    messages = load_csv("messages")
    assignments = load_csv("assignments")
    slas = load_csv("sla_records")
    tickets_df = load_csv("tickets")
    versions_df = load_csv("policy_versions")
    categories_df = load_csv("categories")
    ground_truth_df = load_csv("ground_truth")

    # Index source records for read-only checks.
    tickets = tickets_df.set_index("ticket_id").to_dict("index")
    versions = versions_df.set_index("version_id").to_dict("index")
    categories = categories_df.set_index("category_id").to_dict("index")
    ground_truth = ground_truth_df.set_index("entity_id").to_dict("index")

    policy_messages = messages[messages["message_type"].eq("POLICY_RESPONSE")]
    messages_by_ticket = {
        key: group for key, group in policy_messages.groupby("ticket_id")
    }
    assignments_by_ticket = {
        key: group for key, group in assignments.groupby("ticket_id")
    }
    slas_by_ticket = {
        key: group for key, group in slas.groupby("ticket_id")
    }

    results = []

    for row in anomalies.to_dict("records"):
        ticket_id = row["entity_id"]
        issue = row["issue_type"]
        observed = "INCONCLUSIVE"
        reason = ""
        evidence = {}

        ticket = tickets.get(ticket_id)
        truth = ground_truth.get(ticket_id, {})

        if ticket is None:
            observed = "FAIL"
            reason = "Anomaly references a ticket absent from tickets.csv."

        elif issue == "obsolete_policy_reference":
            records = messages_by_ticket.get(ticket_id, pd.DataFrame())
            ticket_date = ticket.get("created_timestamp", "")[:10]
            expected_version = truth.get("expected_policy_version", "")

            observed, reason, evidence = evaluate_policy_reference(
                records,
                ticket_date,
                versions,
                expected_version,
            )

        elif issue == "sensitive_case_routed_general_queue":
            records = assignments_by_ticket.get(ticket_id, pd.DataFrame())
            category = categories.get(ticket.get("category_id", ""), {})
            expected_route = truth.get("expected_route", "")

            observed, reason, evidence = evaluate_sensitive_routing(
                records,
                ticket,
                category,
                expected_route,
            )

        elif issue == "sla_business_hours_error":
            records = slas_by_ticket.get(ticket_id, pd.DataFrame())

            if records.empty:
                reason = "No SLA record is available."
            else:
                sla = records.iloc[-1].to_dict()
                observed, reason, evidence = evaluate_sla_record(sla)

        elif issue == "unsupported_claim":
            records = messages_by_ticket.get(ticket_id, pd.DataFrame())
            content = (
                " ".join(records["message_content"].astype(str).tolist())
                if not records.empty
                else ""
            )
            cited_ids = (
                sorted(set(records["policy_version_id"].astype(str)) - {""})
                if not records.empty
                else []
            )
            expected_version = truth.get("expected_policy_version", "")

            evidence = {
                "policy_response_count": len(records),
                "cited_policy_versions": cited_ids,
                "expected_policy_version": expected_version,
                "policy_response_content_available": bool(content.strip()),
            }

            if records.empty or not content.strip():
                reason = "No policy response content is available for claim review."
            elif not cited_ids:
                observed = "MATCH"
                reason = (
                    "The policy response lacks a policy-version reference; "
                    "semantic claim support still needs review."
                )
            elif expected_version and expected_version not in cited_ids:
                observed = "MATCH"
                reason = (
                    "The expected policy version is not cited; a content-level "
                    "review is needed to determine whether the claim is unsupported."
                )
            else:
                reason = (
                    "A policy version is cited, but citation presence alone "
                    "cannot prove that the claim is supported."
                )

        else:
            observed = "FAIL"
            reason = "Unrecognized anomaly type."

        evidence.update({
            "ticket_exists": ticket is not None,
            "ground_truth_exists": ticket_id in ground_truth,
        })

        results.append({
            "anomaly_id": row["anomaly_id"],
            "ticket_id": ticket_id,
            "issue_type": issue,
            "severity": row["severity"],
            "audit_status": observed,
            "reason": reason,
            "evidence": evidence,
        })

    counts = {}
    for issue in sorted(REQUIRED_TYPES):
        subset = [r for r in results if r["issue_type"] == issue]
        counts[issue] = {
            "labelled": len(subset),
            **{
                status: sum(r["audit_status"] == status for r in subset)
                for status in ("MATCH", "MISMATCH", "FAIL", "INCONCLUSIVE")
            },
        }

    report = {
        "report_type": "READ_ONLY_ANOMALY_AUDIT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_datasets_modified": False,
        "runtime_database_modified": False,
        "total_labelled_anomalies": len(results),
        "required_anomaly_types_present": sorted(
            set(anomalies["issue_type"]) & REQUIRED_TYPES
        ),
        "unexpected_anomaly_types": sorted(
            set(anomalies["issue_type"]) - REQUIRED_TYPES
        ),
        "summary_by_type": counts,
        "limitations": [
            "The audit evaluates labelled cases against observed records; it does not inject or repair anomalies.",
            "MATCH means evidence supports the specified detector condition, not that every claim in the anomaly label has been proven.",
            "Unsupported claims require semantic comparison against policy text; citation IDs alone cannot establish support.",
            "Assignment history is evaluated by its latest timestamp, but active assignment semantics may require additional validation.",
            "SLA arithmetic is checked using clock hours; business calendars and holidays are not calculated.",
        ],
        "records": results,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Audit report written: {REPORT}")
    print(f"Total labelled anomalies: {len(results)}")
    for issue, values in counts.items():
        print(
            f"{issue}: labelled={values['labelled']}, "
            f"MATCH={values['MATCH']}, MISMATCH={values['MISMATCH']}, "
            f"FAIL={values['FAIL']}, INCONCLUSIVE={values['INCONCLUSIVE']}"
        )
    print("Source CSV datasets and runtime SQLite database were not modified.")


if __name__ == "__main__":
    main()