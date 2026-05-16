"""Mocked unit tests for integrations.notion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations import notion


def _resp(status_code: int, json_body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body or {}
    return r


def _patch_async_client(post_resp):
    """Patch httpx.AsyncClient so `.post(...)` returns ``post_resp``."""
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=post_resp)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return patch("integrations.notion.httpx.AsyncClient", return_value=mock_cm), mock_client


@pytest.mark.asyncio
async def test_add_task_success() -> None:
    cm, client = _patch_async_client(_resp(200, {"id": "abc"}))
    with cm:
        ok = await notion.add_task("לקנות חלב", "Personal")
    assert ok is True
    body = client.post.await_args.kwargs["json"]
    assert body["parent"]["database_id"]
    assert body["properties"]["Name"]["title"][0]["text"]["content"] == "לקנות חלב"
    assert body["properties"]["Bucket"]["select"]["name"] == "Personal"
    assert "Due" not in body["properties"]


@pytest.mark.asyncio
async def test_add_task_with_due_date() -> None:
    cm, client = _patch_async_client(_resp(200, {"id": "abc"}))
    with cm:
        ok = await notion.add_task("דוח", "Career", due_date="2026-06-01")
    assert ok is True
    body = client.post.await_args.kwargs["json"]
    assert body["properties"]["Due"]["date"]["start"] == "2026-06-01"


@pytest.mark.asyncio
async def test_add_task_http_error() -> None:
    cm, _ = _patch_async_client(_resp(400, {"error": "bad request"}))
    with cm:
        ok = await notion.add_task("x", "Personal")
    assert ok is False


@pytest.mark.asyncio
async def test_add_task_timeout() -> None:
    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    with patch("integrations.notion.httpx.AsyncClient", return_value=mock_cm):
        ok = await notion.add_task("x", "Personal")
    assert ok is False


@pytest.mark.asyncio
async def test_add_idea_success() -> None:
    cm, client = _patch_async_client(_resp(200, {"id": "abc"}))
    with cm:
        ok = await notion.add_idea("רעיון חדש", description="פרטים")
    assert ok is True
    body = client.post.await_args.kwargs["json"]
    assert body["properties"]["Name"]["title"][0]["text"]["content"] == "רעיון חדש"
    assert (
        body["properties"]["Description"]["rich_text"][0]["text"]["content"]
        == "פרטים"
    )


@pytest.mark.asyncio
async def test_add_idea_no_description() -> None:
    cm, client = _patch_async_client(_resp(200, {"id": "abc"}))
    with cm:
        ok = await notion.add_idea("רעיון")
    assert ok is True
    body = client.post.await_args.kwargs["json"]
    assert "Description" not in body["properties"]


@pytest.mark.asyncio
async def test_list_tasks_empty() -> None:
    cm, _ = _patch_async_client(_resp(200, {"results": []}))
    with cm:
        out = await notion.list_tasks()
    assert out == ""


@pytest.mark.asyncio
async def test_list_tasks_formats_by_bucket() -> None:
    pages = {
        "results": [
            {
                "properties": {
                    "Name": {"title": [{"plain_text": "משימה א"}]},
                    "Bucket": {"select": {"name": "Personal"}},
                    "Due": {"date": {"start": "2026-06-01"}},
                    "Priority": {"select": {"name": "High"}},
                }
            },
            {
                "properties": {
                    "Name": {"title": [{"plain_text": "משימה ב"}]},
                    "Bucket": {"select": {"name": "Business"}},
                    "Due": None,
                    "Priority": None,
                }
            },
        ]
    }
    cm, _ = _patch_async_client(_resp(200, pages))
    with cm:
        out = await notion.list_tasks()
    assert "📂 Business" in out
    assert "📂 Personal" in out
    assert "משימה א" in out
    assert "משימה ב" in out
    assert "2026-06-01" in out
    assert "High" in out


@pytest.mark.asyncio
async def test_list_tasks_with_bucket_filter() -> None:
    cm, client = _patch_async_client(_resp(200, {"results": []}))
    with cm:
        await notion.list_tasks(filter_bucket="Personal")
    body = client.post.await_args.kwargs["json"]
    assert body["filter"]["property"] == "Bucket"
    assert body["filter"]["select"]["equals"] == "Personal"


@pytest.mark.asyncio
async def test_list_tasks_http_error() -> None:
    cm, _ = _patch_async_client(_resp(500))
    with cm:
        out = await notion.list_tasks()
    assert out == ""
