"""Mocked unit tests for integrations.notion (real-schema variant)."""

from __future__ import annotations

import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations import notion


@pytest.fixture(autouse=True)
def _reset_bucket_cache() -> None:
    notion._reset_bucket_cache()
    yield
    notion._reset_bucket_cache()


def _resp(status_code: int, json_body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body or {}
    return r


def _dedupe_empty() -> MagicMock:
    """Stand-in response for the dedupe pre-query (no recent duplicates)."""
    return _resp(200, {"results": []})


BUCKETS_DB_RESPONSE = {
    "results": [
        {
            "id": "bucket-personal-id",
            "properties": {"Name": {"title": [{"plain_text": "Personal"}]}},
        },
        {
            "id": "bucket-career-id",
            "properties": {"Name": {"title": [{"plain_text": "Career"}]}},
        },
        {
            "id": "bucket-business-id",
            "properties": {"Name": {"title": [{"plain_text": "Business"}]}},
        },
    ]
}


def _scripted_post(script):
    """Return an httpx.AsyncClient stand-in whose ``.post`` returns responses by call order.

    ``script`` is a list of MagicMock responses or callables that take (url, **kwargs).
    """
    client = MagicMock()
    state = {"i": 0}

    def _post(url, **kwargs):
        item = script[state["i"]]
        state["i"] += 1
        # Plain functions => call them (e.g. to raise); MagicMocks pass through.
        if isinstance(item, types.FunctionType):
            return item(url, **kwargs)
        return item

    client.post = AsyncMock(side_effect=_post)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("integrations.notion.httpx.AsyncClient", return_value=cm), client


# ---- add_task --------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_task_resolves_bucket_relation() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),  # dedupe pre-query
        _resp(200, BUCKETS_DB_RESPONSE),  # _load_buckets
        _resp(200, {"id": "new-task"}),  # create page
    ])
    with cm:
        ok = await notion.add_task("לקנות חלב", "Personal")
    assert ok in ("ok", "ok_no_bucket")

    create_call = client.post.await_args_list[2]
    body = create_call.kwargs["json"]
    assert body["parent"]["database_id"]
    assert body["properties"]["Task"]["title"][0]["text"]["content"] == "לקנות חלב"
    assert body["properties"]["Bucket"]["relation"] == [{"id": "bucket-personal-id"}]
    assert "Date" not in body["properties"]


@pytest.mark.asyncio
async def test_add_task_with_due_date() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "new-task"}),
    ])
    with cm:
        ok = await notion.add_task("דוח", "Career", due_date="2026-06-01")
    assert ok in ("ok", "ok_no_bucket")
    body = client.post.await_args_list[2].kwargs["json"]
    assert body["properties"]["Date"]["date"]["start"] == "2026-06-01"
    assert body["properties"]["Bucket"]["relation"] == [{"id": "bucket-career-id"}]


@pytest.mark.asyncio
async def test_add_task_unknown_bucket_creates_without_relation() -> None:
    """If bucket name doesn't exist in My Life Buckets, create without Bucket prop."""
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "new-task"}),
    ])
    with cm:
        ok = await notion.add_task("משימה", "DoesNotExist")
    assert ok in ("ok", "ok_no_bucket")
    body = client.post.await_args_list[2].kwargs["json"]
    assert "Bucket" not in body["properties"]
    assert body["properties"]["Task"]["title"][0]["text"]["content"] == "משימה"


@pytest.mark.asyncio
async def test_add_task_http_error() -> None:
    cm, _ = _scripted_post([
        _dedupe_empty(),
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(400, {"error": "bad"}),
    ])
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok == "error"


@pytest.mark.asyncio
async def test_add_task_timeout_on_create() -> None:
    """Bucket load succeeds, page create times out."""
    def create_timeout(url, **kwargs):
        raise httpx.TimeoutException("timeout")

    cm, _ = _scripted_post([
        _dedupe_empty(),
        _resp(200, BUCKETS_DB_RESPONSE),
        create_timeout,
    ])
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok == "error"


@pytest.mark.asyncio
async def test_add_task_when_bucket_load_fails() -> None:
    """Bucket load HTTP error → cache empty → create succeeds without Bucket."""
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(500),  # _load_buckets fails
        _resp(200, {"id": "new"}),
    ])
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok in ("ok", "ok_no_bucket")
    body = client.post.await_args_list[2].kwargs["json"]
    assert "Bucket" not in body["properties"]


