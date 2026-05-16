"""Shared test fixtures. Resets in-process state between tests."""

from __future__ import annotations

import pytest

import main
from security import rate_limiter


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Clear dedup + rate-limit state so tests don't leak into each other."""
    main.SEEN_MESSAGE_IDS.clear()
    main.SEEN_MESSAGE_IDS_QUEUE.clear()
    rate_limiter._reset_for_tests()
    yield
