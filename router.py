"""Message routing."""

from __future__ import annotations

import logging

from claude_agent.agent import run as run_claude
from whatsapp.client import send_message

logger = logging.getLogger(__name__)

HEBREW_ERROR = "משהו השתבש, נסה שוב"


async def handle_message(from_phone: str, text: str) -> None:
    """Route an incoming WhatsApp text message to Claude and send the reply.

    Wraps the entire body in try/except to ensure the user always gets a reply,
    even on unhandled exceptions. On any error, sends the Hebrew fallback message.
    """
    try:
        reply = await run_claude(from_phone, text)
        await send_message(from_phone, reply)
    except Exception as exc:
        logger.error(
            "Unhandled exception in handle_message for phone ****%s: %s",
            from_phone[-4:] if len(from_phone) > 4 else "****",
            exc.__class__.__name__,
        )
        try:
            await send_message(from_phone, HEBREW_ERROR)
        except Exception as send_exc:
            logger.error(
                "Failed to send error message to phone ****%s: %s",
                from_phone[-4:] if len(from_phone) > 4 else "****",
                send_exc.__class__.__name__,
            )