# ---- add_idea --------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_idea_success() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        ok = await notion.add_idea("רעיון חדש", description="פרטים")
    assert ok == "ok"
    body = client.post.await_args_list[1].kwargs["json"]
    assert body["properties"]["Idea"]["title"][0]["text"]["content"] == "רעיון חדש"
    assert (
        body["properties"]["Description"]["rich_text"][0]["text"]["content"]
        == "פרטים"
    )
    assert "Bucket" not in body["properties"]


@pytest.mark.asyncio
async def test_add_idea_no_description() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        ok = await notion.add_idea("רעיון")
    assert ok == "ok"
    body = client.post.await_args_list[1].kwargs["json"]
    assert "Description" not in body["properties"]


@pytest.mark.asyncio
async def test_add_idea_with_bucket() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        ok = await notion.add_idea("רעיון", bucket="Personal")
    assert ok == "ok"
    body = client.post.await_args_list[2].kwargs["json"]
    assert body["properties"]["Bucket"]["relation"] == [{"id": "bucket-personal-id"}]


@pytest.mark.asyncio
async def test_add_idea_unknown_bucket_creates_without_relation() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        ok = await notion.add_idea("רעיון", bucket="NoSuchBucket")
    assert ok == "ok_no_bucket"
    body = client.post.await_args_list[2].kwargs["json"]
    assert "Bucket" not in body["properties"]


@pytest.mark.asyncio
async def test_add_idea_duplicate_returns_duplicate() -> None:
    """A recently-created idea with the same title should short-circuit."""
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cm, client = _scripted_post([
        _resp(200, {"results": [{"id": "dup", "created_time": now_iso}]}),
    ])
    with cm:
        ok = await notion.add_idea("Recipe App")
    assert ok == "duplicate"
    # Only the dedupe query should have run.
    assert client.post.await_count == 1


@pytest.mark.asyncio
async def test_add_task_duplicate_returns_duplicate() -> None:
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cm, client = _scripted_post([
        _resp(200, {"results": [{"id": "dup", "created_time": now_iso}]}),
    ])
    with cm:
        ok = await notion.add_task("Buy milk", "Personal")
    assert ok == "duplicate"
    assert client.post.await_count == 1


# ---- add_idea_comment ------------------------------------------------------


def _idea_page(page_id: str, title: str) -> dict:
    return {
        "id": page_id,
        "properties": {"Idea": {"title": [{"plain_text": title}]}},
    }


@pytest.mark.asyncio
async def test_add_idea_comment_single_match() -> None:
    cm, client = _scripted_post([
        _resp(200, {"results": [_idea_page("idea-1", "Recipe App")]}),
        _resp(200, {"id": "comment-1"}),
    ])
    with cm:
        status, matches = await notion.add_idea_comment("recipe", "needs auth")
    assert status == "ok"
    assert matches == ["Recipe App"]
    comment_call = client.post.await_args_list[1]
    assert comment_call.args[0].endswith("/comments")
    assert comment_call.kwargs["json"]["parent"] == {"page_id": "idea-1"}
    assert (
        comment_call.kwargs["json"]["rich_text"][0]["text"]["content"] == "needs auth"
    )


@pytest.mark.asyncio
async def test_add_idea_comment_not_found() -> None:
    cm, _ = _scripted_post([
        _resp(200, {"results": [_idea_page("idea-1", "Other")]}),
    ])
    with cm:
        status, matches = await notion.add_idea_comment("recipe", "x")
    assert status == "not_found"
    assert matches == []


@pytest.mark.asyncio
async def test_add_idea_comment_ambiguous() -> None:
    cm, _ = _scripted_post([
        _resp(200, {"results": [
            _idea_page("idea-1", "Recipe App"),
            _idea_page("idea-2", "Recipe App v2"),
        ]}),
    ])
    with cm:
        status, matches = await notion.add_idea_comment("recipe", "x")
    assert status == "ambiguous"
    assert set(matches) == {"Recipe App", "Recipe App v2"}


# ---- list_tasks ------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_empty() -> None:
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"results": []}),
    ])
    with cm:
        out = await notion.list_tasks()
    assert out == ""


