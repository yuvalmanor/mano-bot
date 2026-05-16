"""Parse incoming Meta Cloud API webhook payloads. Implemented in Task 2."""

from __future__ import annotations


def parse_incoming(payload: dict) -> dict | None:
    """Extract from_phone, message_type, text, message_id from a Meta payload.

    Returns None for status updates (delivered/read receipts) or malformed payloads.
    Implemented in Task 2.
    """
    raise NotImplementedError("whatsapp.webhook.parse_incoming is implemented in Task 2")
