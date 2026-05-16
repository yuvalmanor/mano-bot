"""Webhook signature verification + sender allowlist. Implemented in Task 4."""

from __future__ import annotations


def verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    raise NotImplementedError(
        "security.auth.verify_webhook_signature is implemented in Task 4"
    )


def authorize_sender(phone: str) -> bool:
    raise NotImplementedError(
        "security.auth.authorize_sender is implemented in Task 4"
    )