@pytest.mark.asyncio
async def test_list_tasks_formats_by_bucket() -> None:
    pages = {
        "results": [
            {
                "properties": {
                    "Task": {"title": [{"plain_text": "משימה א"}]},
                    "Bucket": {"relation": [{"id": "bucket-personal-id"}]},
                    "Date": {"date": {"start": "2026-06-01"}},
                    "Priority": {"select": {"name": "1"}},
                }
            },
            {
                "properties": {
                    "Task": {"title": [{"plain_text": "משימה ב"}]},
                    "Bucket": {"relation": [{"id": "bucket-business-id"}]},
                    "Date": None,
                    "Priority": None,
                }
            },
        ]
    }
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, pages),
    ])
    with cm:
        out = await notion.list_tasks()
    assert "📂 Business" in out
    assert "📂 Personal" in out
    assert "משימה א" in out
    assert "משימה ב" in out
    assert "2026-06-01" in out
    assert "P1" in out


@pytest.mark.asyncio
async def test_list_tasks_with_bucket_filter() -> None:
    cm, client = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"results": []}),
    ])
    with cm:
        await notion.list_tasks(filter_bucket="Personal")
    query_call = client.post.await_args_list[1]
    body = query_call.kwargs["json"]
    clauses = body["filter"]["and"]
    bucket_clause = next(c for c in clauses if c.get("property") == "Bucket")
    done_clause = next(c for c in clauses if c.get("property") == " Done")
    assert bucket_clause["relation"]["contains"] == "bucket-personal-id"
    assert done_clause["checkbox"] == {"equals": False}


@pytest.mark.asyncio
async def test_list_tasks_unfiltered_excludes_done() -> None:
    cm, client = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"results": []}),
    ])
    with cm:
        await notion.list_tasks()
    query_call = client.post.await_args_list[1]
    body = query_call.kwargs["json"]
    assert body["filter"] == {"property": " Done", "checkbox": {"equals": False}}


@pytest.mark.asyncio
async def test_list_tasks_unknown_filter_returns_empty() -> None:
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
    ])
    with cm:
        out = await notion.list_tasks(filter_bucket="NonexistentBucket")
    assert out == ""


@pytest.mark.asyncio
async def test_list_tasks_http_error() -> None:
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(500),
    ])
    with cm:
        out = await notion.list_tasks()
    assert out == ""


# ---- archive_task ----------------------------------------------------------


def _scripted_client(post_script, patch_script):
    """AsyncClient stand-in with scriptable post() and patch() side effects."""
    client = MagicMock()
    pi = {"i": 0}
    ti = {"i": 0}

    async def _post(url, **kwargs):
        item = post_script[pi["i"]]
        pi["i"] += 1
        return item

    async def _patch(url, **kwargs):
        item = patch_script[ti["i"]]
        ti["i"] += 1
        return item

    client.post = AsyncMock(side_effect=_post)
    client.patch = AsyncMock(side_effect=_patch)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("integrations.notion.httpx.AsyncClient", return_value=cm), client


def _task_page(page_id: str, title: str) -> dict:
    return {
        "id": page_id,
        "properties": {"Task": {"title": [{"plain_text": title}]}},
    }


@pytest.mark.asyncio
async def test_archive_task_single_match_archives() -> None:
    cm, client = _scripted_client(
        post_script=[_resp(200, {"results": [_task_page("page-1", "לקנות חלב")]})],
        patch_script=[_resp(200, {"id": "page-1", "archived": True})],
    )
    with cm:
        status, matches = await notion.archive_task("חלב")
    assert status == "ok"
    assert matches == ["לקנות חלב"]
    patch_call = client.patch.await_args
    assert patch_call.args[0].endswith("/pages/page-1")
    assert patch_call.kwargs["json"] == {"archived": True}


@pytest.mark.asyncio
async def test_archive_task_not_found() -> None:
    cm, _ = _scripted_client(
        post_script=[_resp(200, {"results": [_task_page("page-1", "משימה אחרת")]})],
        patch_script=[],
    )
    with cm:
        status, matches = await notion.archive_task("חלב")
    assert status == "not_found"
    assert matches == []


@pytest.mark.asyncio
async def test_archive_task_ambiguous_returns_titles() -> None:
    cm, client = _scripted_client(
        post_script=[_resp(200, {"results": [
            _task_page("page-1", "לקנות חלב"),
            _task_page("page-2", "לקנות חלב לקפה"),
        ]})],
        patch_script=[],
    )
    with cm:
        status, matches = await notion.archive_task("חלב")
    assert status == "ambiguous"
    assert set(matches) == {"לקנות חלב", "לקנות חלב לקפה"}
    client.patch.assert_not_called()


