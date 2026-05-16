"""Tests for Task 9: GET /audit endpoint and confirm/cancel audit logging."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import config
import main
from security import audit


# ---- GET /audit ------------------------------------------------------------


def test_audit_endpoint_rejects_missing_token() -> None:
    client = TestClient(main.app)
    resp = client.get("/audit")
    assert resp.status_code == 403


def test_audit_endpoint_rejects_wrong_token() -> None:
    client = TestClient(main.app)
    resp = client.get("/audit", headers={"X-Admin-Token": "nope"})
    assert resp.status_code == 403


def test_audit_endpoint_returns_last_50_lines(tmp_path) -> None:
    log = tmp_path / "audit.log"
    # Write 75 lines so we can confirm we get only the last 50 back.
    with open(log, "w", encoding="utf-8") as f:
        for i in range(75):
            f.write(f"line-{i}\n")

    client = TestClient(main.app)
    with patch.object(audit, "AUDIT_LOG_PATH", str(log)):
        resp = client.get("/audit", headers={"X-Admin-Token": config.ADMIN_TOKEN})

    assert resp.status_code == 200
    lines = resp.text.split("\n")
    assert len(lines) == 50
    assert lines[0] == "line-25"
    assert lines[-1] == "line-74"


def test_audit_endpoint_missing_log_file_returns_empty_200(tmp_path) -> None:
    nonexistent = tmp_path / "nope.log"
    client = TestClient(main.app)
    with patch.object(audit, "AUDIT_LOG_PATH", str(nonexistent)):
        resp = client.get("/audit", headers={"X-Admin-Token": config.ADMIN_TOKEN})
    assert resp.status_code == 200
    assert resp.text == ""


# ---- audit.tail() helper ---------------------------------------------------


def test_tail_helper_returns_last_n(tmp_path) -> None:
    log = tmp_path / "audit.log"
    with open(log, "w", encoding="utf-8") as f:
        for i in range(10):
            f.write(f"l{i}\n")

    with patch.object(audit, "AUDIT_LOG_PATH", str(log)):
        out = audit.tail(3)
    assert out == ["l7", "l8", "l9"]


def test_tail_helper_missing_file_returns_empty(tmp_path) -> None:
    with patch.object(audit, "AUDIT_LOG_PATH", str(tmp_path / "nope.log")):
        assert audit.tail(50) == []


# ---- confirm / cancel logging at router ------------------------------------


@pytest.mark.asyncio
async def test_router_logs_user_confirm() -> None:
    from router import handle_message

    with (
        patch("router.run_claude", new=AsyncMock(return_value="ok")),
        patch("router.send_message", new=AsyncMock(return_value=True)),
        patch("router.log_action") as mock_log,
    ):
        await handle_message("+972542159121", "כן")

    actions = [c.args[1] for c in mock_log.call_args_list]
    assert "user_confirm" in actions


@pytest.mark.asyncio
async def test_router_logs_user_cancel_case_insensitive() -> None:
    from router import handle_message

    with (
        patch("router.run_claude", new=AsyncMock(return_value="ok")),
        patch("router.send_message", new=AsyncMock(return_value=True)),
        patch("router.log_action") as mock_log,
    ):
        await handle_message("+972542159121", "  CANCEL  ")

    actions = [c.args[1] for c in mock_log.call_args_list]
    assert "user_cancel" in actions


@pytest.mark.asyncio
async def test_router_does_not_log_for_ordinary_message() -> None:
    from router import handle_message

    with (
        patch("router.run_claude", new=AsyncMock(return_value="ok")),
        patch("router.send_message", new=AsyncMock(return_value=True)),
        patch("router.log_action") as mock_log,
    ):
        await handle_message("+972542159121", "תוסיף משימה")

    actions = [c.args[1] for c in mock_log.call_args_list]
    assert "user_confirm" not in actions
    assert "user_cancel" not in actions
