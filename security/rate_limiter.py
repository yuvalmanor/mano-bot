"""Per-phone in-memory rate limiter.

Limits each phone to ``MAX_MESSAGES`` messages per ``WINDOW_SECONDS``. State is
in-process only — if the worker restarts the counters reset. Acceptable for the
current single-instance Railway deployment.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

MAX_MESSAGES = 20
WINDOW_SECONDS = 10 * 60

_HITS: Dict[str, Deque[float]] = {}

_HEBREW_WARNING = "יותר מדי הודעות. נסה שוב בעוד כמה דקות."


def check_rate_limit(phone: str) -> bool:
    """Return True if ``phone`` is within the rate limit, False if over.

    Records the current timestamp on every call (including denials, so a sender
    spamming during the window keeps the window sliding forward — this is
    intentional, matching common per-key sliding-window behaviour).
    """
    now = time.monotonic()
    hits = _HITS.setdefault(phone, deque())
    cutoff = now - WINDOW_SECONDS
    while hits and hits[0] < cutoff:
        hits.popleft()
    if len(hits) >= MAX_MESSAGES:
        return False
    hits.append(now)
    return True


def get_rate_limit_message() -> str:
    """Hebrew warning string returned to senders that hit the rate limit."""
    return _HEBREW_WARNING


def _reset_for_tests() -> None:
    """Clear all rate-limit state. Test-only helper."""
    _HITS.clear()
