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
from users import get_google_token_env_name

logger = logging.getLogger(__name__)

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_GET_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"
GMAIL_TRASH_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}/trash"
TIMEOUT_SECONDS = 10.0

# Full scope set granted to the OAuth tokens after the Task 6c re-OAuth.
# Older tokens (send-only) still work for send but will fail for read/contacts.
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
OTHER_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.other.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

ALL_SCOPES = [
    GMAIL_SEND_SCOPE,
    GMAIL_READ_SCOPE,
    GMAIL_MODIFY_SCOPE,
    CONTACTS_SCOPE,
    OTHER_CONTACTS_SCOPE,
    CALENDAR_SCOPE,
    DRIVE_SCOPE,
]

ACCOUNT_KEYS = ("personal", "cgm", "deals")


def _token_env_for(account_key: str, user_phone: str | None = None) -> str | None:
    """Resolve the base64 token string for ``account_key`` belonging to ``user_phone``.

    Looks up the config attribute name on the user record (``users.USERS``) and
    returns the live value from ``config``. ``user_phone=None`` falls back to
    Yuval's tokens for service-internal callers (preserves pre-Task-6d
    behavior). Returns None if the user doesn't own this account_key, which
    callers treat as a missing-token failure.
    """
    env_name = get_google_token_env_name(user_phone, account_key)
    if not env_name:
        return None
    return getattr(config, env_name, None)


def _load_credentials(account_key: str, user_phone: str | None = None) -> Credentials | None:
    """Decode base64 token JSON and build a Credentials object. None on failure."""
    raw = _token_env_for(account_key, user_phone)
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


async def send_email(
    to: str,
    subject: str,
    body: str,
    account_key: str,
    user_phone: str | None = None,
) -> bool:
    """Send an email via Gmail API from the account named by ``account_key``.

    ``account_key`` must be one of ``"personal" | "cgm" | "deals"``. The
    concrete Google account is resolved per-user via ``users.USERS`` — for
    Eden, ``cgm`` routes to her own Gmail (Task 6d). Returns True on success,
    False on any failure (bad key, missing/unreadable token, refresh failure,
    HTTP error, timeout). Never raises.
    """
    if account_key not in ACCOUNT_KEYS:
        log_action(user_phone or "", "gmail_send_email", f"account={account_key}", "bad_account")
        return False

    creds = _load_credentials(account_key, user_phone)
    if creds is None:
        log_action(user_phone or "", "gmail_send_email", f"account={account_key}", "no_token")
        return False

    token = await _ensure_access_token(creds)
    if not token:
        log_action(user_phone or "", "gmail_send_email", f"account={account_key}", "refresh_failed")
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
                user_phone or "", "gmail_send_email", f"account={account_key}", f"http_{resp.status_code}"
            )
            return False
        log_action(user_phone or "", "gmail_send_email", f"account={account_key}", "ok")
        return True
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Gmail send error: %s", exc.__class__.__name__)
        log_action(user_phone or "", "gmail_send_email", f"account={account_key}", "error")
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
        lines.append(f"• {subject}\n  {sender} - {date}\n  {snippet}")
    return "\n\n".join(lines)


def _scope_query_to_primary_inbox(query: str) -> str:
    """Default Gmail searches to Primary-tab inbox messages.

    Gmail's ``messages.list`` with an empty or unscoped ``q`` returns *all*
    mail (Inbox + Sent + Spam + every tab including Promotions/Social/Updates).
    The tool is named ``search_inbox`` and the user's stated intent is the
    Primary tab specifically — so we inject ``in:inbox category:primary``
    unless the user (Claude) already constrained location/category in their
    query.
    """
    q = (query or "").strip()
    lowered = q.lower()
    additions: list[str] = []
    # Don't override an explicit user choice of location.
    if "in:" not in lowered and "label:" not in lowered:
        additions.append("in:inbox")
    if "category:" not in lowered:
        additions.append("category:primary")
    if not additions:
        return q
    prefix = " ".join(additions)
    return f"{prefix} {q}".strip()


async def search_inbox(
    query: str,
    account_key: str,
    max_results: int = 10,
    user_phone: str | None = None,
) -> str:
    """Search the account's Gmail inbox and return a human-readable summary.

    ``query`` follows the Gmail search syntax (``from:``, ``subject:``,
    plain keywords, etc.). Empty string returns the most recent messages.
    Returns an empty string on any failure or zero hits.
    """
    if account_key not in ACCOUNT_KEYS:
        log_action(user_phone or "", "gmail_search_inbox", f"account={account_key}", "bad_account")
        return ""

    creds = _load_credentials(account_key, user_phone)
    if creds is None:
        log_action(user_phone or "", "gmail_search_inbox", f"account={account_key}", "no_token")
        return ""

    token = await _ensure_access_token(creds)
    if not token:
        log_action(user_phone or "", "gmail_search_inbox", f"account={account_key}", "refresh_failed")
        return ""

    headers = {"Authorization": f"Bearer {token}"}
    max_results = max(1, min(int(max_results or 10), 25))
    scoped_query = _scope_query_to_primary_inbox(query)
    injected_primary = (
        "category:primary" in scoped_query
        and "category:primary" not in (query or "").lower()
    )

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            ids = await _list_message_ids(
                client, headers, scoped_query, max_results, account_key, user_phone
            )
            # Workspace / business accounts often don't have Gmail's category
            # tabs enabled, so category:primary returns nothing. If we injected
            # the filter ourselves and got zero hits, retry once without it.
            if not ids and injected_primary:
                fallback_query = scoped_query.replace("category:primary", "").strip()
                logger.info("Gmail search empty under Primary; retrying without category filter")
                ids = await _list_message_ids(
                    client, headers, fallback_query, max_results, account_key, user_phone
                )
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
        log_action(user_phone or "", "gmail_search_inbox", f"account={account_key}", "error")
        return ""

    summary = _format_summary(messages)
    log_action(
        user_phone or "",
        "gmail_search_inbox",
        f"account={account_key} hits={len(messages)}",
        "ok",
    )
    return summary


