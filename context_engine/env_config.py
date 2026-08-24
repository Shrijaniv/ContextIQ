"""Environment configuration for context_engine.

All AWS account ids, resource ids, and bucket names come from the environment —
nothing is hardcoded, so the repo can be shared without leaking infrastructure
details. See `.env.example` at the repo root for the full list.
"""

import os


def require(name: str) -> str:
    """Read a required environment variable, or fail with a clear message."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"or export {name} before running this script."
        )
    return value


def region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-west-2")


def bucket() -> str:
    """Bee context S3 bucket.

    Uses BEE_CONTEXT_BUCKET if set, otherwise derives the conventional name
    `bee-context-store-<account>-<region>` from AWS_ACCOUNT_ID.
    """
    explicit = os.environ.get("BEE_CONTEXT_BUCKET")
    if explicit:
        return explicit
    return f"bee-context-store-{require('AWS_ACCOUNT_ID')}-{region()}"
