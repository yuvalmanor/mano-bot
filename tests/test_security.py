"""Tests for the security layer: auth, rate limiter, audit, dedup, kill switch."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import config
import main
from security import rate_limiter
from security.audit import AUDIT_LOG_PATH, log_action
from security.auth import authorize_sender


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _text_payload(text: str, phone: str, message_id: str = "wamid.ABC") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": message_id,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _sign(body: bytes) -> str:
    digest = hmac.new(
        config.WHATSAPP_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# authorize_sender
# ---------------------------------------------------------------------------

def test_authorize_sender_allows_registered() -> None:
    assert authorize_sender("+972542159121") is True


def test_authorize_sender_denies_unknown(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "audit.log"
    monkeypatch.setattr("security.auth.log_action", lambda *a, **k: log_file.write_text("denied"))
    assert authorize_sender("+15555555555") is False
    assert log_file.read_text() == "denied"


# ---------------------------------------------------------------------------
# rate limiter
# ---------------------------------------------------------------------------

def test_rate_limit_allows_under_threshold() -> None:
    phone = "+972500000001"
    for _ in range(rate_limiter.MAX_MESSAGES):
        assert rate_limiter.check_rate_limit(phone) is True


def test_rate_limit_blocks_over_threshold() -> None:
    phone = "+972500000002"
    for _ in range(rate_limiter.MAX_MESSAGES):
        rate_limiter.check_rate_limit(phone)
    assert rate_limiter.check_rate_limit(phone) is False


def test_rate_limit_isolated_per_phone() -> None:
    a, b = "+972500000003", "+972500000004"
    for _ in range(rate_limiter.MAX_MESSAGES):
        rate_limiter.check_rate_limit(a)
    assert rate_limiter.check_rate_limit(a) is False
    assert rate_limiter.check_rate_limit(b) is True


def test_rate_limit_window_expires(monkeypatch) -> None:
    phone = "+972500000005"
    fake_time = [1000.0]
    monkeypatch.setattr(rate_limiter.time, "monotonic", lambda: fake_time[0])
    for _ in range(rate_limiter.MAX_MESSAGES):
        rate_limiter.check_rate_limit(phone)
    assert rate_limiter.check_rate_limit(phone) is False
    fake_time[0] += rate_limiter.WINDOW_SECONDS + 1
    assert rate_limiter.check_rate_limit(phone) is True


def test_rate_limit_message_is_hebrew() -> None:
    msg = rate_limiter.get_rate_limit_message()
    assert any("֐" <= ch <= "׿" for ch in msg)


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------

def test_audit_writes_masked_phone(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "audit.log"
    monkeypatch.setattr("security.audit.AUDIT_LOG_PATH", str(log_path))
    log_action("+972542159121", "test_action", "some details", "ok")
    text = log_path.read_text(encoding="utf-8")
    assert "+972542159121" not in text
    assert "****9121" in text
    assert "action=test_action" in text
    assert "status=ok" in text


def test_audit_swallows_oserror(monkeypatch) -> None:
    monkeypatch.setattr("security.audit.AUDIT_LOG_PATH", "/no/such/dir/audit.log")
    # Must not raise.
    log_action("+972542159121", "x", "y", "z")


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------

def test_is_duplicate_first_call_false_then_true() -> None:
    assert main.is_duplicate("wamid.NEW") is False
    assert main.is_duplicate("wamid.NEW") is True


def test_is_duplicate_fifo_eviction() -> None:
    cap = main.SEEN_MESSAGE_IDS_QUEUE.maxlen
    for i in range(cap):
        main.is_duplicate(f"id-{i}")
    # Adding one more evicts id-0.
    main.is_duplicate("id-overflow")
    assert "id-0" not in main.SEEN_MESSAGE_IDS
    assert main.is_duplicate("id-0") is False  # Treated as new again.


# ---------------------------------------------------------------------------
# POST /webhook pipeline
# ---------------------------------------------------------------------------

def test_post_webhook_unknown_sender_silent_200() -> None:
    fake_handler = AsyncMock()
    body = json.dumps(_text_payload("hi", "+15555555555")).encode("utf-8")
    with patch("router.handle_message", fake_handler):
        client = TestClient(main.app)
        resp = client.post(
            "/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200
    fake_handler.assert_not_called()


def test_post_webhook_dedup_skips_second_delivery() -> None:
    fake_handler = AsyncMock()
    body = json.dumps(_text_payload("hi", "+972542159121", "wamid.DUP")).encode("utf-8")
    sig = _sign(body)
    with patch("router.handle_message", fake_handler):
        client = TestClient(main.app)
        r1 = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
        r2 = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r1.status_code == 200 and r2.status_code == 200
    fake_handler.assert_called_once()


def test_post_webhook_rate_limited_sends_warning() -> None:
    phone = "+972542159121"
    fake_handler = AsyncMock()
    fake_send = AsyncMock(return_value=True)
    # Pre-fill the rate limiter to exhaust the quota.
    for _ in range(rate_limiter.MAX_MESSAGES):
        rate_limiter.check_rate_limit(phone)
    body = json.dumps(_text_payload("hi", phone, "wamid.RL")).encode("utf-8")
    with patch("router.handle_message", fake_handler), \
         patch("main.send_message", fake_send):
        client = TestClient(main.app)
        resp = client.post(
            "/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200
    fake_handler.assert_not_called()
    fake_send.assert_called_once()
    assert fake_send.call_args.args[0] == phone


def test_post_webhook_bot_disabled_returns_200_and_skips(monkeypatch) -> None:
    fake_handler = AsyncMock()
    monkeypatch.setattr(config, "BOT_ENABLED", False)
    body = json.dumps(_text_payload("hi", "+972542159121", "wamid.OFF")).encode("utf-8")
    with patch("router.handle_message", fake_handler):
        client = TestClient(main.app)
        resp = client.post(
            "/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200
    fake_handler.assert_not_called()
