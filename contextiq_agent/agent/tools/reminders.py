"""Reminders tool — creates tasks with due dates via Todoist API v1."""

from __future__ import annotations

from strands import tool


@tool
def create_reminder(text: str, due_date: str) -> dict:
    """Create a reminder task in Todoist.

    Args:
        text: What to be reminded about (e.g. "Buy black beans before taco night").
        due_date: When the reminder is due in natural language
                  (e.g. "tomorrow 9am", "Thursday", "April 25th", "in 2 hours").

    Returns:
        Dict with confirmation and task URL, or 'error' key if it fails.
    """
    import os
    import httpx

    token = os.environ.get("TODOIST_API_TOKEN", "")
    if not token:
        return {"error": "TODOIST_API_TOKEN not configured in .env"}

    try:
        resp = httpx.post(
            "https://api.todoist.com/api/v1/tasks",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": text, "due_string": due_date, "priority": 2},
            timeout=10.0,
        )
        resp.raise_for_status()
        task = resp.json()
        # Extract ISO date from Todoist response for frontend display
        due_info = task.get("due") or {}
        iso_date = due_info.get("datetime") or due_info.get("date")
        return {
            "success": True,
            "task_id": task.get("id"),
            "text": text,
            "due_date": due_date,
            "iso_date": iso_date,
            "url": task.get("url"),
            "message": f"Reminder set: {text} — due {due_date}",
        }
    except Exception as exc:
        return {"error": f"Failed to create reminder: {exc}"}
