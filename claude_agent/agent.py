"""Claude interaction loop."""

from __future__ import annotations

import logging

from anthropic import AsyncClient

import config
from claude_agent.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

CONVERSATION_HISTORY: dict[str, list[dict]] = {}
MAX_HISTORY_TURNS = 5

HEBREW_ERROR = "משהו השתבש, נסה שוב"

PENDING_ACTIONS: dict[str, dict] = {}
TTL_MINUTES = 5
CONFIRM_WORDS = {"כן", "yes", "אשר", "ok", "confirm", "כן."}
CANCEL_WORDS = {"לא", "no", "ביטול", "cancel", "בטל", "לא."}


async def run(user_phone: str, message: str) -> str:
    """Run a Claude turn for a given user.

    Loads conversation history, calls claude-sonnet-4-6 with system prompt
    (cached via ephemeral cache_control), and returns the assistant's reply.
    On API error, logs without message content and returns Hebrew error message.
    """
    if user_phone not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[user_phone] = []

    history = CONVERSATION_HISTORY[user_phone]
    history.append({"role": "user", "content": message})

    client = AsyncClient(api_key=config.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=history,
            tools=[],
        )
    except Exception as exc:
        logger.error(
            "Claude API error for phone ****%s: %s",
            user_phone[-4:] if len(user_phone) > 4 else "****",
            exc.__class__.__name__,
        )
        return HEBREW_ERROR

    assistant_reply = response.content[0].text
    history.append({"role": "assistant", "content": assistant_reply})

    while len(history) > MAX_HISTORY_TURNS * 2:
        history[:2] = []

    return assistant_reply
