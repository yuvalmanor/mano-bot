"""Notion integration.

Uses the Notion REST API directly via httpx (10-second timeout per spec).
Permission checks (``has_permission(phone, "notion")``) happen at the
``claude_agent`` dispatch layer, not here.

Expected Notion database schemas:

* Tasks DB (``NOTION_TASK_DB_ID``)
    - ``Name`` — title
    - ``Bucket`` — select (one of the 15 buckets in SYSTEM_PROMPT)
    - ``Due`` — date (optional)

* Ideas DB (``NOTION_IDEAS_DB_ID``)
    - ``Name`` — title
    - ``Description`` — rich_text (optional)

See README "Notion setup" for how to create these.
"""

from __future__ import annotations

import logging

import httpx

import config
from security.audit import log_action

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT_SECONDS = 10.0


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _title_prop(text: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": text}}]}


def _rich_text_prop(text: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": text}}]}


async def add_task(title: str, bucket: str, due_date: str | None = None) -> bool:
    """Create a task page in the Tasks DB. Returns True on success."""
    properties: dict = {
        "Name": _title_prop(title),
        "Bucket": {"select": {"name": bucket}},
    }
    if due_date:
        properties["Due"] = {"date": {"start": due_date}}

    payload = {
        "parent": {"database_id": config.NOTION_TASK_DB_ID},
        "properties": properties,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/pages", headers=_headers(), json=payload
            )
        if resp.status_code >= 400:
            logger.error("Notion add_task HTTP %s", resp.status_code)
            log_action("", "notion_add_task", f"bucket={bucket}", f"http_{resp.status_code}")
            return False
        log_action("", "notion_add_task", f"bucket={bucket}", "ok")
        return True
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_task error: %s", exc.__class__.__name__)
        log_action("", "notion_add_task", f"bucket={bucket}", "error")
        return False


async def add_idea(title: str, description: str | None = None) -> bool:
    """Create an idea page in the Ideas DB. Returns True on success."""
    properties: dict = {"Name": _title_prop(title)}
    if description:
        properties["Description"] = _rich_text_prop(description)

    payload = {
        "parent": {"database_id": config.NOTION_IDEAS_DB_ID},
        "properties": properties,
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/pages", headers=_headers(), json=payload
            )
        if resp.status_code >= 400:
            logger.error("Notion add_idea HTTP %s", resp.status_code)
            log_action("", "notion_add_idea", "", f"http_{resp.status_code}")
            return False
        log_action("", "notion_add_idea", "", "ok")
        return True
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_idea error: %s", exc.__class__.__name__)
        log_action("", "notion_add_idea", "", "error")
        return False


def _extract_title(page: dict) -> str:
    name = page.get("properties", {}).get("Name", {})
    parts = name.get("title", []) or []
    return "".join(p.get("plain_text", "") for p in parts) or "(ללא שם)"


def _extract_bucket(page: dict) -> str:
    sel = (page.get("properties", {}).get("Bucket") or {}).get("select")
    return sel.get("name") if sel else "ללא קטגוריה"


def _extract_due(page: dict) -> str:
    d = (page.get("properties", {}).get("Due") or {}).get("date")
    return d.get("start", "") if d else ""


def _extract_priority(page: dict) -> str:
    sel = (page.get("properties", {}).get("Priority") or {}).get("select")
    return sel.get("name") if sel else ""


async def list_tasks(filter_bucket: str | None = None) -> str:
    """Return a Hebrew-friendly string of tasks grouped by bucket → due → priority.

    Empty string on error or when no tasks match.
    """
    payload: dict = {"page_size": 100}
    if filter_bucket:
        payload["filter"] = {
            "property": "Bucket",
            "select": {"equals": filter_bucket},
        }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_TASK_DB_ID}/query",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code >= 400:
            logger.error("Notion list_tasks HTTP %s", resp.status_code)
            log_action("", "notion_list_tasks", "", f"http_{resp.status_code}")
            return ""
        data = resp.json()
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion list_tasks error: %s", exc.__class__.__name__)
        log_action("", "notion_list_tasks", "", "error")
        return ""

    pages = data.get("results", [])
    if not pages:
        log_action("", "notion_list_tasks", "", "empty")
        return ""

    by_bucket: dict[str, list[dict]] = {}
    for page in pages:
        b = _extract_bucket(page)
        by_bucket.setdefault(b, []).append(page)

    lines: list[str] = []
    for bucket in sorted(by_bucket.keys()):
        lines.append(f"📂 {bucket}")
        items = by_bucket[bucket]
        items.sort(key=lambda p: (_extract_due(p) or "9999", _extract_priority(p)))
        for p in items:
            title = _extract_title(p)
            due = _extract_due(p)
            prio = _extract_priority(p)
            suffix_parts = []
            if due:
                suffix_parts.append(due)
            if prio:
                suffix_parts.append(prio)
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            lines.append(f"  • {title}{suffix}")
        lines.append("")

    log_action("", "notion_list_tasks", f"count={len(pages)}", "ok")
    return "\n".join(lines).rstrip()
