"""Parse incoming Meta Cloud API webhook payloads."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_incoming(payload: Any) -> dict | None:
    """Extract from_phone, message_type, text, message_id from a Meta payload.

    Returns None for status updates (delivered/read receipts), non-text messages
    we don't yet handle, or malformed payloads. Returns dict with keys:
    ``from_phone``, ``message_type``, ``text``, ``message_id`` for text messages.
    """
    if not isinstance(payload, dict):
        return None

    try:
        entry = payload.get("entry") or []
        for entry_item in entry:
            changes = entry_item.get("changes") or []
            for change in changes:
                value = change.get("value") or {}
                # Status updates (delivered, read, sent) — silently ignore
                if "statuses" in value and "messages" not in value:
                    return None
                messages = value.get("messages") or []
                if not messages:
                    continue
                msg = messages[0]
                message_type = msg.get("type")
                message_id = msg.get("id")
                from_phone = msg.get("from")
                if not (message_type and message_id and from_phone):
                    return None
                if not from_phone.startswith("+"):
                    from_phone = "+" + from_phone
                if message_type != "text":
                    return None
                text = (msg.get("text") or {}).get("body")
                if text is None:
                    return None
                return {
                    "from_phone": from_phone,
                    "message_type": message_type,
                    "text": text,
                    "message_id": message_id,
                }
        return None
    except (AttributeError, TypeError, KeyError, IndexError):
        logger.warning("Malformed webhook payload received")
        return None
