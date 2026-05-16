"""Send messages via the Meta Cloud API."""

from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v19.0"
TIMEOUT_SECONDS = 10.0


def _messages_url() -> str:
    return (
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )


async def send_message(to_phone: str, text: str) -> bool:
    """POST a text message to the Meta Cloud API.

    Returns True on 2xx, False on timeout, network failure, or non-2xx response.
    Never logs the access token. Errors are logged with status code but not body
    content beyond a short snippet for debugging.
    """
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text},
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(_messages_url(), json=payload, headers=headers)
    except httpx.TimeoutException:
        logger.error("WhatsApp send timeout to %s", _mask_phone(to_phone))
        return False
    except httpx.HTTPError as exc:
        logger.error(
            "WhatsApp send network error to %s: %s",
            _mask_phone(to_phone),
            exc.__class__.__name__,
        )
        return False

    if 200 <= resp.status_code < 300:
        return True
    logger.error(
        "WhatsApp send failed to %s: status=%d",
        _mask_phone(to_phone),
        resp.status_code,
    )
    return False


def _mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return "****"
    return "****" + phone[-4:]
