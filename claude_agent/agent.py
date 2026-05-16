"""Claude interaction loop. Implemented in Task 3."""

from __future__ import annotations

CONVERSATION_HISTORY: dict[str, list[dict]] = {}
MAX_HISTORY_TURNS = 5


async def run(user_phone: str, message: str) -> str:
    """Run a Claude turn for a given user. Implemented in Task 3."""
    raise NotImplementedError("claude_agent.agent.run is implemented in Task 3")
