"""Webhook signature verification + sender allowlist.

``verify_webhook_signature`` is implemented in Task 2 (needed by main.py).
``authorize_sender`` is implemented in Task 4.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import config

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
    raise NotImplementedError(
        "security.auth.authorize_sender is implemented in Task 4"
    )
