"""Mocked unit tests for integrations.gmail.

Covers: bad account key, missing/invalid token, refresh failure, HTTP 4xx/5xx,
timeout, and the happy path including RFC822 base64url encoding of the message.
No live API calls.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations import gmail


VALID_TOKEN_INFO = {
    "token": "ya29.fake-access",
    "refresh_token": "1//fake-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id",
    "client_secret": "fake-client-secret",
    "scopes": ["https://www.googleapis.com/auth/gmail.send"],
}


def _b64(info: dict) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


def _make_creds(valid: bool = True, token: str = "ya29.fake-access", refresh_token: str = "1//rt") -> MagicMock:
    creds = MagicMock()
    creds.valid = valid
    creds.token = token
    creds.refresh_token = refresh_token
    return creds


@pytest.mark.asyncio
async def test_send_email_bad_account_key() -> None:
    ok = await gmail.send_email("a@b.com", "s", "b", account_key="bogus")
    assert ok is False


@pytest.mark.asyncio
async def test_send_email_missing_token_env() -> None:
    with patch("integrations.gmail.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = ""
        ok = await gmail.send_email("a@b.com", "s", "b", account_key="personal")
        assert ok is False


@pytest.mark.asyncio
async def test_send_email_invalid_base64() -> None:
    with patch("integrations.gmail.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = "!!!not-base64!!!"
        ok = await gmail.send_email("a@b.com", "s", "b", account_key="personal")
        assert ok is False


@pytest.mark.asyncio
async def test_send_email_invalid_json_in_token() -> None:
    with patch("integrations.gmail.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = base64.b64encode(b"not json").decode()
        ok = await gmail.send_email("a@b.com", "s", "b", account_key="personal")
        assert ok is False


@pytest.mark.asyncio
async def test_send_email_happy_path() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 200
        # Snapshot what was sent for assertion below.
        fake_post.captured = {"url": url, "headers": headers, "json": json}
        return resp

    fake_post.captured = {}

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gmail.send_email(
            "alice@example.com", "hello", "body text", account_key="personal"
        )
        assert ok is True

    captured = fake_post.captured
    assert captured["url"] == gmail.GMAIL_SEND_URL
    assert captured["headers"]["Authorization"] == "Bearer ya29.fake-access"
    raw_b64 = captured["json"]["raw"]
    # Must be urlsafe base64; decoding yields RFC822 with our fields.
    decoded = base64.urlsafe_b64decode(raw_b64.encode()).decode()
    assert "To: alice@example.com" in decoded
    assert "Subject: hello" in decoded
    assert "body text" in decoded


@pytest.mark.asyncio
async def test_send_email_refresh_when_invalid() -> None:
    creds = _make_creds(valid=False, token=None, refresh_token="1//rt")

    def fake_refresh(_req):
        creds.token = "ya29.refreshed"
        creds.valid = True

    creds.refresh = fake_refresh

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 200
        fake_post.captured_headers = headers
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        ok = await gmail.send_email("x@y.com", "s", "b", account_key="cgm")
        assert ok is True
        assert fake_post.captured_headers["Authorization"] == "Bearer ya29.refreshed"


@pytest.mark.asyncio
async def test_send_email_refresh_failure_returns_false() -> None:
    creds = _make_creds(valid=False, token=None, refresh_token="1//rt")

    def fake_refresh(_req):
        raise RuntimeError("refresh boom")

    creds.refresh = fake_refresh

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
    ):
        cfg.GOOGLE_TOKEN_DEALS = _b64(VALID_TOKEN_INFO)
        ok = await gmail.send_email("x@y.com", "s", "b", account_key="deals")
        assert ok is False


@pytest.mark.asyncio
async def test_send_email_http_error_returns_false() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 403
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gmail.send_email("x@y.com", "s", "b", account_key="personal")
        assert ok is False


@pytest.mark.asyncio
async def test_send_email_timeout_returns_false() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        raise httpx.TimeoutException("slow")

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gmail.send_email("x@y.com", "s", "b", account_key="personal")
        assert ok is False


@pytest.mark.asyncio
async def test_send_email_never_logs_token_value(caplog) -> None:
    creds = _make_creds(valid=True, token="super-secret-token-DO-NOT-LEAK")

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 200
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        with caplog.at_level("DEBUG"):
            await gmail.send_email("x@y.com", "s", "b", account_key="personal")

    full_log = " ".join(r.getMessage() for r in caplog.records)
    assert "super-secret-token-DO-NOT-LEAK" not in full_log


# ---- search_inbox ---------------------------------------------------------


@pytest.mark.asyncio
async def test_search_inbox_bad_account() -> None:
    out = await gmail.search_inbox("anything", account_key="bogus")
    assert out == ""


@pytest.mark.asyncio
async def test_search_inbox_happy_path_formats_summary() -> None:
    creds = _make_creds(valid=True)

    list_body = {"messages": [{"id": "m1"}, {"id": "m2"}]}
    msg1 = {
        "snippet": "first snippet",
        "payload": {
            "headers": [
                {"name": "From", "value": "alice@x.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Date", "value": "Mon, 1 Jan 2026"},
            ]
        },
    }
    msg2 = {
        "snippet": "second snippet",
        "payload": {
            "headers": [
                {"name": "From", "value": "bob@y.com"},
                {"name": "Subject", "value": "Invoice"},
                {"name": "Date", "value": "Tue, 2 Jan 2026"},
            ]
        },
    }

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        if url.endswith("/messages"):
            resp.json.return_value = list_body
        elif url.endswith("/m1"):
            resp.json.return_value = msg1
        elif url.endswith("/m2"):
            resp.json.return_value = msg2
        else:
            resp.json.return_value = {}
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        out = await gmail.search_inbox("from:alice", account_key="cgm")

    assert "Hello" in out
    assert "alice@x.com" in out
    assert "first snippet" in out
    assert "Invoice" in out
    assert "bob@y.com" in out


@pytest.mark.asyncio
async def test_search_inbox_empty_list_returns_empty_string() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {}  # no "messages" key
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        out = await gmail.search_inbox("nothing-matches", account_key="cgm")

    assert out == ""


@pytest.mark.asyncio
async def test_search_inbox_list_http_error_returns_empty() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 403
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        out = await gmail.search_inbox("x", account_key="cgm")

    assert out == ""


def test_scope_query_empty_gets_primary_inbox() -> None:
    assert gmail._scope_query_to_primary_inbox("") == "in:inbox category:primary"


def test_scope_query_keyword_gets_primary_inbox_prefix() -> None:
    assert (
        gmail._scope_query_to_primary_inbox("invoice")
        == "in:inbox category:primary invoice"
    )


def test_scope_query_respects_explicit_in() -> None:
    # User explicitly chose another location (e.g. sent) — don't override.
    out = gmail._scope_query_to_primary_inbox("in:sent")
    assert "in:inbox" not in out
    assert "category:primary" in out


def test_scope_query_respects_explicit_category() -> None:
    out = gmail._scope_query_to_primary_inbox("category:promotions")
    assert "category:primary" not in out
    assert "in:inbox" in out


def test_scope_query_respects_label_filter() -> None:
    out = gmail._scope_query_to_primary_inbox("label:work")
    assert "in:inbox" not in out


@pytest.mark.asyncio
async def test_search_inbox_query_scoped_to_primary_in_api_call() -> None:
    creds = _make_creds(valid=True)
    captured = {}

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        if url.endswith("/messages"):
            captured["q"] = params.get("q")
            resp.json.return_value = {}
        else:
            resp.json.return_value = {}
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        await gmail.search_inbox("", account_key="cgm")

    assert captured["q"] == "in:inbox category:primary"


@pytest.mark.asyncio
async def test_search_inbox_timeout_returns_empty() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        raise httpx.TimeoutException("slow")

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        out = await gmail.search_inbox("x", account_key="cgm")

    assert out == ""


# ---- Agent dispatch integration -------------------------------------------


@pytest.mark.asyncio
async def test_agent_dispatches_gmail_tool_for_authorized_user() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"  # Yuval — has 'gmail'

    def text_block(t):
        b = MagicMock()
        b.type = "text"
        b.text = t
        return b

    def tool_use(tid, name, inp):
        b = MagicMock()
        b.type = "tool_use"
        b.id = tid
        b.name = name
        b.input = inp
        return b

    def resp(stop, content):
        r = MagicMock()
        r.stop_reason = stop
        r.content = content
        return r

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.gmail.send_email", new=AsyncMock(return_value=True)
        ) as mock_send,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                resp(
                    "tool_use",
                    [
                        tool_use(
                            "tu1",
                            "gmail_send_email",
                            {
                                "to": "a@b.com",
                                "subject": "Hi",
                                "body": "hey",
                                "account_key": "personal",
                            },
                        )
                    ],
                ),
                resp("end_turn", [text_block("נשלח")]),
            ]
        )

        reply = await run(phone, "תשלח מייל ל-a@b.com")
        assert reply == "נשלח"
        mock_send.assert_awaited_once_with(
            to="a@b.com", subject="Hi", body="hey", account_key="personal"
        )


@pytest.mark.asyncio
async def test_agent_denies_gmail_tool_for_eden() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972546900908"  # Eden — no 'gmail' permission

    def text_block(t):
        b = MagicMock()
        b.type = "text"
        b.text = t
        return b

    def tool_use(tid, name, inp):
        b = MagicMock()
        b.type = "tool_use"
        b.id = tid
        b.name = name
        b.input = inp
        return b

    def resp(stop, content):
        r = MagicMock()
        r.stop_reason = stop
        r.content = content
        return r

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.gmail.send_email", new=AsyncMock(return_value=True)
        ) as mock_send,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                resp(
                    "tool_use",
                    [
                        tool_use(
                            "tu1",
                            "gmail_send_email",
                            {
                                "to": "a@b.com",
                                "subject": "x",
                                "body": "x",
                                "account_key": "personal",
                            },
                        )
                    ],
                ),
                resp("end_turn", [text_block("אין הרשאה")]),
            ]
        )

        reply = await run(phone, "תשלח מייל")
        assert reply == "אין הרשאה"
        mock_send.assert_not_awaited()
