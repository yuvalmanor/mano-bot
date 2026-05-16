"""Google Calendar integration. Implemented in Task 7.

Named gcalendar to avoid shadowing the stdlib calendar module.
"""

from __future__ import annotations


async def create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None = None,
) -> bool:
    raise NotImplementedError(
        "integrations.gcalendar.create_event is implemented in Task 7"
    )


async def list_upcoming_events(days: int = 7) -> str:
    raise NotImplementedError(
        "integrations.gcalendar.list_upcoming_events is implemented in Task 7"
    )