@pytest.mark.asyncio
async def test_archive_task_query_http_error() -> None:
    cm, _ = _scripted_client(
        post_script=[_resp(500)],
        patch_script=[],
    )
    with cm:
        status, matches = await notion.archive_task("חלב")
    assert status == "error"
    assert matches == []


@pytest.mark.asyncio
async def test_archive_task_patch_http_error() -> None:
    cm, _ = _scripted_client(
        post_script=[_resp(200, {"results": [_task_page("page-1", "לקנות חלב")]})],
        patch_script=[_resp(500)],
    )
    with cm:
        status, matches = await notion.archive_task("חלב")
    assert status == "error"
    assert matches == []


@pytest.mark.asyncio
async def test_archive_task_case_insensitive_match() -> None:
    cm, _ = _scripted_client(
        post_script=[_resp(200, {"results": [_task_page("page-1", "Apple RSU Update")]})],
        patch_script=[_resp(200, {"archived": True})],
    )
    with cm:
        status, matches = await notion.archive_task("apple rsu")
    assert status == "ok"
    assert matches == ["Apple RSU Update"]


# ---- archive_idea / list_ideas ---------------------------------------------


@pytest.mark.asyncio
async def test_archive_idea_single_match_archives() -> None:
    cm, client = _scripted_client(
        post_script=[_resp(200, {"results": [_idea_page("idea-1", "Recipe App")]})],
        patch_script=[_resp(200, {"id": "idea-1", "archived": True})],
    )
    with cm:
        status, matches = await notion.archive_idea("recipe")
    assert status == "ok"
    assert matches == ["Recipe App"]
    patch_call = client.patch.await_args
    assert patch_call.args[0].endswith("/pages/idea-1")
    assert patch_call.kwargs["json"] == {"archived": True}


@pytest.mark.asyncio
async def test_archive_idea_not_found() -> None:
    cm, _ = _scripted_client(
        post_script=[_resp(200, {"results": [_idea_page("idea-1", "Other")]})],
        patch_script=[],
    )
    with cm:
        status, matches = await notion.archive_idea("recipe")
    assert status == "not_found"
    assert matches == []


@pytest.mark.asyncio
async def test_archive_idea_ambiguous() -> None:
    cm, _ = _scripted_client(
        post_script=[_resp(200, {"results": [
            _idea_page("idea-1", "Recipe App"),
            _idea_page("idea-2", "Recipe App v2"),
        ]})],
        patch_script=[],
    )
    with cm:
        status, matches = await notion.archive_idea("recipe")
    assert status == "ambiguous"
    assert set(matches) == {"Recipe App", "Recipe App v2"}


@pytest.mark.asyncio
async def test_list_ideas_groups_by_bucket() -> None:
    pages = {
        "results": [
            {
                "properties": {
                    "Idea": {"title": [{"plain_text": "Idea A"}]},
                    "Bucket": {"relation": [{"id": "bucket-personal-id"}]},
                }
            },
            {
                "properties": {
                    "Idea": {"title": [{"plain_text": "Idea B"}]},
                    "Bucket": {"relation": []},
                }
            },
        ]
    }
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, pages),
    ])
    with cm:
        out = await notion.list_ideas()
    assert "💡 Personal" in out
    assert "Idea A" in out
    assert "Idea B" in out


@pytest.mark.asyncio
async def test_list_ideas_unknown_bucket_returns_empty() -> None:
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
    ])
    with cm:
        out = await notion.list_ideas(filter_bucket="NopeBucket")
    assert out == ""


# ---- bucket cache ----------------------------------------------------------


@pytest.mark.asyncio
async def test_bucket_cache_loads_once() -> None:
    """Two add_task calls in a row should only hit the buckets DB once."""
    cm, client = _scripted_post([
        _dedupe_empty(),  # add_task("a") dedupe
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "t1"}),
        _dedupe_empty(),  # add_task("b") dedupe
        _resp(200, {"id": "t2"}),
    ])
    with cm:
        await notion.add_task("a", "Personal")
        await notion.add_task("b", "Career")

    # 5 total POSTs: 2 dedupe + 1 buckets load + 2 page creates.
    assert client.post.await_count == 5


# ---- add_idea with content / source_url (knowledge DB) ---------------------


