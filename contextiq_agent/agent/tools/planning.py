"""Plan summary tool — saves planning session summaries."""

from __future__ import annotations

import uuid

from strands import tool

# In-memory plan storage (DynamoDB deferred)
_plan_store: dict[str, list[dict]] = {}


@tool
def save_plan_summary(summary: str, user_id: str = "default") -> dict:
    """Save a planning session summary for later reference.

    Args:
        summary: The complete plan summary text to save.
        user_id: User identifier. Default "default".

    Returns:
        Dict with 'saved' status and plan ID, or 'error' if saving failed.
    """
    plan_id = str(uuid.uuid4())[:8]

    try:
        plans = _plan_store.setdefault(user_id, [])
        plans.append({"plan_id": plan_id, "summary": summary})
        return {"saved": True, "plan_id": plan_id}
    except Exception as exc:
        return {"error": f"Could not save plan summary: {type(exc).__name__}"}
