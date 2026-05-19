"""Google Calendar integration.

Uses the personal account token (``GOOGLE_TOKEN_PERSONAL``) — Yuval's single
calendar lives at ``yuvalmanor@gmail.com``. Tokens are base64-encoded JSON in
env vars, same pattern as ``integrations.gmail`` (see D-015).

Named ``gcalendar`` to avoid shadowing the stdlib ``calendar`` module.

Permission checks (``has_permission(phone, "calendar")``) happen at the
``claude_agent`` dispatch layer, not here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from security.audit import log_action

logger = logging.getLogger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TIMEOUT_SECONDS = 10.0
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def _load_credentials() -> Credentials | None:
    """Decode the personal-account base64 token JSON. None on failure."""
    raw = config.GOOGLE_TOKEN_PERSONAL
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw)
        info = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("gcalendar _load_credentials decode error: %s", exc.__class__.__name__)
        return None
    try:
        return Credentials.from_authorized_user_info(info, scopes=[CALENDAR_SCOPE])
    except Exception as exc:
        logger.error("gcalendar Credentials.from_authorized_user_info failed: %s", exc.__class__.__name__)
        return None


async def _ensure_access_token(creds: Credentials) -> str | None:
    """Return a valid access token, refreshing in a worker thread if needed."""
    if creds.valid and creds.token:
        return creds.token
    if not creds.refresh_token:
        return creds.token

    def _refresh() -> None:
        creds.refresh(Request())

    try:
        await asyncio.to_thread(_refresh)
    except Exception as exc:
        logger.error("gcalendar token refresh failed: %s", exc.__class__.__name__)
        return None
    return creds.token


async def create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    description: str | None = None,
    alert_minutes: int = 10,
) -> dict:
    """Create an event on the primary calendar.

    ``start_datetime`` / ``end_datetime`` must be RFC3339 strings (e.g.
    ``2026-05-20T14:00:00+03:00``). Returns a dict with:
      - ``ok``: bool — True on 2xx, False on any failure
      - ``html_link``: str — the event's Google Calendar URL (empty on failure)
      - ``reason``: str — short failure reason for the caller to surface
        (``no_token`` / ``refresh_failed`` / ``http_<code>`` / ``error``).
        Empty on success.

    ``alert_minutes`` semantics:
      - ``10`` (default) → popup reminder 10 minutes before
      - any non-negative int → popup that many minutes before
      - ``-1`` → no reminder (overrides=[], useDefault=false)
    Never raises.
    """
    creds = _load_credentials()
    if creds is None:
        log_action("", "calendar_create_event", "", "no_token")
        return {"ok": False, "html_link": "", "reason": "no_token"}

    token = await _ensure_access_token(creds)
    if not token:
        log_action("", "calendar_create_event", "", "refresh_failed")
        return {"ok": False, "html_link": "", "reason": "refresh_failed"}

    body: dict = {
        "summary": title,
        "start": {"dateTime": start_datetime},
        "end": {"dateTime": end_datetime},
    }
    if description:
        body["description"] = description

    if alert_minutes == -1:
        body["reminders"] = {"useDefault": False, "overrides": []}
    elif alert_minutes >= 0:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": alert_minutes}],
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(CALENDAR_API_BASE, headers=headers, json=body)
        if resp.status_code >= 400:
            logger.error("Calendar create HTTP %s", resp.status_code)
            log_action("", "calendar_create_event", "", f"http_{resp.status_code}")
            return {"ok": False, "html_link": "", "reason": f"http_{resp.status_code}"}
        html_link = ""
        try:
            html_link = resp.json().get("htmlLink", "") or ""
        except Exception:
            pass
        log_action("", "calendar_create_event", "", "ok")
        return {"ok": True, "html_link": html_link, "reason": ""}
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Calendar create error: %s", exc.__class__.__name__)
        log_action("", "calendar_create_event", "", "error")
        return {"ok": False, "html_link": "", "reason": "error"}


def _format_events(items: list[dict]) -> str:
    """Render a list of Calendar API event resources as a Hebrew-friendly string."""
    if not items:
        return ""
    lines: list[str] = []
    for ev in items:
        title = ev.get("summary", "(ללא כותרת)")
        start = ev.get("start", {})
        when = start.get("dateTime") or start.get("date") or ""
        lines.append(f"• {when} — {title}")
    return "\n".join(lines)


async def list_upcoming_events(days: int = 7) -> str:
    """Return upcoming events for the next ``days`` days as a formatted string.

    Empty string on any failure or if no events are found.
    """
    creds = _load_credentials()
    if creds is None:
        log_action("", "calendar_list_events", "", "no_token")
        return ""

    token = await _ensure_access_token(creds)
    if not token:
        log_action("", "calendar_list_events", "", "refresh_failed")
        return ""

    now = datetime.now(timezone.utc)
    time_min = now.isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=days)).isoformat().replace("+00:00", "Z")

    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "50",
    }
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(CALENDAR_API_BASE, headers=headers, params=params)
        if resp.status_code >= 400:
            logger.error("Calendar list HTTP %s", resp.status_code)
            log_action("", "calendar_list_events", "", f"http_{resp.status_code}")
            return ""
        data = resp.json()
        log_action("", "calendar_list_events", f"days={days}", "ok")
        return _format_events(data.get("items", []))
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Calendar list error: %s", exc.__class__.__name__)
        log_action("", "calendar_list_events", "", "error")
        return ""


async def cancel_event_by_query(
    query: str, days_window: int = 60
) -> tuple[str, list[str]]:
    """Cancel (delete) a single calendar event matched by free-text ``query``.

    Searches events on the primary calendar within the next ``days_window``
    days using the Calendar API's ``q=`` free-text filter (matches title,
    description, location, attendees). Mirrors the find-then-act / ambiguous
    pattern used by :func:`integrations.gmail.trash_by_query`.

    Returns a ``(status, summaries)`` tuple where status is one of:
      - ``"ok"``: exactly one match, deleted; ``summaries`` is ``[<title>]``
      - ``"not_found"``: zero matches; ``summaries`` is ``[]``
      - ``"ambiguous"``: 2+ matches; ``summaries`` lists all candidate titles
      - ``"error"``: auth/HTTP/timeout failure; ``summaries`` is ``[]``
    Never raises.
    """
    creds = _load_credentials()
    if creds is None:
        log_action("", "calendar_cancel_event", "", "no_token")
        return "error", []
    token = await _ensure_access_token(creds)
    if not token:
        log_action("", "calendar_cancel_event", "", "refresh_failed")
        return "error", []

    now = datetime.now(timezone.utc)
    time_min = now.isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=days_window)).isoformat().replace("+00:00", "Z")
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "q": query,
        "maxResults": "10",
    }
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(CALENDAR_API_BASE, headers=headers, params=params)
            if resp.status_code >= 400:
                logger.error("Calendar cancel search HTTP %s", resp.status_code)
                log_action("", "calendar_cancel_event", "", f"http_{resp.status_code}")
                return "error", []
            items = resp.json().get("items", [])
            if not items:
                log_action("", "calendar_cancel_event", "", "not_found")
                return "not_found", []
            if len(items) > 1:
                summaries = [it.get("summary", "(ללא כותרת)") for it in items]
                log_action("", "calendar_cancel_event", f"n={len(items)}", "ambiguous")
                return "ambiguous", summaries
            event = items[0]
            event_id = event["id"]
            summary = event.get("summary", "(ללא כותרת)")
            del_resp = await client.delete(
                f"{CALENDAR_API_BASE}/{event_id}", headers=headers
            )
            if del_resp.status_code in (200, 204):
                log_action("", "calendar_cancel_event", "", "ok")
                return "ok", [summary]
            logger.error("Calendar delete HTTP %s", del_resp.status_code)
            log_action("", "calendar_cancel_event", "", f"http_{del_resp.status_code}")
            return "error", []
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Calendar cancel error: %s", exc.__class__.__name__)
        log_action("", "calendar_cancel_event", "", "error")
        return "error", []
