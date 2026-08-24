"""Calendar event tool — creates events in the frontend calendar via WebSocket callback."""

from __future__ import annotations

from strands import tool


def _resolve_date(date_str: str) -> str:
    """Resolve any date string to YYYY-MM-DD using natural language parsing.

    Handles: day names ("Thursday"), relative dates ("tomorrow"), month+day
    ("April 23rd", "May 5th"), ISO dates ("2026-05-05"), and more.
    Always prefers future dates over past ones.
    """
    import dateparser
    from datetime import datetime

    result = dateparser.parse(
        date_str,
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    if result:
        return result.strftime("%Y-%m-%d")

    # Fallback: return as-is and let the error surface
    return date_str


@tool
def create_calendar_event(
    title: str,
    date: str,
    time: str = "",
    location: str = "",
    notes: str = "",
) -> dict:
    """Create a calendar event.

    Use this when the user confirms moving or scheduling an event.

    Args:
        title: Event title (e.g. "Taco Night").
        date: When the event is. Pass whatever the user said — day name ("Thursday"),
              month and day ("April 23rd", "May 5th"), or ISO date ("2026-05-05").
              The system resolves it automatically. Do not pull a date from memory —
              use the date the user just confirmed in this conversation.
        time: Start time in HH:MM 24h format (e.g. "18:30"). Empty for all-day.
        location: Optional location.
        notes: Optional notes.

    Returns:
        Dict with success confirmation and resolved date.
    """
    try:
        from datetime import datetime

        resolved_date = _resolve_date(date)

        iso_datetime = None
        if resolved_date and time:
            iso_datetime = datetime.fromisoformat(f"{resolved_date}T{time}:00").isoformat()
        elif resolved_date:
            iso_datetime = f"{resolved_date}T00:00:00"

        return {
            "success": True,
            "title": title,
            "date": resolved_date,
            "time": time,
            "location": location,
            "notes": notes,
            "iso_datetime": iso_datetime,
            "message": f"Calendar event created: {title} on {resolved_date}{' at ' + time if time else ''}",
        }
    except Exception as exc:
        return {"error": f"Failed to create calendar event: {exc}"}
