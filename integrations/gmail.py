"""Gmail integration.

Sends mail via the Gmail REST API using a per-account user token. Tokens are
stored as base64-encoded JSON in environment variables (Railway's filesystem
is ephemeral, so token files on disk would be lost on redeploy — see D-015).

Permission checks (``has_permission(phone, "gmail")``) happen at the
``claude_agent`` dispatch layer, not here.

We use httpx directly for the send call (consistent with ``integrations.notion``
and the spec's 10-second timeout). Token refresh, when needed, is delegated to
``google-auth`` via ``asyncio.to_thread`` so we don't block the event loop.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from email.message import EmailMessage

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from security.audit import log_action

logger = logging.getLogger(__name__)

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_GET_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"
TIMEOUT_SECONDS = 10.0

# Full scope set granted to the OAuth tokens after the Task 6c re-OAuth.
# Older tokens (send-only) still work for send but will fail for read/contacts.
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
OTHER_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.other.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

ALL_SCOPES = [
    GMAIL_SEND_SCOPE,
    GMAIL_READ_SCOPE,
    CONTACTS_SCOPE,
    OTHER_CONTACTS_SCOPE,
    CALENDAR_SCOPE,
    DRIVE_SCOPE,
]

ACCOUNT_KEYS = ("personal", "cgm", "deals")


def _token_env_for(account_key: str) -> str | None:
    if account_key == "personal":
        return config.GOOGLE_TOKEN_PERSONAL
    if account_key == "cgm":
        return config.GOOGLE_TOKEN_CGM
    if account_key == "deals":
        return config.GOOGLE_TOKEN_DEALS
    return None


def _load_credentials(account_key: str) -> Credentials | None:
    """Decode base64 token JSON and build a Credentials object. None on failure."""
    raw = _token_env_for(account_key)
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw)
        info = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("gmail _load_credentials decode error: %s", exc.__class__.__name__)
        return None
    try:
        return Credentials.from_authorized_user_info(info, scopes=ALL_SCOPES)
    except Exception as exc:  # google-auth raises ValueError on bad shape
        logger.error("gmail Credentials.from_authorized_user_info failed: %s", exc.__class__.__name__)
        return None


async def _ensure_access_token(creds: Credentials) -> str | None:
    """Return a valid access token, refreshing in a worker thread if needed."""
    if creds.valid and creds.token:
        return creds.token
    if not creds.refresh_token:
        return creds.token  # may be None; caller will fail the send

    def _refresh() -> None:
        creds.refresh(Request())

    try:
        await asyncio.to_thread(_refresh)
    except Exception as exc:
        logger.error("gmail token refresh failed: %s", exc.__class__.__name__)
        return None
    return creds.token


def _build_raw_message(to: str, subject: str, body: str) -> str:
    """Build an RFC 822 message and return it as base64url (no padding-stripped)."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


async def send_email(to: str, subject: str, body: str, account_key: str) -> bool:
    """Send an email via Gmail API from the account named by ``account_key``.

    ``account_key`` must be one of ``"personal" | "cgm" | "deals"``. Returns True
    on success, False on any failure (bad key, missing/unreadable token, refresh
    failure, HTTP error, timeout). Never raises.
    """
    if account_key not in ACCOUNT_KEYS:
        log_action("", "gmail_send_email", f"account={account_key}", "bad_account")
        return False

    creds = _load_credentials(account_key)
    if creds is None:
        log_action("", "gmail_send_email", f"account={account_key}", "no_token")
        return False

    token = await _ensure_access_token(creds)
    if not token:
        log_action("", "gmail_send_email", f"account={account_key}", "refresh_failed")
        return False

    raw = _build_raw_message(to=to, subject=subject, body=body)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(GMAIL_SEND_URL, headers=headers, json={"raw": raw})
        if resp.status_code >= 400:
            logger.error("Gmail send HTTP %s", resp.status_code)
            log_action(
                "", "gmail_send_email", f"account={account_key}", f"http_{resp.status_code}"
            )
            return False
        log_action("", "gmail_send_email", f"account={account_key}", "ok")
        return True
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Gmail send error: %s", exc.__class__.__name__)
        log_action("", "gmail_send_email", f"account={account_key}", "error")
        return False


def _header(headers: list[dict], name: str) -> str:
    target = name.lower()
    for entry in headers or []:
        if (entry.get("name") or "").lower() == target:
            return entry.get("value") or ""
    return ""


def _format_summary(messages: list[dict]) -> str:
    if not messages:
        return ""
    lines: list[str] = []
    for msg in messages:
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        sender = _header(headers, "From")
        subject = _header(headers, "Subject") or "(no subject)"
        date = _header(headers, "Date")
        snippet = (msg.get("snippet") or "").strip()
        lines.append(f"• {subject}\n  {sender} — {date}\n  {snippet}")
    return "\n\n".join(lines)


async def search_inbox(
    query: str, account_key: str, max_results: int = 10
) -> str:
    """Search the account's Gmail inbox and return a human-readable summary.

    ``query`` follows the Gmail search syntax (``from:``, ``subject:``,
    plain keywords, etc.). Empty string returns the most recent messages.
    Returns an empty string on any failure or zero hits.
    """
    if account_key not in ACCOUNT_KEYS:
        log_action("", "gmail_search_inbox", f"account={account_key}", "bad_account")
        return ""

    creds = _load_credentials(account_key)
    if creds is None:
        log_action("", "gmail_search_inbox", f"account={account_key}", "no_token")
        return ""

    token = await _ensure_access_token(creds)
    if not token:
        log_action("", "gmail_search_inbox", f"account={account_key}", "refresh_failed")
        return ""

    headers = {"Authorization": f"Bearer {token}"}
    max_results = max(1, min(int(max_results or 10), 25))

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            list_resp = await client.get(
                GMAIL_LIST_URL,
                headers=headers,
                params={"q": query or "", "maxResults": max_results},
            )
            if list_resp.status_code >= 400:
                logger.error("Gmail list HTTP %s", list_resp.status_code)
                log_action(
                    "", "gmail_search_inbox", f"account={account_key}", f"http_{list_resp.status_code}"
                )
                return ""
            ids = [m["id"] for m in (list_resp.json().get("messages") or []) if "id" in m]
            messages: list[dict] = []
            for mid in ids:
                get_resp = await client.get(
                    GMAIL_GET_URL.format(id=mid),
                    headers=headers,
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["From", "Subject", "Date"],
                    },
                )
                if get_resp.status_code >= 400:
                    logger.error("Gmail get HTTP %s for msg", get_resp.status_code)
                    continue
                messages.append(get_resp.json())
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Gmail search error: %s", exc.__class__.__name__)
        log_action("", "gmail_search_inbox", f"account={account_key}", "error")
        return ""

    summary = _format_summary(messages)
    log_action(
        "",
        "gmail_search_inbox",
        f"account={account_key} hits={len(messages)}",
        "ok",
    )
    return summary
