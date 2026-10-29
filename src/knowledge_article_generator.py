from pathlib import Path
import logging

import pandas as pd


# --------------------------------------------------
# Configuration
# --------------------------------------------------

POLICY_FILE = Path("data/csv/policy_documents.csv")
OUTPUT_DIR = Path("data/csv")
OUTPUT_FILE = OUTPUT_DIR / "knowledge_articles.csv"


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Load Policies
# --------------------------------------------------

def load_policies():
    """Load and validate policy master data."""

    logger.info("Loading policies from %s", POLICY_FILE)

    if not POLICY_FILE.exists():
        raise FileNotFoundError(
            f"Policy file not found: {POLICY_FILE}. "
            "Run policy_generator.py first."
        )

    policies = pd.read_csv(POLICY_FILE)

    required_columns = {
        "policy_id",
        "policy_name",
        "policy_category",
    }

    missing_columns = required_columns - set(policies.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if policies["policy_id"].duplicated().any():
        raise ValueError(
            "Duplicate policy_id found."
        )

    logger.info(
        "Loaded %d policies successfully",
        len(policies),
    )

    return policies


# --------------------------------------------------
# Generate Knowledge Articles
# --------------------------------------------------

def generate_knowledge_articles():
    """Generate three knowledge articles for every policy."""

    policies = load_policies()

    logger.info("Generating knowledge articles")

    articles = []

    for _, policy in policies.iterrows():

        policy_id = policy["policy_id"]
        policy_name = policy["policy_name"]
        category = policy["policy_category"]

        article_templates = [
            (
                "Overview",
                (
                    f"The {policy_name} defines the general "
                    f"guidelines, eligibility requirements, and "
                    f"responsibilities related to {category.lower()}."
                ),
            ),
            (
                "Eligibility and Process",
                (
                    f"Employees should review the {policy_name} "
                    f"requirements before submitting a request. "
                    f"Requests must follow the applicable HR process "
                    f"and required approvals."
                ),
            ),
            (
                "Employee Guidance",
                (
                    f"For questions regarding the {policy_name}, "
                    f"employees should contact HR and refer to the "
                    f"current approved policy version."
                ),
            ),
        ]

        for article_number, (article_type, content) in enumerate(
            article_templates,
            start=1,
        ):
            articles.append(
                {
                    "article_id": (
                        f"KA-{policy_id}-{article_number:02}"
                    ),
                    "policy_id": policy_id,
                    "article_title": (
                        f"{policy_name} - {article_type}"
                    ),
                    "article_type": article_type,
                    "category": category,
                    "content": content,
                    "status": "PUBLISHED",
                }
            )

    article_df = pd.DataFrame(articles)

    # --------------------------------------------------
    # Validation
    # --------------------------------------------------

    logger.info("Validating generated knowledge articles")

    assert len(article_df) == 150

    assert article_df["article_id"].is_unique

    assert article_df["policy_id"].isin(
        policies["policy_id"]
    ).all()

    articles_per_policy = (
        article_df.groupby("policy_id")
        .size()
    )

    assert (articles_per_policy == 3).all()

    assert set(article_df["status"]) == {
        "PUBLISHED"
    }

    logger.info(
        "Knowledge article validation successful"
    )

    return article_df


# --------------------------------------------------
# Main
# --------------------------------------------------

def main():
    """Generate and save knowledge articles."""

    try:
        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        article_df = generate_knowledge_articles()

        article_df.to_csv(
            OUTPUT_FILE,
            index=False,
        )

        logger.info(
            "Generated %d knowledge articles",
            len(article_df),
        )

        logger.info(
            "Saved to: %s",
            OUTPUT_FILE,
        )

    except FileNotFoundError as error:
        logger.error("Input file error: %s", error)
        raise

    except ValueError as error:
        logger.error("Validation error: %s", error)
        raise

    except AssertionError as error:
        logger.error(
            "Generated data validation failed: %s",
            error,
        )
        raise

    except Exception:
        logger.exception(
            "Unexpected error while generating knowledge articles"
        )
        raise


if __name__ == "__main__":
    main()