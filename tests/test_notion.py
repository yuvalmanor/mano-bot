"""Mocked unit tests for integrations.notion (real-schema variant)."""

from __future__ import annotations

import types
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
        _resp(200, BUCKETS_DB_RESPONSE),  # _load_buckets
        _resp(200, {"id": "new-task"}),  # create page
    ])
    with cm:
        ok = await notion.add_task("לקנות חלב", "Personal")
    assert ok is True

    # Second call is the page create — verify schema.
    create_call = client.post.await_args_list[1]
    body = create_call.kwargs["json"]
    assert body["parent"]["database_id"]
    assert body["properties"]["Task"]["title"][0]["text"]["content"] == "לקנות חלב"
    assert body["properties"]["Bucket"]["relation"] == [{"id": "bucket-personal-id"}]
    assert "Date" not in body["properties"]


@pytest.mark.asyncio
async def test_add_task_with_due_date() -> None:
    cm, client = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "new-task"}),
    ])
    with cm:
        ok = await notion.add_task("דוח", "Career", due_date="2026-06-01")
    assert ok is True
    body = client.post.await_args_list[1].kwargs["json"]
    assert body["properties"]["Date"]["date"]["start"] == "2026-06-01"
    assert body["properties"]["Bucket"]["relation"] == [{"id": "bucket-career-id"}]


@pytest.mark.asyncio
async def test_add_task_unknown_bucket_creates_without_relation() -> None:
    """If bucket name doesn't exist in My Life Buckets, create without Bucket prop."""
    cm, client = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "new-task"}),
    ])
    with cm:
        ok = await notion.add_task("משימה", "DoesNotExist")
    assert ok is True
    body = client.post.await_args_list[1].kwargs["json"]
    assert "Bucket" not in body["properties"]
    assert body["properties"]["Task"]["title"][0]["text"]["content"] == "משימה"


@pytest.mark.asyncio
async def test_add_task_http_error() -> None:
    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(400, {"error": "bad"}),
    ])
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok is False


@pytest.mark.asyncio
async def test_add_task_timeout_on_create() -> None:
    """Bucket load succeeds, page create times out."""
    def create_timeout(url, **kwargs):
        raise httpx.TimeoutException("timeout")

    cm, _ = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        create_timeout,
    ])
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok is False


@pytest.mark.asyncio
async def test_add_task_when_bucket_load_fails() -> None:
    """Bucket load HTTP error → cache empty → create succeeds without Bucket."""
    cm, client = _scripted_post([
        _resp(500),  # _load_buckets fails
        _resp(200, {"id": "new"}),
    ])
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok is True
    body = client.post.await_args_list[1].kwargs["json"]
    assert "Bucket" not in body["properties"]


# ---- add_idea --------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_idea_success() -> None:
    cm, client = _scripted_post([_resp(200, {"id": "new-idea"})])
    with cm:
        ok = await notion.add_idea("רעיון חדש", description="פרטים")
    assert ok is True
    body = client.post.await_args.kwargs["json"]
    assert body["properties"]["Idea"]["title"][0]["text"]["content"] == "רעיון חדש"
    assert (
        body["properties"]["Description"]["rich_text"][0]["text"]["content"]
        == "פרטים"
    )


@pytest.mark.asyncio
async def test_add_idea_no_description() -> None:
    cm, client = _scripted_post([_resp(200, {"id": "new-idea"})])
    with cm:
        ok = await notion.add_idea("רעיון")
    assert ok is True
    body = client.post.await_args.kwargs["json"]
    assert "Description" not in body["properties"]


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


# ---- bucket cache ----------------------------------------------------------


@pytest.mark.asyncio
async def test_bucket_cache_loads_once() -> None:
    """Two add_task calls in a row should only hit the buckets DB once."""
    cm, client = _scripted_post([
        _resp(200, BUCKETS_DB_RESPONSE),
        _resp(200, {"id": "t1"}),
        _resp(200, {"id": "t2"}),
    ])
    with cm:
        await notion.add_task("a", "Personal")
        await notion.add_task("b", "Career")

    # 3 total POSTs: 1 buckets load + 2 page creates.
    assert client.post.await_count == 3
    first_url = client.post.await_args_list[0].args[0]
    assert "/databases/" in first_url  # the buckets query
