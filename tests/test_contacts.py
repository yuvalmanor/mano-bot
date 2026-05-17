"""Mocked unit tests for integrations.contacts."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from integrations import contacts


VALID_TOKEN_INFO = {
    "token": "ya29.fake-access",
    "refresh_token": "1//rt",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "x",
    "client_secret": "y",
    "scopes": ["https://www.googleapis.com/auth/contacts.other.readonly"],
}


def _b64(info: dict) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


def _make_creds(valid: bool = True, token: str = "ya29.fake-access") -> MagicMock:
    c = MagicMock()
    c.valid = valid
    c.token = token
    c.refresh_token = "1//rt"
    return c


def _ok_resp(body: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = body
    return r


@pytest.mark.asyncio
async def test_lookup_contact_no_token() -> None:
    with patch("integrations.gmail.config") as cfg:
        cfg.GOOGLE_TOKEN_CGM = ""
        res = await contacts.lookup_contact("alice", account_key="cgm")
        assert res == []


@pytest.mark.asyncio
async def test_lookup_contact_merges_and_dedupes() -> None:
    saved = {
        "results": [
            {
                "person": {
                    "names": [{"displayName": "Alice Saved"}],
                    "emailAddresses": [{"value": "alice@x.com"}],
                }
            }
        ]
    }
    other = {
        "results": [
            {
                "person": {
                    "names": [{"displayName": "Alice Other"}],
                    "emailAddresses": [{"value": "alice@x.com"}],  # dup
                }
            },
            {
                "person": {
                    "names": [{"displayName": "Bob"}],
                    "emailAddresses": [{"value": "bob@y.com"}],
                }
            },
        ]
    }

    calls = []

    async def fake_get(self, url, headers=None, params=None):
        calls.append(url)
        if "otherContacts" in url:
            return _ok_resp(other)
        return _ok_resp(saved)

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=_make_creds(),
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        res = await contacts.lookup_contact("alice", account_key="cgm")

    assert {(r["name"], r["email"]) for r in res} == {
        ("Alice Saved", "alice@x.com"),
        ("Bob", "bob@y.com"),
    }
    assert any("people:searchContacts" in u for u in calls)
    assert any("otherContacts:search" in u for u in calls)


@pytest.mark.asyncio
async def test_lookup_contact_timeout_returns_empty() -> None:
    async def fake_get(self, url, headers=None, params=None):
        raise httpx.TimeoutException("slow")

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=_make_creds(),
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        res = await contacts.lookup_contact("alice", account_key="cgm")
        assert res == []


@pytest.mark.asyncio
async def test_lookup_contact_skips_4xx_but_keeps_other_endpoint() -> None:
    saved_resp = MagicMock()
    saved_resp.status_code = 403
    saved_resp.request = MagicMock()
    saved_resp.request.url.path = "/v1/people:searchContacts"

    other_body = {
        "results": [
            {
                "person": {
                    "names": [{"displayName": "Carol"}],
                    "emailAddresses": [{"value": "carol@z.com"}],
                }
            }
        ]
    }

    async def fake_get(self, url, headers=None, params=None):
        if "otherContacts" in url:
            return _ok_resp(other_body)
        return saved_resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=_make_creds(),
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        res = await contacts.lookup_contact("carol", account_key="cgm")

    assert res == [{"name": "Carol", "email": "carol@z.com"}]


@pytest.mark.asyncio
async def test_lookup_contact_ignores_entries_with_no_email() -> None:
    body = {
        "results": [
            {"person": {"names": [{"displayName": "NoEmail"}]}},
            {
                "person": {
                    "names": [{"displayName": "Dan"}],
                    "emailAddresses": [{"value": "dan@x.com"}],
                }
            },
        ]
    }

    async def fake_get(self, url, headers=None, params=None):
        return _ok_resp(body)

    with (
        patch("integrations.gmail.config") as cfg,
        patch(
            "integrations.gmail.Credentials.from_authorized_user_info",
            return_value=_make_creds(),
        ),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        res = await contacts.lookup_contact("d", account_key="cgm")

    assert res == [{"name": "Dan", "email": "dan@x.com"}]
