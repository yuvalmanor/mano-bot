"""Audit logging.

Appends one line per action to ``audit.log`` in the working directory. Phone
numbers are masked to the last 4 digits. Message content is never logged.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "audit.log")


def _mask(phone: str) -> str:
    if not phone:
        return "****"
    tail = phone[-4:] if len(phone) >= 4 else phone
    return f"****{tail}"


def log_action(phone: str, action_type: str, details: str, status: str) -> None:
    """Append one audit line. Never raises — audit must not break the request path."""
    ts = datetime.now(timezone.utc).isoformat()
    line = (
        f"[{ts}] | phone={_mask(phone)} | action={action_type} "
        f"| details={details} | status={status}\n"
    )
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        logger.error("Failed to write audit log: %s", exc.__class__.__name__)
