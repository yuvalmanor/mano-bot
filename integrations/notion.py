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
from datetime import datetime, timedelta, timezone

import httpx

import config
from security.audit import log_action

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TIMEOUT_SECONDS = 10.0
DEDUPE_WINDOW_MINUTES = 5

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


def _extract_rich_text(page: dict, prop_name: str) -> str:
    parts = (page.get("properties", {}).get(prop_name) or {}).get("rich_text", []) or []
    return "".join(p.get("plain_text", "") for p in parts)


# Notion caps a single rich_text item at 2000 chars; chunk below that.
_BLOCK_TEXT_LIMIT = 1900


def _paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def _idea_body_blocks(content: str | None, source_url: str | None) -> list[dict]:
    """Build page-body blocks: a source bookmark + chunked content paragraphs."""
    blocks: list[dict] = []
    if source_url:
        blocks.append(_paragraph_block(f"Source: {source_url}"))
        blocks.append({"object": "block", "type": "bookmark", "bookmark": {"url": source_url}})
    if content:
        for i in range(0, len(content), _BLOCK_TEXT_LIMIT):
            blocks.append(_paragraph_block(content[i : i + _BLOCK_TEXT_LIMIT]))
    return blocks


def _block_to_text(block: dict) -> str:
    """Extract readable text from a single Notion block (best-effort)."""
    btype = block.get("type", "")
    payload = block.get(btype) or {}
    if btype == "bookmark":
        return payload.get("url", "")
    rich = payload.get("rich_text") or []
    return "".join(r.get("plain_text", "") for r in rich)


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


