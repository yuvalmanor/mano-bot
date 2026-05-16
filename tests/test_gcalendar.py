"""Mocked unit tests for integrations.gcalendar.

Covers: missing/invalid token, refresh failure, HTTP error, timeout, happy
paths for create_event and list_upcoming_events, and agent dispatch (Yuval
allowed, Eden denied). No live API calls.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations import gcalendar


VALID_TOKEN_INFO = {
    "token": "ya29.fake-access",
    "refresh_token": "1//fake-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake-client-id",
    "client_secret": "fake-client-secret",
    "scopes": ["https://www.googleapis.com/auth/calendar.events"],
}


def _b64(info: dict) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


def _make_creds(valid: bool = True, token: str = "ya29.fake-access", refresh_token: str = "1//rt") -> MagicMock:
    creds = MagicMock()
    creds.valid = valid
    creds.token = token
    creds.refresh_token = refresh_token
    return creds


# ---- create_event ----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event_missing_token_env() -> None:
    with patch("integrations.gcalendar.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = ""
        ok = await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")
        assert ok is False


@pytest.mark.asyncio
async def test_create_event_invalid_base64() -> None:
    with patch("integrations.gcalendar.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = "!!!not-base64!!!"
        ok = await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")
        assert ok is False


@pytest.mark.asyncio
async def test_create_event_happy_path() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 200
        fake_post.captured = {"url": url, "headers": headers, "json": json}
        return resp

    fake_post.captured = {}

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gcalendar.create_event(
            "Dentist",
            "2026-05-20T14:00:00+03:00",
            "2026-05-20T15:00:00+03:00",
            description="cleaning",
        )
        assert ok is True

    captured = fake_post.captured
    assert captured["url"] == gcalendar.CALENDAR_API_BASE
    assert captured["headers"]["Authorization"] == "Bearer ya29.fake-access"
    body = captured["json"]
    assert body["summary"] == "Dentist"
    assert body["start"] == {"dateTime": "2026-05-20T14:00:00+03:00"}
    assert body["end"] == {"dateTime": "2026-05-20T15:00:00+03:00"}
    assert body["description"] == "cleaning"


@pytest.mark.asyncio
async def test_create_event_omits_description_when_none() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 200
        fake_post.captured = json
        return resp

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")

    assert "description" not in fake_post.captured


@pytest.mark.asyncio
async def test_create_event_refresh_when_invalid() -> None:
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
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")
        assert ok is True
        assert fake_post.captured_headers["Authorization"] == "Bearer ya29.refreshed"


@pytest.mark.asyncio
async def test_create_event_refresh_failure_returns_false() -> None:
    creds = _make_creds(valid=False, token=None, refresh_token="1//rt")

    def fake_refresh(_req):
        raise RuntimeError("refresh boom")

    creds.refresh = fake_refresh

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")
        assert ok is False


@pytest.mark.asyncio
async def test_create_event_http_error_returns_false() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        resp = MagicMock()
        resp.status_code = 403
        return resp

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")
        assert ok is False


@pytest.mark.asyncio
async def test_create_event_timeout_returns_false() -> None:
    creds = _make_creds(valid=True)

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002
        raise httpx.TimeoutException("slow")

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        ok = await gcalendar.create_event("t", "2026-05-20T14:00:00+03:00", "2026-05-20T15:00:00+03:00")
        assert ok is False


# ---- list_upcoming_events --------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_missing_token() -> None:
    with patch("integrations.gcalendar.config") as cfg:
        cfg.GOOGLE_TOKEN_PERSONAL = ""
        out = await gcalendar.list_upcoming_events()
        assert out == ""


@pytest.mark.asyncio
async def test_list_events_happy_path_formats_items() -> None:
    creds = _make_creds(valid=True)

    api_response = {
        "items": [
            {"summary": "Dentist", "start": {"dateTime": "2026-05-20T14:00:00+03:00"}},
            {"summary": "Birthday", "start": {"date": "2026-05-21"}},
            {"start": {"dateTime": "2026-05-22T09:00:00+03:00"}},  # missing summary
        ]
    }

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value=api_response)
        fake_get.captured = {"url": url, "headers": headers, "params": params}
        return resp

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await gcalendar.list_upcoming_events(days=3)

    assert "Dentist" in out
    assert "Birthday" in out
    assert "(ללא כותרת)" in out
    captured = fake_get.captured
    assert captured["params"]["singleEvents"] == "true"
    assert captured["params"]["orderBy"] == "startTime"
    assert captured["headers"]["Authorization"] == "Bearer ya29.fake-access"


@pytest.mark.asyncio
async def test_list_events_empty_returns_empty_string() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"items": []})
        return resp

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await gcalendar.list_upcoming_events()
        assert out == ""


@pytest.mark.asyncio
async def test_list_events_http_error_returns_empty() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 500
        return resp

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await gcalendar.list_upcoming_events()
        assert out == ""


@pytest.mark.asyncio
async def test_list_events_timeout_returns_empty() -> None:
    creds = _make_creds(valid=True)

    async def fake_get(self, url, headers=None, params=None):
        raise httpx.TimeoutException("slow")

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        out = await gcalendar.list_upcoming_events()
        assert out == ""


@pytest.mark.asyncio
async def test_list_events_never_logs_token_value(caplog) -> None:
    creds = _make_creds(valid=True, token="super-secret-cal-token-DO-NOT-LEAK")

    async def fake_get(self, url, headers=None, params=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"items": []})
        return resp

    with (
        patch("integrations.gcalendar.config") as cfg,
        patch(
            "integrations.gcalendar.Credentials.from_authorized_user_info",
            return_value=creds,
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        with caplog.at_level("DEBUG"):
            await gcalendar.list_upcoming_events()

    full_log = " ".join(r.getMessage() for r in caplog.records)
    assert "super-secret-cal-token-DO-NOT-LEAK" not in full_log


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
async def test_agent_dispatches_calendar_create_for_yuval() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.gcalendar.create_event",
            new=AsyncMock(return_value=True),
        ) as mock_create,
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
                            "calendar_create_event",
                            {
                                "title": "Dentist",
                                "start_datetime": "2026-05-20T14:00:00+03:00",
                                "end_datetime": "2026-05-20T15:00:00+03:00",
                                "description": "cleaning",
                            },
                        )
                    ],
                ),
                _resp("end_turn", [_text_block("נקבע")]),
            ]
        )

        reply = await run(phone, "תקבע פגישה אצל רופא השיניים")
        assert reply == "נקבע"
        mock_create.assert_awaited_once_with(
            title="Dentist",
            start_datetime="2026-05-20T14:00:00+03:00",
            end_datetime="2026-05-20T15:00:00+03:00",
            description="cleaning",
        )


@pytest.mark.asyncio
async def test_agent_dispatches_calendar_list_for_yuval() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.gcalendar.list_upcoming_events",
            new=AsyncMock(return_value="• 2026-05-20T14:00:00+03:00 — Dentist"),
        ) as mock_list,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _resp(
                    "tool_use",
                    [_tool_use("tu1", "calendar_list_events", {"days": 14})],
                ),
                _resp("end_turn", [_text_block("הנה הפגישות")]),
            ]
        )

        reply = await run(phone, "מה יש לי השבועיים הקרובים")
        assert reply == "הנה הפגישות"
        mock_list.assert_awaited_once_with(days=14)


@pytest.mark.asyncio
async def test_agent_denies_calendar_for_eden() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, run

    CONVERSATION_HISTORY.clear()
    phone = "+972546900908"  # Eden — no 'calendar'

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.gcalendar.create_event",
            new=AsyncMock(return_value=True),
        ) as mock_create,
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
                            "calendar_create_event",
                            {
                                "title": "x",
                                "start_datetime": "2026-05-20T14:00:00+03:00",
                                "end_datetime": "2026-05-20T15:00:00+03:00",
                            },
                        )
                    ],
                ),
                _resp("end_turn", [_text_block("אין הרשאה")]),
            ]
        )

        reply = await run(phone, "תקבע פגישה")
        assert reply == "אין הרשאה"
        mock_create.assert_not_awaited()
