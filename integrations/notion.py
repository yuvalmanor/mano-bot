"""Notion integration.

Uses the Notion REST API directly via httpx (10-second timeout per spec).
Permission checks happen at the ``claude_agent`` dispatch layer, not here.

Adapted to Yuval's existing Notion schema (under Headquarters / Idea Lab):

* My Task List database — title prop is ``Task``, ``Bucket`` is a *relation*
  to the My Life Buckets DB, ``Date`` is the due date.

* My Ideas database — title prop is ``Idea``, ``Description`` is rich_text,
  ``Bucket`` is a relation to the same My Life Buckets DB.

* My Life Buckets database — one page per bucket; the page title is the
  bucket name (``Business``, ``Personal``, etc.). We resolve a bucket name to
  a page ID via a lazy-cached query, then set the relation by page ID.
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

# Lazy-loaded bucket caches. Populated on first call to _load_buckets().
_BUCKET_NAME_TO_ID: dict[str, str] = {}
_BUCKET_ID_TO_NAME: dict[str, str] = {}
_BUCKETS_LOADED = False


def _reset_bucket_cache() -> None:
    """Test hook — clear the bucket cache so tests start fresh."""
    global _BUCKETS_LOADED
    _BUCKET_NAME_TO_ID.clear()
    _BUCKET_ID_TO_NAME.clear()
    _BUCKETS_LOADED = False


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


def _extract_plain_title(page: dict, prop_name: str) -> str:
    parts = (page.get("properties", {}).get(prop_name) or {}).get("title", []) or []
    return "".join(p.get("plain_text", "") for p in parts)


async def _load_buckets() -> None:
    """Populate the bucket name<->id caches from the My Life Buckets DB.

    Silent no-op on error — callers must handle empty caches gracefully.
    """
    global _BUCKETS_LOADED
    if _BUCKETS_LOADED:
        return
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_BUCKETS_DB_ID}/query",
                headers=_headers(),
                json={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion _load_buckets HTTP %s", resp.status_code)
            return
        data = resp.json()
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion _load_buckets error: %s", exc.__class__.__name__)
        return

    for page in data.get("results", []):
        page_id = page.get("id")
        if not page_id:
            continue
        name = _extract_plain_title(page, "Name")
        if not name:
            continue
        _BUCKET_NAME_TO_ID[name] = page_id
        _BUCKET_ID_TO_NAME[page_id] = name

    _BUCKETS_LOADED = True


async def _resolve_bucket_id(bucket_name: str) -> str | None:
    """Return the My Life Buckets page ID for ``bucket_name``, or None."""
    await _load_buckets()
    return _BUCKET_NAME_TO_ID.get(bucket_name)


async def add_task(title: str, bucket: str, due_date: str | None = None) -> bool:
    """Create a task page in My Task List. Returns True on success.

    The bucket is set as a relation to My Life Buckets. If ``bucket`` cannot be
    resolved to an existing bucket page, the task is created without a bucket
    relation (Yuval can re-bucket it manually) and the audit log records
    ``status=ok_no_bucket``.
    """
    bucket_id = await _resolve_bucket_id(bucket)

    properties: dict = {"Task": _title_prop(title)}
    if bucket_id:
        properties["Bucket"] = {"relation": [{"id": bucket_id}]}
    if due_date:
        properties["Date"] = {"date": {"start": due_date}}

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
        status = "ok" if bucket_id else "ok_no_bucket"
        log_action("", "notion_add_task", f"bucket={bucket}", status)
        return True
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_task error: %s", exc.__class__.__name__)
        log_action("", "notion_add_task", f"bucket={bucket}", "error")
        return False


async def add_idea(title: str, description: str | None = None) -> bool:
    """Create an idea page in My Ideas. Returns True on success."""
    properties: dict = {"Idea": _title_prop(title)}
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


def _extract_due(page: dict) -> str:
    d = (page.get("properties", {}).get("Date") or {}).get("date")
    return d.get("start", "") if d else ""


def _extract_priority(page: dict) -> str:
    sel = (page.get("properties", {}).get("Priority") or {}).get("select")
    return sel.get("name") if sel else ""


def _extract_bucket_name(page: dict) -> str:
    """Resolve the page's Bucket relation back to a bucket name via the cache."""
    rel = (page.get("properties", {}).get("Bucket") or {}).get("relation") or []
    if not rel:
        return "ללא קטגוריה"
    first_id = rel[0].get("id")
    return _BUCKET_ID_TO_NAME.get(first_id, "ללא קטגוריה")


async def list_tasks(filter_bucket: str | None = None) -> str:
    """Return tasks grouped by bucket → due date → priority.

    Empty string on error or no matches. Bucket filter is by name; resolved to
    a relation filter against the My Life Buckets page ID.
    """
    await _load_buckets()

    payload: dict = {"page_size": 100}
    if filter_bucket:
        bucket_id = _BUCKET_NAME_TO_ID.get(filter_bucket)
        if not bucket_id:
            log_action("", "notion_list_tasks", f"unknown_bucket={filter_bucket}", "empty")
            return ""
        payload["filter"] = {
            "property": "Bucket",
            "relation": {"contains": bucket_id},
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
        b = _extract_bucket_name(page)
        by_bucket.setdefault(b, []).append(page)

    lines: list[str] = []
    for bucket in sorted(by_bucket.keys()):
        lines.append(f"📂 {bucket}")
        items = by_bucket[bucket]
        items.sort(key=lambda p: (_extract_due(p) or "9999", _extract_priority(p)))
        for p in items:
            title = _extract_plain_title(p, "Task") or "(ללא שם)"
            due = _extract_due(p)
            prio = _extract_priority(p)
            suffix_parts = []
            if due:
                suffix_parts.append(due)
            if prio:
                suffix_parts.append(f"P{prio}")
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            lines.append(f"  • {title}{suffix}")
        lines.append("")

    log_action("", "notion_list_tasks", f"count={len(pages)}", "ok")
    return "\n".join(lines).rstrip()
