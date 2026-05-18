"""Per-user Google account resolution (Task 6d).

The integration layer must pick the right token based on (account_key,
user_phone): Eden's ``cgm`` → her own ``GOOGLE_TOKEN_EDEN_CGM``; Yuval's
``cgm`` → ``GOOGLE_TOKEN_CGM``. Eden has no ``personal`` / ``deals``, so those
must resolve to None and fail closed. ``user_phone=None`` falls back to
Yuval's tokens for service-internal callers.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from integrations import contacts, drive, gmail
from users import get_google_token_env_name

YUVAL = "+972542159121"
EDEN = "+972546900908"

VALID_TOKEN_INFO = {
    "token": "ya29.fake",
    "refresh_token": "1//rt",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "fake",
    "client_secret": "fake",
    "scopes": ["https://www.googleapis.com/auth/gmail.send"],
}


def _b64(info: dict) -> str:
    return base64.b64encode(json.dumps(info).encode()).decode()


def _make_creds() -> MagicMock:
    creds = MagicMock()
    creds.valid = True
    creds.token = "ya29.fake"
    creds.refresh_token = "1//rt"
    return creds


# --- users.get_google_token_env_name ---------------------------------------

def test_resolution_yuval_all_three_accounts() -> None:
    assert get_google_token_env_name(YUVAL, "personal") == "GOOGLE_TOKEN_PERSONAL"
    assert get_google_token_env_name(YUVAL, "cgm") == "GOOGLE_TOKEN_CGM"
    assert get_google_token_env_name(YUVAL, "deals") == "GOOGLE_TOKEN_DEALS"


def test_resolution_eden_only_cgm() -> None:
    assert get_google_token_env_name(EDEN, "cgm") == "GOOGLE_TOKEN_EDEN_CGM"
    assert get_google_token_env_name(EDEN, "personal") is None
    assert get_google_token_env_name(EDEN, "deals") is None


def test_resolution_unknown_phone_returns_none() -> None:
    assert get_google_token_env_name("+9990000000", "cgm") is None


def test_resolution_none_phone_falls_back_to_yuval() -> None:
    # Service-internal callers (pre-6d code paths) get Yuval's tokens.
    assert get_google_token_env_name(None, "personal") == "GOOGLE_TOKEN_PERSONAL"
    assert get_google_token_env_name(None, "cgm") == "GOOGLE_TOKEN_CGM"


# --- gmail.send_email — Eden uses her token, not Yuval's ------------------

@pytest.mark.asyncio
async def test_gmail_send_eden_uses_eden_cgm_token() -> None:
    creds = _make_creds()
    seen_token_raw: dict[str, str | None] = {"raw": None}

    def fake_from_info(info, scopes=None):  # noqa: ARG001
        seen_token_raw["raw"] = info.get("token")
        return creds

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002, ARG001
        resp = MagicMock()
        resp.status_code = 200
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch("integrations.gmail.Credentials.from_authorized_user_info", side_effect=fake_from_info),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        # Distinguishable tokens per env var so we can assert Eden's was used.
        cfg.GOOGLE_TOKEN_CGM = _b64({**VALID_TOKEN_INFO, "token": "yuval-cgm"})
        cfg.GOOGLE_TOKEN_EDEN_CGM = _b64({**VALID_TOKEN_INFO, "token": "eden-cgm"})

        ok = await gmail.send_email(
            "x@y.com", "s", "b", account_key="cgm", user_phone=EDEN
        )
        assert ok is True
        assert seen_token_raw["raw"] == "eden-cgm"


@pytest.mark.asyncio
async def test_gmail_send_yuval_cgm_unchanged() -> None:
    creds = _make_creds()
    seen_token_raw: dict[str, str | None] = {"raw": None}

    def fake_from_info(info, scopes=None):  # noqa: ARG001
        seen_token_raw["raw"] = info.get("token")
        return creds

    async def fake_post(self, url, headers=None, json=None):  # noqa: A002, ARG001
        resp = MagicMock()
        resp.status_code = 200
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch("integrations.gmail.Credentials.from_authorized_user_info", side_effect=fake_from_info),
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64({**VALID_TOKEN_INFO, "token": "yuval-cgm"})
        cfg.GOOGLE_TOKEN_EDEN_CGM = _b64({**VALID_TOKEN_INFO, "token": "eden-cgm"})

        ok = await gmail.send_email(
            "x@y.com", "s", "b", account_key="cgm", user_phone=YUVAL
        )
        assert ok is True
        assert seen_token_raw["raw"] == "yuval-cgm"


@pytest.mark.asyncio
async def test_gmail_send_eden_personal_no_token() -> None:
    # Eden has no personal account — must fail closed, not fall through to Yuval.
    # No config patching needed: the user-record lookup returns None for
    # (Eden, "personal"), so we never touch config at all.
    ok = await gmail.send_email(
        "x@y.com", "s", "b", account_key="personal", user_phone=EDEN
    )
    assert ok is False


@pytest.mark.asyncio
async def test_gmail_send_eden_no_eden_token_configured() -> None:
    # Even with EDEN_CGM empty, must fail rather than use Yuval's CGM token.
    with patch("integrations.gmail.config") as cfg:
        cfg.GOOGLE_TOKEN_EDEN_CGM = ""
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        ok = await gmail.send_email(
            "x@y.com", "s", "b", account_key="cgm", user_phone=EDEN
        )
        assert ok is False


# --- contacts.lookup_contact — same routing rule --------------------------

@pytest.mark.asyncio
async def test_contacts_eden_uses_eden_cgm_token() -> None:
    creds = _make_creds()
    seen_token_raw: dict[str, str | None] = {"raw": None}

    def fake_from_info(info, scopes=None):  # noqa: ARG001
        seen_token_raw["raw"] = info.get("token")
        return creds

    async def fake_get(self, url, headers=None, params=None):  # noqa: A002, ARG001
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"results": []})
        return resp

    with (
        patch("integrations.gmail.config") as cfg,
        patch("integrations.gmail.Credentials.from_authorized_user_info", side_effect=fake_from_info),
        patch.object(httpx.AsyncClient, "get", new=fake_get),
    ):
        cfg.GOOGLE_TOKEN_CGM = _b64({**VALID_TOKEN_INFO, "token": "yuval-cgm"})
        cfg.GOOGLE_TOKEN_EDEN_CGM = _b64({**VALID_TOKEN_INFO, "token": "eden-cgm"})

        results = await contacts.lookup_contact(
            "alice", account_key="cgm", user_phone=EDEN
        )
        assert results == []
        assert seen_token_raw["raw"] == "eden-cgm"


# --- drive.search_files — same routing rule -------------------------------

@pytest.mark.asyncio
async def test_drive_eden_personal_no_token() -> None:
    # Eden's google_tokens only has cgm → GOOGLE_TOKEN_EDEN_CGM; with that env
    # var empty, drive must fail closed rather than fall back to Yuval's token.
    with patch("integrations.drive.config") as cfg:
        cfg.GOOGLE_TOKEN_EDEN_CGM = ""
        cfg.GOOGLE_TOKEN_PERSONAL = _b64(VALID_TOKEN_INFO)
        cfg.GOOGLE_TOKEN_CGM = _b64(VALID_TOKEN_INFO)
        text = await drive.search_files(
            "report", account_key="cgm", user_phone=EDEN
        )
        assert text == ""