async def _recent_duplicate_exists(db_id: str, title_prop: str, title: str) -> bool:
    """Return True if a page with the same title was created in the dedupe window."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUPE_WINDOW_MINUTES)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{db_id}/query",
                headers=_headers(),
                json={
                    "page_size": 20,
                    "sorts": [{"timestamp": "created_time", "direction": "descending"}],
                    "filter": {
                        "property": title_prop,
                        "title": {"equals": title},
                    },
                },
            )
        if resp.status_code >= 400:
            return False
        for page in resp.json().get("results", []):
            created = page.get("created_time", "")
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts >= cutoff:
                return True
        return False
    except (httpx.TimeoutException, httpx.HTTPError):
        return False


async def add_task(title: str, bucket: str, due_date: str | None = None) -> str:
    """Create a task page in My Task List.

    Returns one of ``"ok"`` | ``"ok_no_bucket"`` | ``"duplicate"`` | ``"error"``.
    Duplicate = a task with the same exact title was created in the last
    ``DEDUPE_WINDOW_MINUTES`` (guards against accidental double tool calls).
    """
    if await _recent_duplicate_exists(config.NOTION_TASK_DB_ID, "Task", title):
        log_action("", "notion_add_task", f"bucket={bucket}", "duplicate")
        return "duplicate"

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
            return "error"
        status = "ok" if bucket_id else "ok_no_bucket"
        log_action("", "notion_add_task", f"bucket={bucket}", status)
        return status
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_task error: %s", exc.__class__.__name__)
        log_action("", "notion_add_task", f"bucket={bucket}", "error")
        return "error"


async def add_idea(
    title: str,
    description: str | None = None,
    bucket: str | None = None,
    content: str | None = None,
    source_url: str | None = None,
) -> str:
    """Create an idea page in My Ideas.

    Returns one of ``"ok"`` | ``"ok_no_bucket"`` | ``"duplicate"`` | ``"error"``.
    ``bucket`` is optional; when provided it's resolved to a My Life Buckets
    relation. Unknown bucket → created without relation (status ``ok_no_bucket``).

    ``content`` and ``source_url`` are the knowledge-DB extension: when either
    is supplied, the page *body* gets a source bookmark and the distilled
    article content (chunked into paragraph blocks), so the idea is readable
    and the link re-openable later. Callers that omit both keep the original
    title/description/bucket behavior unchanged.
    """
    if await _recent_duplicate_exists(config.NOTION_IDEAS_DB_ID, "Idea", title):
        log_action("", "notion_add_idea", "", "duplicate")
        return "duplicate"

    properties: dict = {"Idea": _title_prop(title)}
    if description:
        properties["Description"] = _rich_text_prop(description)

    bucket_id: str | None = None
    if bucket:
        bucket_id = await _resolve_bucket_id(bucket)
        if bucket_id:
            properties["Bucket"] = {"relation": [{"id": bucket_id}]}

    payload = {
        "parent": {"database_id": config.NOTION_IDEAS_DB_ID},
        "properties": properties,
    }
    body_blocks = _idea_body_blocks(content, source_url)
    if body_blocks:
        payload["children"] = body_blocks

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/pages", headers=_headers(), json=payload
            )
        if resp.status_code >= 400:
            logger.error("Notion add_idea HTTP %s", resp.status_code)
            log_action("", "notion_add_idea", f"bucket={bucket}", f"http_{resp.status_code}")
            return "error"
        status = "ok" if (bucket_id or not bucket) else "ok_no_bucket"
        log_action("", "notion_add_idea", f"bucket={bucket}", status)
        return status
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_idea error: %s", exc.__class__.__name__)
        log_action("", "notion_add_idea", f"bucket={bucket}", "error")
        return "error"


async def archive_idea(title: str) -> tuple[str, list[str]]:
    """Archive an idea from My Ideas by fuzzy title match.

    Same contract as ``archive_task``: returns ``(status, matches)`` with
    status in ``{"ok", "not_found", "ambiguous", "error"}``.
    """
    needle = title.strip().lower()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_IDEAS_DB_ID}/query",
                headers=_headers(),
                json={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion archive_idea query HTTP %s", resp.status_code)
            log_action("", "notion_archive_idea", f"title={title}", f"http_{resp.status_code}")
            return ("error", [])
        pages = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion archive_idea query error: %s", exc.__class__.__name__)
        log_action("", "notion_archive_idea", f"title={title}", "error")
        return ("error", [])

    matches: list[tuple[str, str]] = []
    for page in pages:
        page_title = _extract_plain_title(page, "Idea")
        if needle in page_title.lower():
            matches.append((page.get("id", ""), page_title))

    if not matches:
        log_action("", "notion_archive_idea", f"title={title}", "not_found")
        return ("not_found", [])
    if len(matches) > 1:
        log_action("", "notion_archive_idea", f"title={title}", "ambiguous")
        return ("ambiguous", [t for _, t in matches])

    page_id, matched_title = matches[0]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.patch(
                f"{NOTION_API}/pages/{page_id}",
                headers=_headers(),
                json={"archived": True},
            )
        if resp.status_code >= 400:
            logger.error("Notion archive_idea patch HTTP %s", resp.status_code)
            log_action("", "notion_archive_idea", f"title={matched_title}", f"http_{resp.status_code}")
            return ("error", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion archive_idea patch error: %s", exc.__class__.__name__)
        log_action("", "notion_archive_idea", f"title={matched_title}", "error")
        return ("error", [])

    log_action("", "notion_archive_idea", f"title={matched_title}", "ok")
    return ("ok", [matched_title])


async def list_ideas(filter_bucket: str | None = None) -> str:
    """Return ideas grouped by bucket. Empty string on error / no matches."""
    await _load_buckets()

    payload: dict = {"page_size": 100}
    if filter_bucket:
        bucket_id = _BUCKET_NAME_TO_ID.get(filter_bucket)
        if not bucket_id:
            log_action("", "notion_list_ideas", f"unknown_bucket={filter_bucket}", "empty")
            return ""
        payload["filter"] = {
            "property": "Bucket", "relation": {"contains": bucket_id}
        }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_IDEAS_DB_ID}/query",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code >= 400:
            logger.error("Notion list_ideas HTTP %s", resp.status_code)
            log_action("", "notion_list_ideas", "", f"http_{resp.status_code}")
            return ""
        data = resp.json()
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion list_ideas error: %s", exc.__class__.__name__)
        log_action("", "notion_list_ideas", "", "error")
        return ""

    pages = data.get("results", [])
    if not pages:
        log_action("", "notion_list_ideas", "", "empty")
        return ""

    by_bucket: dict[str, list[str]] = {}
    for page in pages:
        title = _extract_plain_title(page, "Idea") or "(ללא שם)"
        bucket = _extract_bucket_name(page)
        by_bucket.setdefault(bucket, []).append(title)

    lines: list[str] = []
    for bucket in sorted(by_bucket.keys()):
        lines.append(f"💡 {bucket}")
        for title in by_bucket[bucket]:
            lines.append(f"  • {title}")
        lines.append("")

    log_action("", "notion_list_ideas", f"count={len(pages)}", "ok")
    return "\n".join(lines).rstrip()


async def add_idea_comment(idea_title: str, comment: str) -> tuple[str, list[str]]:
    """Add a Notion page comment to an idea matched by fuzzy title.

    Returns ``(status, matches)`` where status is one of:
      * ``"ok"`` — single match, comment added. ``matches=[matched_title]``.
      * ``"not_found"`` — no idea matches. ``matches=[]``.
      * ``"ambiguous"`` — multiple matches. ``matches=[title, title, ...]``.
      * ``"error"`` — HTTP or transport error.
    """
    needle = idea_title.strip().lower()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_IDEAS_DB_ID}/query",
                headers=_headers(),
                json={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion add_idea_comment query HTTP %s", resp.status_code)
            log_action("", "notion_add_idea_comment", f"title={idea_title}", f"http_{resp.status_code}")
            return ("error", [])
        pages = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_idea_comment query error: %s", exc.__class__.__name__)
        log_action("", "notion_add_idea_comment", f"title={idea_title}", "error")
        return ("error", [])

    matches: list[tuple[str, str]] = []
    for page in pages:
        page_title = _extract_plain_title(page, "Idea")
        if needle in page_title.lower():
            matches.append((page.get("id", ""), page_title))

    if not matches:
        log_action("", "notion_add_idea_comment", f"title={idea_title}", "not_found")
        return ("not_found", [])
    if len(matches) > 1:
        log_action("", "notion_add_idea_comment", f"title={idea_title}", "ambiguous")
        return ("ambiguous", [t for _, t in matches])

    page_id, matched_title = matches[0]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/comments",
                headers=_headers(),
                json={
                    "parent": {"page_id": page_id},
                    "rich_text": [{"type": "text", "text": {"content": comment}}],
                },
            )
        if resp.status_code >= 400:
            logger.error("Notion add_idea_comment HTTP %s", resp.status_code)
            log_action("", "notion_add_idea_comment", f"title={matched_title}", f"http_{resp.status_code}")
            return ("error", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_idea_comment error: %s", exc.__class__.__name__)
        log_action("", "notion_add_idea_comment", f"title={matched_title}", "error")
        return ("error", [])

    log_action("", "notion_add_idea_comment", f"title={matched_title}", "ok")
    return ("ok", [matched_title])


async def get_idea(title: str) -> tuple[str, str]:
    """Read one idea's full content from the Idea Lab, matched by fuzzy title.

    Returns ``(status, content)`` where status is one of:
      * ``"ok"`` — single match; ``content`` = Description + page body + comments.
      * ``"not_found"`` — no idea matches. ``content=""``.
      * ``"ambiguous"`` — multiple matches; ``content`` = candidate titles joined
        with `` | `` (same shape the dispatcher uses for archive/comment).
      * ``"error"`` — HTTP or transport error. ``content=""``.

    Match rule: case-insensitive substring against the Idea title — identical to
    ``archive_idea`` / ``add_idea_comment``.
    """
    needle = title.strip().lower()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_IDEAS_DB_ID}/query",
                headers=_headers(),
                json={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion get_idea query HTTP %s", resp.status_code)
            log_action("", "notion_get_idea", f"title={title}", f"http_{resp.status_code}")
            return ("error", "")
        pages = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion get_idea query error: %s", exc.__class__.__name__)
        log_action("", "notion_get_idea", f"title={title}", "error")
        return ("error", "")

    matches: list[tuple[str, str]] = []
    for page in pages:
        page_title = _extract_plain_title(page, "Idea")
        if needle in page_title.lower():
            matches.append((page.get("id", ""), page_title))

    if not matches:
        log_action("", "notion_get_idea", f"title={title}", "not_found")
        return ("not_found", "")
    if len(matches) > 1:
        log_action("", "notion_get_idea", f"title={title}", "ambiguous")
        return ("ambiguous", " | ".join(t for _, t in matches))

    page_id, matched_title = matches[0]
    matched_page = next(p for p in pages if p.get("id") == page_id)

    sections: list[str] = [f"# {matched_title}"]
    description = _extract_rich_text(matched_page, "Description")
    if description:
        sections.append(description)

    body = await _fetch_block_text(page_id)
    if body:
        sections.append(body)

    comments = await _fetch_comments_text(page_id)
    if comments:
        sections.append("Comments:\n" + comments)

    log_action("", "notion_get_idea", f"title={matched_title}", "ok")
    return ("ok", "\n\n".join(sections))


async def _fetch_block_text(page_id: str) -> str:
    """Return the page body as text (paragraphs/headings/bookmarks). '' on error."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{NOTION_API}/blocks/{page_id}/children",
                headers=_headers(),
                params={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion get_idea blocks HTTP %s", resp.status_code)
            return ""
        blocks = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion get_idea blocks error: %s", exc.__class__.__name__)
        return ""

    lines = [t for t in (_block_to_text(b) for b in blocks) if t]
    return "\n".join(lines)


async def _fetch_comments_text(page_id: str) -> str:
    """Return page comments as newline-joined text. '' on error or none."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{NOTION_API}/comments",
                headers=_headers(),
                params={"block_id": page_id, "page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion get_idea comments HTTP %s", resp.status_code)
            return ""
        comments = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion get_idea comments error: %s", exc.__class__.__name__)
        return ""

    lines: list[str] = []
    for c in comments:
        text = "".join(r.get("plain_text", "") for r in c.get("rich_text", []) or [])
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


# ---- Knowledge DB (Phase 2) ------------------------------------------------
# A dedicated database for saved articles / links / references, separate from
# the Idea Lab. Schema: Title (title) / Topic (multi_select) / Source (url) /
# Saved (created_time). Distilled content + link live in the page body. All
# functions short-circuit to "not_configured" until NOTION_KNOWLEDGE_DB_ID is
# set, so the feature is inert on deploys where the DB doesn't exist yet.


def _extract_multi_select(page: dict, prop_name: str) -> list[str]:
    sel = (page.get("properties", {}).get(prop_name) or {}).get("multi_select") or []
    return [s.get("name", "") for s in sel if s.get("name")]


def _extract_url(page: dict, prop_name: str) -> str:
    return (page.get("properties", {}).get(prop_name) or {}).get("url") or ""


async def add_knowledge(
    title: str,
    topics: list[str] | None = None,
    content: str | None = None,
    source_url: str | None = None,
) -> str:
    """Save an item to the Knowledge DB.

    Returns ``"ok"`` | ``"duplicate"`` | ``"error"`` | ``"not_configured"``.
    ``topics`` become Topic multi_select options (auto-created by Notion);
    ``content`` + ``source_url`` populate the page body (reuses the idea body
    builder: a source bookmark + chunked content paragraphs).
    """
    if not config.NOTION_KNOWLEDGE_DB_ID:
        log_action("", "notion_add_knowledge", "", "not_configured")
        return "not_configured"
    if await _recent_duplicate_exists(config.NOTION_KNOWLEDGE_DB_ID, "Title", title):
        log_action("", "notion_add_knowledge", "", "duplicate")
        return "duplicate"

    properties: dict = {"Title": _title_prop(title)}
    if topics:
        properties["Topic"] = {"multi_select": [{"name": t} for t in topics]}
    if source_url:
        properties["Source"] = {"url": source_url}

    payload: dict = {
        "parent": {"database_id": config.NOTION_KNOWLEDGE_DB_ID},
        "properties": properties,
    }
    body_blocks = _idea_body_blocks(content, source_url)
    if body_blocks:
        payload["children"] = body_blocks

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/pages", headers=_headers(), json=payload
            )
        if resp.status_code >= 400:
            logger.error("Notion add_knowledge HTTP %s", resp.status_code)
            log_action("", "notion_add_knowledge", "", f"http_{resp.status_code}")
            return "error"
        log_action("", "notion_add_knowledge", f"topics={topics or []}", "ok")
        return "ok"
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion add_knowledge error: %s", exc.__class__.__name__)
        log_action("", "notion_add_knowledge", "", "error")
        return "error"


async def list_knowledge(topic: str | None = None) -> str:
    """Return Knowledge DB items grouped by topic. Empty string on error/none."""
    if not config.NOTION_KNOWLEDGE_DB_ID:
        log_action("", "notion_list_knowledge", "", "not_configured")
        return ""

    payload: dict = {"page_size": 100}
    if topic:
        payload["filter"] = {"property": "Topic", "multi_select": {"contains": topic}}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_KNOWLEDGE_DB_ID}/query",
                headers=_headers(),
                json=payload,
            )
        if resp.status_code >= 400:
            logger.error("Notion list_knowledge HTTP %s", resp.status_code)
            log_action("", "notion_list_knowledge", "", f"http_{resp.status_code}")
            return ""
        pages = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion list_knowledge error: %s", exc.__class__.__name__)
        log_action("", "notion_list_knowledge", "", "error")
        return ""

    if not pages:
        log_action("", "notion_list_knowledge", "", "empty")
        return ""

    by_topic: dict[str, list[str]] = {}
    for page in pages:
        title = _extract_plain_title(page, "Title") or "(ללא שם)"
        topics = _extract_multi_select(page, "Topic") or ["ללא נושא"]
        for t in topics:
            by_topic.setdefault(t, []).append(title)

    lines: list[str] = []
    for t in sorted(by_topic.keys()):
        lines.append(f"📚 {t}")
        for title in by_topic[t]:
            lines.append(f"  • {title}")
        lines.append("")

    log_action("", "notion_list_knowledge", f"count={len(pages)}", "ok")
    return "\n".join(lines).rstrip()


async def get_knowledge(title: str) -> tuple[str, str]:
    """Read one Knowledge DB item by fuzzy title.

    Returns ``(status, content)`` with status in
    ``{"ok","not_found","ambiguous","error","not_configured"}``. On a single
    match, ``content`` = Topic + Source + page body + comments. Same fuzzy
    substring match as ``get_idea``.
    """
    if not config.NOTION_KNOWLEDGE_DB_ID:
        log_action("", "notion_get_knowledge", "", "not_configured")
        return ("not_configured", "")

    needle = title.strip().lower()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_KNOWLEDGE_DB_ID}/query",
                headers=_headers(),
                json={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion get_knowledge query HTTP %s", resp.status_code)
            log_action("", "notion_get_knowledge", f"title={title}", f"http_{resp.status_code}")
            return ("error", "")
        pages = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion get_knowledge query error: %s", exc.__class__.__name__)
        log_action("", "notion_get_knowledge", f"title={title}", "error")
        return ("error", "")

    matches: list[tuple[str, str]] = []
    for page in pages:
        page_title = _extract_plain_title(page, "Title")
        if needle in page_title.lower():
            matches.append((page.get("id", ""), page_title))

    if not matches:
        log_action("", "notion_get_knowledge", f"title={title}", "not_found")
        return ("not_found", "")
    if len(matches) > 1:
        log_action("", "notion_get_knowledge", f"title={title}", "ambiguous")
        return ("ambiguous", " | ".join(t for _, t in matches))

    page_id, matched_title = matches[0]
    matched_page = next(p for p in pages if p.get("id") == page_id)

    sections: list[str] = [f"# {matched_title}"]
    topics = _extract_multi_select(matched_page, "Topic")
    if topics:
        sections.append("Topics: " + ", ".join(topics))
    source = _extract_url(matched_page, "Source")
    if source:
        sections.append(f"Source: {source}")

    body = await _fetch_block_text(page_id)
    if body:
        sections.append(body)

    comments = await _fetch_comments_text(page_id)
    if comments:
        sections.append("Comments:\n" + comments)

    log_action("", "notion_get_knowledge", f"title={matched_title}", "ok")
    return ("ok", "\n\n".join(sections))


async def archive_task(title: str) -> tuple[str, list[str]]:
    """Archive a task in My Task List by fuzzy title match.

    Returns ``(status, matches)`` where status is one of:
      * ``"ok"`` — exactly one match, archived. ``matches=[matched_title]``.
      * ``"not_found"`` — no task matches. ``matches=[]``.
      * ``"ambiguous"`` — multiple matches. ``matches=[title, title, ...]``.
      * ``"error"`` — HTTP or transport error. ``matches=[]``.

    Match rule: case-insensitive substring against the Task title. Archived
    pages are excluded by Notion's query default — we don't double-archive.
    """
    needle = title.strip().lower()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{NOTION_API}/databases/{config.NOTION_TASK_DB_ID}/query",
                headers=_headers(),
                json={"page_size": 100},
            )
        if resp.status_code >= 400:
            logger.error("Notion archive_task query HTTP %s", resp.status_code)
            log_action("", "notion_archive_task", f"title={title}", f"http_{resp.status_code}")
            return ("error", [])
        pages = resp.json().get("results", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion archive_task query error: %s", exc.__class__.__name__)
        log_action("", "notion_archive_task", f"title={title}", "error")
        return ("error", [])

    matches: list[tuple[str, str]] = []
    for page in pages:
        page_title = _extract_plain_title(page, "Task")
        if needle in page_title.lower():
            matches.append((page.get("id", ""), page_title))

    if not matches:
        log_action("", "notion_archive_task", f"title={title}", "not_found")
        return ("not_found", [])
    if len(matches) > 1:
        log_action("", "notion_archive_task", f"title={title}", "ambiguous")
        return ("ambiguous", [t for _, t in matches])

    page_id, matched_title = matches[0]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.patch(
                f"{NOTION_API}/pages/{page_id}",
                headers=_headers(),
                json={"archived": True},
            )
        if resp.status_code >= 400:
            logger.error("Notion archive_task patch HTTP %s", resp.status_code)
            log_action("", "notion_archive_task", f"title={matched_title}", f"http_{resp.status_code}")
            return ("error", [])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        logger.error("Notion archive_task patch error: %s", exc.__class__.__name__)
        log_action("", "notion_archive_task", f"title={matched_title}", "error")
        return ("error", [])

    log_action("", "notion_archive_task", f"title={matched_title}", "ok")
    return ("ok", [matched_title])


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
    # Property name has a literal leading space in the live schema (" Done").
    not_done_filter = {"property": " Done", "checkbox": {"equals": False}}
    if filter_bucket:
        bucket_id = _BUCKET_NAME_TO_ID.get(filter_bucket)
        if not bucket_id:
            log_action("", "notion_list_tasks", f"unknown_bucket={filter_bucket}", "empty")
            return ""
        payload["filter"] = {
            "and": [
                {"property": "Bucket", "relation": {"contains": bucket_id}},
                not_done_filter,
            ]
        }
    else:
        payload["filter"] = not_done_filter

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