async def _list_message_ids(
    client: httpx.AsyncClient,
    headers: dict,
    query: str,
    max_results: int,
    account_key: str,
    user_phone: str | None = None,
) -> list[str]:
    """Wrap the messages.list call and return matching message IDs (or [])."""
    resp = await client.get(
        GMAIL_LIST_URL,
        headers=headers,
        params={"q": query, "maxResults": max_results},
    )
    if resp.status_code >= 400:
        logger.error("Gmail list HTTP %s", resp.status_code)
        log_action(
            user_phone or "",
            "gmail_search_inbox",
            f"account={account_key}",
            f"http_{resp.status_code}",
        )
        return []
    return [m["id"] for m in (resp.json().get("messages") or []) if "id" in m]


async def trash_by_query(
    query: str,
    account_key: str,
    max_candidates: int = 5,
    user_phone: str | None = None,
) -> tuple[str, list[str]]:
    """Trash a single message identified by a Gmail query.

    Returns a ``(status, subjects)`` tuple:
    - ``("ok", [subject])`` — exactly one match, moved to Trash.
    - ``("not_found", [])`` — no messages matched.
    - ``("ambiguous", [subj1, subj2, ...])`` — multiple matches; caller
      should ask the user to narrow down.
    - ``("error", [])`` — bad account, missing/unreadable token, refresh
      failure, HTTP error, or timeout.

    Query is scoped to ``in:inbox category:primary`` by the same rule as
    ``search_inbox`` (with the Workspace fallback). Messages go to Trash —
    they're recoverable from the Gmail UI for 30 days.
    """
    if account_key not in ACCOUNT_KEYS:
        log_action(user_phone or "", "gmail_trash_email", f"account={account_key}", "bad_account")
        return ("error", [])

    creds = _load_credentials(account_key, user_phone)
    if creds is None:
        log_action(user_phone or "", "gmail_trash_email", f"account={account_key}", "no_token")
        return ("error", [])

    token = await _ensure_access_token(creds)
    if not token:
        log_action(user_phone or "", "gmail_trash_email", f"account={account_key}", "refresh_failed")
        return ("error", [])

    headers = {"Authorization": f"Bearer {token}"}
    max_candidates = max(1, min(int(max_candidates or 5), 10))
    scoped_query = _scope_query_to_primary_inbox(query)
    injected_primary = (
        "category:primary" in scoped_query
        and "category:primary" not in (query or "").lower()
    )

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            ids = await _list_message_ids(
                client, headers, scoped_query, max_candidates, account_key, user_phone
            )
            if not ids and injected_primary:
                fallback_query = scoped_query.replace("category:primary", "").strip()
                ids = await _list_message_ids(
                    client, headers, fallback_query, max_candidates, account_key, user_phone
                )

            if not ids:
                log_action(
                    user_phone or "",
                    "gmail_trash_email",
                    f"account={account_key} q={query}",
                    "not_found",
                )
                return ("not_found", [])

            if len(ids) > 1:
                # Fetch subjects for disambiguation.
                subjects: list[str] = []
                for mid in ids:
                    get_resp = await client.get(
                        GMAIL_GET_URL.format(id=mid),
                        headers=headers,
                        params={
                            "format": "metadata",
                            "metadataHeaders": ["Subject", "From"],
                        },
                    )
                    if get_resp.status_code >= 400:
                        continue
                    payload = get_resp.json().get("payload") or {}
                    h = payload.get("headers") or []
                    subjects.append(_header(h, "Subject") or "(no subject)")
                log_action(
                    user_phone or "",
                    "gmail_trash_email",
                    f"account={account_key} hits={len(ids)}",
                    "ambiguous",
                )
                return ("ambiguous", subjects)

            mid = ids[0]
            # Grab the subject before trashing so we can echo it back.
            get_resp = await client.get(
                GMAIL_GET_URL.format(id=mid),
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["Subject"]},
            )
            subject = "(unknown)"
            if get_resp.status_code < 400:
                payload = get_resp.json().get("payload") or {}
                subject = _header(payload.get("headers") or [], "Subject") or "(no subject)"

            trash_resp = await client.post(
                GMAIL_TRASH_URL.format(id=mid), headers=headers
            )
            if trash_resp.status_code >= 400:
                logger.error("Gmail trash HTTP %s", trash_resp.status_code)
                log_action(
                    user_phone or "",
                    "gmail_trash_email",
                    f"account={account_key}",
                    f"http_{trash_resp.status_code}",
                )
                return ("error", [])

            log_action(
                user_phone or "", "gmail_trash_email", f"account={account_key}", "ok"
            )
            return ("ok", [subject])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Gmail trash error: %s", exc.__class__.__name__)
        log_action(user_phone or "", "gmail_trash_email", f"account={account_key}", "error")
        return ("error", [])