@pytest.mark.asyncio
async def test_add_idea_writes_body_blocks_for_content_and_url() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        ok = await notion.add_idea(
            "Wineries",
            content="Tishbi - open Sat 10-17. Recanati - open Sat.",
            source_url="https://example.com/wineries",
        )
    assert ok == "ok"
    body = client.post.await_args_list[1].kwargs["json"]
    children = body["children"]
    # Source paragraph + bookmark + at least one content paragraph.
    assert any(b.get("type") == "bookmark" for b in children)
    assert children[1]["bookmark"]["url"] == "https://example.com/wineries"
    joined = "".join(
        rt["text"]["content"]
        for b in children
        if b.get("type") == "paragraph"
        for rt in b["paragraph"]["rich_text"]
    )
    assert "Tishbi" in joined
    assert "https://example.com/wineries" in joined


@pytest.mark.asyncio
async def test_add_idea_chunks_long_content() -> None:
    long_content = "x" * 4100  # > 2 * 1900 → 3 paragraph blocks
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        ok = await notion.add_idea("Long", content=long_content)
    assert ok == "ok"
    children = client.post.await_args_list[1].kwargs["json"]["children"]
    para = [b for b in children if b.get("type") == "paragraph"]
    assert len(para) == 3
    assert all(
        len(b["paragraph"]["rich_text"][0]["text"]["content"]) <= 1900 for b in para
    )


@pytest.mark.asyncio
async def test_add_idea_no_content_omits_children() -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, {"id": "new-idea"}),
    ])
    with cm:
        await notion.add_idea("Plain idea")
    body = client.post.await_args_list[1].kwargs["json"]
    assert "children" not in body


# ---- get_idea --------------------------------------------------------------


def _scripted_get_post(post_script, get_script):
    """AsyncClient stand-in that scripts ``.post`` and ``.get`` by call order."""
    client = MagicMock()
    pstate = {"i": 0}
    gstate = {"i": 0}

    def _post(url, **kwargs):
        item = post_script[pstate["i"]]
        pstate["i"] += 1
        return item

    def _get(url, **kwargs):
        item = get_script[gstate["i"]]
        gstate["i"] += 1
        return item

    client.post = AsyncMock(side_effect=_post)
    client.get = AsyncMock(side_effect=_get)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return patch("integrations.notion.httpx.AsyncClient", return_value=cm), client


@pytest.mark.asyncio
async def test_get_idea_single_match_assembles_content() -> None:
    page = {
        "id": "idea-1",
        "properties": {
            "Idea": {"title": [{"plain_text": "Wineries"}]},
            "Description": {"rich_text": [{"plain_text": "Saturday wineries"}]},
        },
    }
    blocks = {
        "results": [
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Tishbi open Sat"}]}},
            {"type": "bookmark", "bookmark": {"url": "https://example.com/w"}},
        ]
    }
    comments = {"results": [{"rich_text": [{"plain_text": "visited, great"}]}]}
    cm, _ = _scripted_get_post(
        post_script=[_resp(200, {"results": [page]})],
        get_script=[_resp(200, blocks), _resp(200, comments)],
    )
    with cm:
        status, content = await notion.get_idea("winer")
    assert status == "ok"
    assert "Wineries" in content
    assert "Saturday wineries" in content
    assert "Tishbi open Sat" in content
    assert "https://example.com/w" in content
    assert "visited, great" in content


@pytest.mark.asyncio
async def test_get_idea_not_found() -> None:
    cm, _ = _scripted_get_post(
        post_script=[_resp(200, {"results": [_idea_page("idea-1", "Other")]})],
        get_script=[],
    )
    with cm:
        status, content = await notion.get_idea("winer")
    assert status == "not_found"
    assert content == ""


@pytest.mark.asyncio
async def test_get_idea_ambiguous_returns_titles() -> None:
    cm, _ = _scripted_get_post(
        post_script=[
            _resp(200, {"results": [
                _idea_page("a", "Wine bars"),
                _idea_page("b", "Wineries north"),
            ]})
        ],
        get_script=[],
    )
    with cm:
        status, content = await notion.get_idea("wine")
    assert status == "ambiguous"
    assert "Wine bars" in content and "Wineries north" in content


@pytest.mark.asyncio
async def test_get_idea_query_http_error() -> None:
    cm, _ = _scripted_get_post(
        post_script=[_resp(500)],
        get_script=[],
    )
    with cm:
        status, content = await notion.get_idea("x")
    assert status == "error"
    assert content == ""


