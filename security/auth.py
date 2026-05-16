"""Webhook signature verification + sender allowlist."""

from __future__ import annotations

import hashlib
import hmac
import logging

import config
from security.audit import log_action
from users import is_authorized

logger = logging.getLogger(__name__)

_SIGNATURE_PREFIX = "sha256="


def verify_webhook_signature(payload_bytes: bytes, signature_header: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 header against the raw payload bytes.

    Computes HMAC-SHA256 of ``payload_bytes`` using ``WHATSAPP_APP_SECRET`` and
    compares (constant-time) against the hex digest in ``signature_header``.
    Returns False if the header is missing, malformed, or does not match.
    """
    if not signature_header or not signature_header.startswith(_SIGNATURE_PREFIX):
        return False
    received = signature_header[len(_SIGNATURE_PREFIX):]
    expected = hmac.new(
        config.WHATSAPP_APP_SECRET.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(received, expected)


def authorize_sender(phone: str) -> bool:
    """Return True only if ``phone`` is in the user registry.

    Logs unauthorized attempts to the audit trail with the phone (masked) and
    timestamp only — never message content.
    """
    if is_authorized(phone):
        return True
    log_action(phone, "unauthorized_sender", "phone not in registry", "denied")
    return False
