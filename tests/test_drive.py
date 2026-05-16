"""Mocked unit tests for integrations.drive.

Covers: bad account key, missing/invalid token, refresh failure, HTTP error,
timeout, happy path with formatting, query escaping, empty result, and agent
dispatch (Yuval allowed, Eden denied). No live API calls.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations import drive


VALID_TOKEN_INFO = {
    "token": "ya29.fake-access",
    "refresh_token": "1//fake-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id",
    "client_secret": "fake-client-secret",
    "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
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
async def test_search_bad_account_key() -> None:
    out = await drive.search_files("foo", account_key="bogus")
    assert out == ""


@pytest.mark.asyncio
async def test_search_missing_token() -> None:
    with patch("integrations.drive.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = ""
        out = await drive.search_files("foo", account_key="personal")
        assert out == ""


@pytest.mark.asyncio
async def test_search_invalid_base64() -> None:
    with patch("integrations.drive.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = "!!!not-base64!!!"
        out = await drive.search_files("foo", account_key="personal")
        assert out == ""


@pytest.mark.asyncio
async def test_search_happy_path_formats_results() -> None:
    creds = _make_creds(valid=True)
    api_response = {
        "files": [
            {"id": "1", "name": "Q1 plan.pdf", "webViewLink": "https://drive.google.com/file/d/1/view"},
            {"id": "2", "name": "no-link.txt"},
        ]
    }

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value=api_response)
        fake_get.captured = {"url": url, "headers": headers, "params": params}
        return resp

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_DEALS = _b64(VALID_TOKEN_INFO)
        out = await drive.search_files("plan", account_key="deals")

    assert "Q1 plan.pdf" in out
    assert "https://drive.google.com/file/d/1/view" in out
    assert "no-link.txt" in out
    captured = fake_get.captured
    assert captured["url"] == drive.DRIVE_FILES_URL
    assert captured["headers"]["Authorization"] == "Bearer ya29.fake-access"
    assert "name contains 'plan'" in captured["params"]["q"]
    assert "trashed = false" in captured["params"]["q"]


@pytest.mark.asyncio
async def test_search_escapes_quotes_in_query() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"files": []})
        fake_get.captured_q = params["q"]
        return resp

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        await drive.search_files("O'Brien", account_key="personal")

    # The unescaped apostrophe must not appear; the escaped form must.
    assert "O\\'Brien" in fake_get.captured_q


@pytest.mark.asyncio
async def test_search_empty_results_returns_empty_string() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"files": []})
        return resp

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await drive.search_files("nope", account_key="personal")
        assert out == ""


@pytest.mark.asyncio
async def test_search_refresh_when_invalid() -> None:
    creds = _make_creds(valid=False, token=None, refresh_token="1//rt")

    def fake_refresh(_req):
        creds.token = "ya29.refreshed"
        creds.valid = True

    creds.refresh = fake_refresh

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"files": []})
        fake_get.captured_headers = headers
        return resp

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        await drive.search_files("x", account_key="cgm")
        assert fake_get.captured_headers["Authorization"] == "Bearer ya29.refreshed"


@pytest.mark.asyncio
async def test_search_refresh_failure_returns_empty() -> None:
    creds = _make_creds(valid=False, token=None, refresh_token="1//rt")

    def fake_refresh(_req):
        raise RuntimeError("boom")

    creds.refresh = fake_refresh

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await drive.search_files("x", account_key="personal")
        assert out == ""


@pytest.mark.asyncio
async def test_search_http_error_returns_empty() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 500
        return resp

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await drive.search_files("x", account_key="personal")
        assert out == ""


@pytest.mark.asyncio
async def test_search_timeout_returns_empty() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        raise httpx.TimeoutException("slow")

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await drive.search_files("x", account_key="personal")
        assert out == ""


@pytest.mark.asyncio
async def test_search_never_logs_token_value(caplog) -> None:
    creds = _make_creds(valid=True, token="super-secret-drive-DO-NOT-LEAK")

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"files": []})
        return resp

    with (
        patch("integrations.drive.config") as cfg,
        patch(
            "integrations.drive.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        with caplog.at_level("DEBUG"):
            await drive.search_files("x", account_key="personal")

    full_log = " ".join(r.getMessage() for r in caplog.records)
    assert "super-secret-drive-DO-NOT-LEAK" not in full_log


# ---- Agent dispatch --------------------------------------------------------


def _text_block(t):
    b = MagicMock()
    b.type = "text"
    b.text = t
    return b


def _tool_use(tid, name, inp):
    b = MagicMock()
    b.type = "tool_use"
    b.id = tid
    b.name = name
    b.input = inp
    return b


def _resp(stop, content):
    r = MagicMock()
    r.stop_reason = stop
    r.content = content
    return r


@pytest.mark.asyncio
async def test_agent_dispatches_drive_search_for_yuval() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.drive.search_files",
            new=AsyncMock(return_value="• Q1.pdf — https://x"),
        ) as mock_search,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _resp(
                    "tool_use",
                    [
                        _tool_use(
                            "tu1",
                            "drive_search_files",
                            {"query": "Q1", "account_key": "deals"},
                        )
                    ],
                ),
                _resp("end_turn", [_text_block("מצאתי")]),
            ]
        )

        reply = await run(phone, "תחפש לי קובץ Q1 ב-deals")
        assert reply == "מצאתי"
        mock_search.assert_awaited_once_with(query="Q1", account_key="deals")


@pytest.mark.asyncio
async def test_agent_denies_drive_for_eden() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972546900908"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.drive.search_files",
            new=AsyncMock(return_value="• Q1.pdf — https://x"),
        ) as mock_search,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _resp(
                    "tool_use",
                    [
                        _tool_use(
                            "tu1",
                            "drive_search_files",
                            {"query": "Q1", "account_key": "personal"},
                        )
                    ],
                ),
                _resp("end_turn", [_text_block("אין הרשאה")]),
            ]
        )

        reply = await run(phone, "תחפש קובץ")
        assert reply == "אין הרשאה"
        mock_search.assert_not_awaited()
