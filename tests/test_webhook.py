"""Tests for whatsapp.webhook, whatsapp.client, security.auth, and main.

All HTTP is mocked — no live server, no outbound network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import config
import main
from whatsapp.client import send_message
from whatsapp.webhook import parse_incoming
from security.auth import verify_webhook_signature


# ---------------------------------------------------------------------------
# parse_incoming
# ---------------------------------------------------------------------------

def _text_payload(text: str = "hello", phone: str = "+972542159121") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": "wamid.ABC",
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


def test_parse_incoming_extracts_text_message() -> None:
    parsed = parse_incoming(_text_payload("שלום"))
    assert parsed == {
        "from_phone": "+972542159121",
        "message_type": "text",
        "text": "שלום",
        "message_id": "wamid.ABC",
    }


def test_parse_incoming_ignores_status_updates() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {"value": {"statuses": [{"id": "wamid.X", "status": "delivered"}]}}
                ]
            }
        ]
    }
    assert parse_incoming(payload) is None


def test_parse_incoming_ignores_non_text_messages() -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "+972542159121",
                                    "id": "wamid.IMG",
                                    "type": "image",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert parse_incoming(payload) is None


@pytest.mark.parametrize("payload", [None, {}, {"entry": []}, {"foo": "bar"}, "string"])
def test_parse_incoming_malformed_returns_none(payload) -> None:
    assert parse_incoming(payload) is None


# ---------------------------------------------------------------------------
# send_message (httpx mocked)
# ---------------------------------------------------------------------------

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _client_with_transport(transport: httpx.MockTransport):
    """Return a callable that mimics ``httpx.AsyncClient(...)`` but always uses ``transport``.

    Uses a captured reference to the real class so it works under
    ``patch("whatsapp.client.httpx.AsyncClient")``, which patches the class
    globally on the ``httpx`` module.
    """
    def _factory(*_args, **_kwargs) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=transport, timeout=10.0)
    return _factory


@pytest.mark.asyncio
async def test_send_message_success() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]})
    )
    with patch("whatsapp.client.httpx.AsyncClient", side_effect=_client_with_transport(transport)):
        ok = await send_message("+972542159121", "echo")
    assert ok is True


@pytest.mark.asyncio
async def test_send_message_http_error_returns_false() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "x"}))
    with patch("whatsapp.client.httpx.AsyncClient", side_effect=_client_with_transport(transport)):
        ok = await send_message("+972542159121", "echo")
    assert ok is False


@pytest.mark.asyncio
async def test_send_message_timeout_returns_false() -> None:
    def _raise_timeout(req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=req)

    transport = httpx.MockTransport(_raise_timeout)
    with patch("whatsapp.client.httpx.AsyncClient", side_effect=_client_with_transport(transport)):
        ok = await send_message("+972542159121", "echo")
    assert ok is False


@pytest.mark.asyncio
async def test_send_message_does_not_log_token(caplog) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    with patch("whatsapp.client.httpx.AsyncClient", side_effect=_client_with_transport(transport)):
        await send_message("+972542159121", "echo")
    assert config.WHATSAPP_ACCESS_TOKEN not in caplog.text


# ---------------------------------------------------------------------------
# verify_webhook_signature
# ---------------------------------------------------------------------------

def _sign(body: bytes) -> str:
    digest = hmac.new(
        config.WHATSAPP_APP_SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_accepts_valid() -> None:
    body = b'{"hello":"world"}'
    assert verify_webhook_signature(body, _sign(body)) is True


def test_verify_signature_rejects_invalid() -> None:
    assert verify_webhook_signature(b"{}", "sha256=deadbeef") is False


def test_verify_signature_rejects_missing_header() -> None:
    assert verify_webhook_signature(b"{}", None) is False
    assert verify_webhook_signature(b"{}", "") is False


def test_verify_signature_rejects_wrong_prefix() -> None:
    assert verify_webhook_signature(b"{}", "sha1=abcd") is False


# ---------------------------------------------------------------------------
# GET /webhook verification handshake
# ---------------------------------------------------------------------------

def test_get_webhook_returns_challenge_on_valid_token() -> None:
    client = TestClient(main.app)
    resp = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": config.WHATSAPP_VERIFY_TOKEN,
            "hub.challenge": "12345",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_get_webhook_rejects_wrong_token() -> None:
    client = TestClient(main.app)
    resp = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "12345",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /webhook end-to-end with mocked send_message
# ---------------------------------------------------------------------------

def test_post_webhook_rejects_invalid_signature() -> None:
    client = TestClient(main.app)
    body = json.dumps(_text_payload("hi")).encode("utf-8")
    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )
    assert resp.status_code == 403


def test_post_webhook_handles_text_message() -> None:
    fake_handler = AsyncMock()
    with patch("router.handle_message", fake_handler):
        client = TestClient(main.app)
        body = json.dumps(_text_payload("שלום", "+972542159121")).encode("utf-8")
        resp = client.post(
            "/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200
    fake_handler.assert_called_once_with("+972542159121", "שלום")


def test_post_webhook_ignores_status_update() -> None:
    fake_handler = AsyncMock()
    status_payload = {
        "entry": [
            {
                "changes": [
                    {"value": {"statuses": [{"id": "x", "status": "delivered"}]}}
                ]
            }
        ]
    }
    body = json.dumps(status_payload).encode("utf-8")
    with patch("router.handle_message", fake_handler):
        client = TestClient(main.app)
        resp = client.post(
            "/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200
    fake_handler.assert_not_called()


def test_post_webhook_non_json_body_returns_200() -> None:
    body = b"not json"
    client = TestClient(main.app)
    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 200
