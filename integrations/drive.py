"""Google Drive integration (read-only).

Searches files via the Drive v3 API using a per-account user token. Tokens are
base64-encoded JSON env vars, same pattern as ``integrations.gmail`` (D-015).

Permission checks (``has_permission(phone, "drive")``) happen at the
``claude_agent`` dispatch layer, not here.

Scope: ``drive.readonly`` only — no write operations.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from security.audit import log_action
from users import get_google_token_env_name

logger = logging.getLogger(__name__)

DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
TIMEOUT_SECONDS = 10.0
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
MAX_RESULTS = 20

ACCOUNT_KEYS = ("personal", "cgm", "deals")


def _token_env_for(account_key: str, user_phone: str | None = None) -> str | None:
    """Resolve token via the per-user mapping in ``users.USERS`` (Task 6d).

    ``user_phone=None`` falls back to Yuval's tokens for callers that don't
    plumb a phone through.
    """
    env_name = get_google_token_env_name(user_phone, account_key)
    if not env_name:
        return None
    return getattr(config, env_name, None)


def _load_credentials(account_key: str, user_phone: str | None = None) -> Credentials | None:
    raw = _token_env_for(account_key, user_phone)
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw)
        info = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("drive _load_credentials decode error: %s", exc.__class__.__name__)
        return None
    try:
        return Credentials.from_authorized_user_info(info, scopes=[DRIVE_SCOPE])
    except Exception as exc:
        logger.error("drive Credentials.from_authorized_user_info failed: %s", exc.__class__.__name__)
        return None


async def _ensure_access_token(creds: Credentials) -> str | None:
    if creds.valid and creds.token:
        return creds.token
    if not creds.refresh_token:
        return creds.token

    def _refresh() -> None:
        creds.refresh(Request())

    try:
        await asyncio.to_thread(_refresh)
    except Exception as exc:
        logger.error("drive token refresh failed: %s", exc.__class__.__name__)
        return None
    return creds.token


def _escape_query(q: str) -> str:
    """Escape backslashes and single quotes for a Drive ``q`` literal."""
    return q.replace("\\", "\\\\").replace("'", "\\'")


def _format_results(items: list[dict]) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for f in items:
        name = f.get("name", "(ללא שם)")
        link = f.get("webViewLink", "")
        if link:
            lines.append(f"• {name} — {link}")
        else:
            lines.append(f"• {name}")
    return "\n".join(lines)


async def search_files(
    query: str, account_key: str, user_phone: str | None = None
) -> str:
    """Search Drive files by name substring for the named account.

    The concrete Google account is resolved per-user via ``users.USERS`` —
    Eden's ``cgm`` → her account (Task 6d). Returns a Hebrew-friendly
    newline-joined list of "name — link" entries, or empty string on any
    failure or if no files match. Never raises.
    """
    if account_key not in ACCOUNT_KEYS:
        log_action(user_phone or "", "drive_search_files", f"account={account_key}", "bad_account")
        return ""

    creds = _load_credentials(account_key, user_phone)
    if creds is None:
        log_action(user_phone or "", "drive_search_files", f"account={account_key}", "no_token")
        return ""

    token = await _ensure_access_token(creds)
    if not token:
        log_action(user_phone or "", "drive_search_files", f"account={account_key}", "refresh_failed")
        return ""

    safe = _escape_query(query)
    params = {
        "q": f"name contains '{safe}' and trashed = false",
        "fields": "files(id,name,webViewLink,mimeType)",
        "pageSize": str(MAX_RESULTS),
    }
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(DRIVE_FILES_URL, headers=headers, params=params)
        if resp.status_code >= 400:
            logger.error("Drive search HTTP %s", resp.status_code)
            log_action(
                user_phone or "",
                "drive_search_files",
                f"account={account_key}",
                f"http_{resp.status_code}",
            )
            return ""
        data = resp.json()
        log_action(user_phone or "", "drive_search_files", f"account={account_key}", "ok")
        return _format_results(data.get("files", []))
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Drive search error: %s", exc.__class__.__name__)
        log_action(user_phone or "", "drive_search_files", f"account={account_key}", "error")
        return ""
