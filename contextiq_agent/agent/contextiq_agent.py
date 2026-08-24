"""ContextIQ agent — BidiAgent setup with Nova Sonic and system prompt."""

from __future__ import annotations
import pathlib

from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models import BidiNovaSonicModel
from context_engine.tools.agent_context_retrieval import retrieve_context
from contextiq_agent.agent.config import ContextIQConfig
from contextiq_agent.agent.tools import (
    check_weather,
    search_restaurants,
    save_plan_summary,
    create_reminder,
    create_calendar_event,
    search_web,
    amazon_shopping,
    opentable_search,
    opentable_select_restaurant,
    opentable_reserve,
    opentable_confirm_reservation,
)

# System prompt is maintained in prompt.md — edit that file to update agent behavior
_PROMPT_TEMPLATE = (
    pathlib.Path(__file__).parent / "prompt.md"
).read_text(encoding="utf-8")


def _build_system_prompt() -> str:
    """Inject today's date so the agent can resolve relative dates correctly."""
    from datetime import date
    today = date.today()
    date_context = (
        f"Today's date: {today.strftime('%A, %B %-d, %Y')} ({today.isoformat()})\n\n"
    )
    return date_context + _PROMPT_TEMPLATE


CONTEXTIQ_SYSTEM_PROMPT = _build_system_prompt()


def create_contextiq_agent(
    config: ContextIQConfig,
    voice_id: str = "matthew",
    on_reminder_created=None,
    on_calendar_event_created=None,
    event_loop=None,
) -> BidiAgent:
    """Create and configure the ContextIQ BidiAgent with Nova Sonic and retrieve_context tool.

    Args:
        config: ContextIQ configuration.
        voice_id: Nova Sonic voice ID.
        on_reminder_created: Optional async callable(text, due_date, result) — pushes
            reminder_created WebSocket event to the frontend.
        on_calendar_event_created: Optional async callable(result) — pushes
            calendar_event_created WebSocket event to the frontend.
    """
    import asyncio
    from strands import tool as strands_tool

    model = BidiNovaSonicModel(
        client_config={"region": config.aws_region},
        provider_config={
            "audio": {"voice": voice_id},
            "turn_detection": {"endpointingSensitivity": "HIGH"},
        }
    )

    # Use the captured event loop for thread-safe scheduling from tool callbacks
    _loop = event_loop

    def _schedule(coro) -> None:
        """Schedule an async callback from a sync tool thread context."""
        if _loop is not None and _loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, _loop)
        else:
            import warnings
            warnings.warn("Could not schedule callback — no event loop available")

    # Wrap create_reminder to emit WS event on success
    if on_reminder_created is not None:
        @strands_tool
        def create_reminder_notifying(text: str, due_date: str) -> dict:
            """Create a reminder and notify the frontend in real time."""
            result = create_reminder(text=text, due_date=due_date)
            if result.get("success"):
                _schedule(on_reminder_created(text, due_date, result))
            return result

        reminder_tool = create_reminder_notifying
    else:
        reminder_tool = create_reminder

    # Wrap create_calendar_event to emit WS event on success
    if on_calendar_event_created is not None:
        @strands_tool
        def create_calendar_event_notifying(
            title: str, date: str, time: str = "", location: str = "", notes: str = ""
        ) -> dict:
            """Create a calendar event and notify the frontend in real time."""
            result = create_calendar_event(
                title=title, date=date, time=time, location=location, notes=notes
            )
            if result.get("success"):
                _schedule(on_calendar_event_created(result))
            return result

        calendar_tool = create_calendar_event_notifying
    else:
        calendar_tool = create_calendar_event

    tools = [
        retrieve_context,
        check_weather,
        search_restaurants,
        save_plan_summary,
        reminder_tool,
        calendar_tool,
        search_web,
        amazon_shopping,
        opentable_search,
        opentable_select_restaurant,
        opentable_reserve,
        opentable_confirm_reservation,
    ]

    return BidiAgent(
        model=model,
        system_prompt=_build_system_prompt(),
        tools=tools,
    )
