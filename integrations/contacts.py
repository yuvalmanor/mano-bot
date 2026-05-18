"""Google People API — contacts lookup.

Searches the authenticated account's contacts. We hit two endpoints and merge:

* ``people:searchContacts`` — the user's saved "My Contacts".
* ``otherContacts:search`` — auto-generated contacts from past correspondence
  (anyone the account has emailed/been emailed by without being explicitly
  saved). This is the dominant source for "people I've emailed" lookups.

Returns a deduplicated list of ``{"name", "email"}`` dicts. Empty list on any
failure (bad account key, missing/unreadable token, refresh failure, HTTP/
timeout error). Never raises.

Token loading / scope handling is shared with ``integrations.gmail`` via
``integrations.gmail._load_credentials`` so credentials live in one place.
"""

from __future__ import annotations

import logging

import httpx

from integrations.gmail import _ensure_access_token, _load_credentials
from security.audit import log_action

logger = logging.getLogger(__name__)

PEOPLE_SEARCH_URL = "https://people.googleapis.com/v1/people:searchContacts"
OTHER_CONTACTS_SEARCH_URL = "https://people.googleapis.com/v1/otherContacts:search"
TIMEOUT_SECONDS = 10.0
DEFAULT_PAGE_SIZE = 25

# People API requires both endpoints to be "warmed up" with an empty-query
# request before they return results for a real query. We skip the warmup —
# the bot's first call after redeploy may be empty, but subsequent calls work.
# (Not a correctness issue: empty results just trigger the "ask Yuval for the
# address" fallback path in the prompt.)


def _extract_matches(payload: dict) -> list[dict]:
    """Pull (name, email) pairs out of either endpoint's response shape."""
    out: list[dict] = []
    results = payload.get("results") or []
    for entry in results:
        person = entry.get("person") or {}
        names = person.get("names") or []
        emails = person.get("emailAddresses") or []
        if not emails:
            continue
        display_name = (names[0].get("displayName") if names else "") or ""
        for email_entry in emails:
            value = (email_entry.get("value") or "").strip()
            if value:
                out.append({"name": display_name.strip(), "email": value})
    return out


def _dedupe(entries: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for entry in entries:
        key = entry["email"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


async def lookup_contact(
    query: str, account_key: str, user_phone: str | None = None
) -> list[dict]:
    """Search the named account's contacts for ``query``.

    ``account_key`` currently accepts ``"cgm"`` only (per spec: contacts lookup
    is CGM-scoped). The concrete Google account is resolved per-user via
    ``users.USERS`` — Eden's ``cgm`` → her account (Task 6d). Returns a list of
    ``{"name", "email"}`` dicts, deduped by email. Empty list on any failure.
    """
    creds = _load_credentials(account_key, user_phone)
    if creds is None:
        log_action(user_phone or "", "contacts_lookup", f"account={account_key}", "no_token")
        return []

    token = await _ensure_access_token(creds)
    if not token:
        log_action(user_phone or "", "contacts_lookup", f"account={account_key}", "refresh_failed")
        return []

    headers = {"Authorization": f"Bearer {token}"}
    merged: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            saved_resp = await client.get(
                PEOPLE_SEARCH_URL,
                headers=headers,
                params={
                    "query": query,
                    "readMask": "names,emailAddresses",
                    "pageSize": DEFAULT_PAGE_SIZE,
                },
            )
            other_resp = await client.get(
                OTHER_CONTACTS_SEARCH_URL,
                headers=headers,
                params={
                    "query": query,
                    "readMask": "names,emailAddresses",
                    "pageSize": DEFAULT_PAGE_SIZE,
                },
            )
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("contacts lookup error: %s", exc.__class__.__name__)
        log_action(user_phone or "", "contacts_lookup", f"account={account_key}", "error")
        return []

    for resp in (saved_resp, other_resp):
        if resp.status_code >= 400:
            logger.error(
                "contacts lookup HTTP %s on %s",
                resp.status_code,
                resp.request.url.path if resp.request else "?",
            )
            continue
        try:
            merged.extend(_extract_matches(resp.json()))
        except ValueError:
            logger.error("contacts lookup: response was not JSON")

    deduped = _dedupe(merged)
    log_action(
        user_phone or "",
        "contacts_lookup",
        f"account={account_key} hits={len(deduped)}",
        "ok",
    )
    return deduped