# ---- Knowledge DB ----------------------------------------------------------


@pytest.fixture
def _knowledge_db(monkeypatch) -> None:
    """Configure a Knowledge DB id for the duration of a test."""
    monkeypatch.setattr(notion.config, "NOTION_KNOWLEDGE_DB_ID", "kdb-1")


def _knowledge_page(page_id: str, title: str, topics=None, source=None) -> dict:
    props: dict = {"Title": {"title": [{"plain_text": title}]}}
    if topics is not None:
        props["Topic"] = {"multi_select": [{"name": t} for t in topics]}
    if source is not None:
        props["Source"] = {"url": source}
    return {"id": page_id, "properties": props}


@pytest.mark.asyncio
async def test_add_knowledge_not_configured() -> None:
    # NOTION_KNOWLEDGE_DB_ID unset by default → short-circuit, no HTTP.
    assert await notion.add_knowledge("Wineries") == "not_configured"


@pytest.mark.asyncio
async def test_add_knowledge_writes_props_and_body(_knowledge_db) -> None:
    cm, client = _scripted_post([
        _dedupe_empty(),
        _resp(200, {"id": "k1"}),
    ])
    with cm:
        ok = await notion.add_knowledge(
            "Saturday Wineries",
            topics=["Wine", "Travel"],
            content="Tishbi open Sat 10-17.",
            source_url="https://example.com/w",
        )
    assert ok == "ok"
    body = client.post.await_args_list[1].kwargs["json"]
    assert body["parent"]["database_id"] == "kdb-1"
    assert body["properties"]["Title"]["title"][0]["text"]["content"] == "Saturday Wineries"
    assert body["properties"]["Topic"]["multi_select"] == [{"name": "Wine"}, {"name": "Travel"}]
    assert body["properties"]["Source"]["url"] == "https://example.com/w"
    assert any(b.get("type") == "bookmark" for b in body["children"])


@pytest.mark.asyncio
async def test_add_knowledge_duplicate(_knowledge_db) -> None:
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cm, client = _scripted_post([
        _resp(200, {"results": [{"id": "dup", "created_time": now_iso}]}),
    ])
    with cm:
        ok = await notion.add_knowledge("Saturday Wineries")
    assert ok == "duplicate"
    assert client.post.await_count == 1


@pytest.mark.asyncio
async def test_list_knowledge_groups_by_topic(_knowledge_db) -> None:
    cm, _ = _scripted_post([
        _resp(200, {"results": [
            _knowledge_page("k1", "Saturday Wineries", topics=["Wine"]),
            _knowledge_page("k2", "Negev road trip", topics=["Travel"]),
        ]}),
    ])
    with cm:
        text = await notion.list_knowledge()
    assert "📚 Wine" in text
    assert "Saturday Wineries" in text
    assert "📚 Travel" in text


@pytest.mark.asyncio
async def test_list_knowledge_not_configured() -> None:
    assert await notion.list_knowledge() == ""


@pytest.mark.asyncio
async def test_get_knowledge_assembles_content(_knowledge_db) -> None:
    page = _knowledge_page(
        "k1", "Saturday Wineries", topics=["Wine"], source="https://example.com/w"
    )
    blocks = {"results": [
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Tishbi open Sat"}]}},
    ]}
    comments = {"results": []}
    cm, _ = _scripted_get_post(
        post_script=[_resp(200, {"results": [page]})],
        get_script=[_resp(200, blocks), _resp(200, comments)],
    )
    with cm:
        status, content = await notion.get_knowledge("winer")
    assert status == "ok"
    assert "Saturday Wineries" in content
    assert "Topics: Wine" in content
    assert "https://example.com/w" in content
    assert "Tishbi open Sat" in content


@pytest.mark.asyncio
async def test_get_knowledge_not_configured() -> None:
    status, content = await notion.get_knowledge("x")
    assert status == "not_configured"
    assert content == ""


@pytest.mark.asyncio
async def test_get_knowledge_ambiguous(_knowledge_db) -> None:
    cm, _ = _scripted_get_post(
        post_script=[_resp(200, {"results": [
            _knowledge_page("a", "Wine bars"),
            _knowledge_page("b", "Wineries north"),
        ]})],
        get_script=[],
    )
    with cm:
        status, content = await notion.get_knowledge("wine")
    assert status == "ambiguous"
    assert "Wine bars" in content and "Wineries north" in content
