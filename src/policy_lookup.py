from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "csv"


class PolicyLookupError(ValueError):
    """Raised when a valid policy reference cannot be found."""


def load_policy_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load policy documents, versions, and knowledge articles."""
    documents = pd.read_csv(DATA_DIR / "policy_documents.csv", dtype=str).fillna("")
    versions = pd.read_csv(DATA_DIR / "policy_versions.csv", dtype=str).fillna("")
    articles = pd.read_csv(DATA_DIR / "knowledge_articles.csv", dtype=str).fillna("")
    return documents, versions, articles


def get_current_version(
    policy_id: str,
    versions: pd.DataFrame | None = None,
    as_of_date: str | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Return the current version, or the version effective on a supplied date."""
    if versions is None:
        _, versions, _ = load_policy_data()

    required = {
        "version_id", "policy_id", "is_current", "status",
        "effective_date", "expiration_date",
    }
    missing = required - set(versions.columns)
    if missing:
        raise PolicyLookupError(
            f"Policy versions missing columns: {sorted(missing)}"
        )

    matches = versions[versions["policy_id"].eq(policy_id)].copy()
    if matches.empty:
        raise PolicyLookupError(f"No versions found for policy {policy_id}.")

    if as_of_date is None:
        matches = matches[
            matches["is_current"].str.lower().eq("true")
            & matches["status"].str.upper().eq("CURRENT")
        ]
    else:
        requested_date = pd.to_datetime(as_of_date, errors="coerce", utc=True)
        if pd.isna(requested_date):
            raise PolicyLookupError(f"Invalid policy lookup date: {as_of_date}")

        effective_dates = pd.to_datetime(
            matches["effective_date"], errors="coerce", utc=True
        )
        expiration_text = matches["expiration_date"].astype(str).str.strip()
        expiration_dates = pd.to_datetime(
            expiration_text.where(expiration_text.ne("")),
            errors="coerce",
            utc=True,
        )

        valid = effective_dates.notna() & (effective_dates <= requested_date)
        valid &= expiration_dates.isna() | (expiration_dates >= requested_date)
        matches = matches[valid]

    if len(matches) != 1:
        raise PolicyLookupError(
            f"Expected exactly one applicable version for {policy_id}; "
            f"found {len(matches)}."
        )

    return matches.iloc[0].to_dict()

def get_published_article(
    policy_id: str,
    articles: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Return a published knowledge article for a policy."""
    if articles is None:
        _, _, articles = load_policy_data()

    required = {"article_id", "policy_id", "article_title", "content", "status"}
    missing = required - set(articles.columns)
    if missing:
        raise PolicyLookupError(
            f"Knowledge articles missing columns: {sorted(missing)}"
        )

    matches = articles[
        articles["policy_id"].eq(policy_id)
        & articles["status"].str.upper().eq("PUBLISHED")
    ]
    if matches.empty:
        raise PolicyLookupError(
            f"No published knowledge article found for {policy_id}."
        )

    useful = matches[matches["content"].str.strip().ne("")]
    selected = useful.iloc[0] if not useful.empty else matches.iloc[0]
    return selected.to_dict()


def lookup_policy(
    policy_id: str,
    as_of_date: str | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Return policy and article provenance, optionally checked against a date."""
    documents, versions, articles = load_policy_data()

    if "policy_id" not in documents.columns:
        raise PolicyLookupError("Policy documents do not contain policy_id.")

    document_matches = documents[documents["policy_id"].eq(policy_id)]
    if len(document_matches) != 1:
        raise PolicyLookupError(
            f"Expected one policy document for {policy_id}; "
            f"found {len(document_matches)}."
        )

    document = document_matches.iloc[0].to_dict()
    version = get_current_version(policy_id, versions, as_of_date)
    article = get_published_article(policy_id, articles)

    return {
        "policy_id": policy_id,
        "policy_title": document.get("policy_name", ""),
        "version_id": version["version_id"],
        "version_number": version.get("version_number", ""),
        "effective_date": version.get("effective_date", ""),
        "article_id": article["article_id"],
        "article_title": article["article_title"],
        "article_content": article["content"],
        "citation": (
            f"{policy_id} | {version['version_id']} | {article['article_id']}"
        ),
        "decision_status": "POLICY_FOUND",
    }
