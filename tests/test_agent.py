"""Mocked unit tests for Claude agent (incl. tool-use loop)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_agent.agent import (
    HEBREW_ERROR,
    HEBREW_PERMISSION_DENIED,
    _scrub_llm_punctuation,
    run,
)


def test_scrub_em_dash_replaced():
    assert _scrub_llm_punctuation("Same limitation — read access") == "Same limitation - read access"


def test_scrub_en_dash_replaced():
    assert _scrub_llm_punctuation("pages 3–7") == "pages 3-7"


def test_scrub_leaves_plain_hyphen_alone():
    assert _scrub_llm_punctuation("a-b-c") == "a-b-c"


def _text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _tool_use_block(tool_id: str, name: str, input_dict: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = name
    block.input = input_dict
    return block


def _response(stop_reason: str, content: list) -> MagicMock:
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content
    return resp


@pytest.mark.asyncio
async def test_agent_run_single_message() -> None:
    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_response("end_turn", [_text_block("שלום")])
        )

        reply = await run("+972542159121", "היי")
        assert reply == "שלום"
        mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_agent_run_conversation_history() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY

    phone = "+972542159121"
    CONVERSATION_HISTORY.clear()

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_response("end_turn", [_text_block("תשובה 1")])
        )

        reply1 = await run(phone, "שאלה 1")
        assert reply1 == "תשובה 1"
        assert len(CONVERSATION_HISTORY[phone]) == 2

        captured = {}

        def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _response("end_turn", [_text_block("תשובה 2")])

        mock_client.messages.create = AsyncMock(side_effect=capture)
        reply2 = await run(phone, "שאלה 2")
        assert reply2 == "תשובה 2"
        # On second call, history (2) + new user msg = 3 messages sent
        assert len(captured["messages"]) == 3
        assert captured["messages"][0]["role"] == "user"
        assert captured["messages"][1]["role"] == "assistant"
        assert captured["messages"][2]["role"] == "user"
        assert len(CONVERSATION_HISTORY[phone]) == 4


@pytest.mark.asyncio
async def test_agent_run_history_trimming() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY, MAX_HISTORY_TURNS

    phone = "+972999999999"
    CONVERSATION_HISTORY.clear()
    CONVERSATION_HISTORY[phone] = []

    for i in range(MAX_HISTORY_TURNS + 2):
        CONVERSATION_HISTORY[phone].append({"role": "user", "content": f"msg {i}"})
        CONVERSATION_HISTORY[phone].append(
            {"role": "assistant", "content": f"reply {i}"}
        )

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_response("end_turn", [_text_block("ok")])
        )

        await run(phone, "new msg")
        assert len(CONVERSATION_HISTORY[phone]) <= MAX_HISTORY_TURNS * 2


@pytest.mark.asyncio
async def test_agent_run_api_error() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY

    phone = "+972111111111"
    CONVERSATION_HISTORY.clear()

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=Exception("boom"))

        reply = await run(phone, "שאלה")
        assert reply == HEBREW_ERROR


@pytest.mark.asyncio
async def test_agent_separate_histories() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY

    phone1 = "+972111111111"
    phone2 = "+972222222222"
    CONVERSATION_HISTORY.clear()

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=_response("end_turn", [_text_block("reply")])
        )

        await run(phone1, "msg1")
        await run(phone2, "msg2")
        assert len(CONVERSATION_HISTORY[phone1]) == 2
        assert len(CONVERSATION_HISTORY[phone2]) == 2


# ---- Tool-use tests --------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_tool_use_notion_add_task_authorized() -> None:
    """Yuval has 'notion' permission — tool should be dispatched and reply produced."""
    from claude_agent.agent import CONVERSATION_HISTORY

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch("claude_agent.agent.notion.add_task", new=AsyncMock(return_value=True)) as mock_add,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        responses = [
            _response(
                "tool_use",
                [
                    _tool_use_block(
                        "tu_1",
                        "notion_add_task",
                        {"title": "לקנות חלב", "bucket": "Personal"},
                    )
                ],
            ),
            _response("end_turn", [_text_block("נוספה משימה")]),
        ]
        mock_client.messages.create = AsyncMock(side_effect=responses)

        reply = await run(phone, "תוסיף משימה לקנות חלב")
        assert reply == "נוספה משימה"
        mock_add.assert_awaited_once_with(
            title="לקנות חלב", bucket="Personal", due_date=None
        )
        assert mock_client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_agent_tool_use_permission_denied_for_eden() -> None:
    """Eden has no notion permission — dispatch must NOT run; tool_result is_error."""
    from claude_agent.agent import CONVERSATION_HISTORY

    CONVERSATION_HISTORY.clear()
    phone = "+972546900908"  # Eden

    captured_messages: list = []

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch("claude_agent.agent.notion.add_task", new=AsyncMock(return_value=True)) as mock_add,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        responses = [
            _response(
                "tool_use",
                [
                    _tool_use_block(
                        "tu_1", "notion_add_task", {"title": "x", "bucket": "Personal"}
                    )
                ],
            ),
            _response("end_turn", [_text_block("אין הרשאה")]),
        ]

        def capture(**kwargs):
            captured_messages.append(list(kwargs["messages"]))
            return responses[len(captured_messages) - 1]

        mock_client.messages.create = AsyncMock(side_effect=capture)

        reply = await run(phone, "תוסיף משימה")
        assert reply == "אין הרשאה"
        mock_add.assert_not_awaited()

        # The second call's last message is the tool_result; verify is_error=True.
        last_msgs = captured_messages[1]
        tool_result_msg = last_msgs[-1]
        assert tool_result_msg["role"] == "user"
        tool_result_block = tool_result_msg["content"][0]
        assert tool_result_block["type"] == "tool_result"
        assert tool_result_block.get("is_error") is True
        assert tool_result_block["content"] == HEBREW_PERMISSION_DENIED


@pytest.mark.asyncio
async def test_agent_tool_use_list_tasks() -> None:
    from claude_agent.agent import CONVERSATION_HISTORY

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch(
            "claude_agent.agent.notion.list_tasks",
            new=AsyncMock(return_value="📂 Personal\n  • לקנות חלב"),
        ) as mock_list,
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        responses = [
            _response(
                "tool_use",
                [_tool_use_block("tu_1", "notion_list_tasks", {})],
            ),
            _response("end_turn", [_text_block("הנה המשימות שלך")]),
        ]
        mock_client.messages.create = AsyncMock(side_effect=responses)

        reply = await run(phone, "מה המשימות שלי?")
        assert reply == "הנה המשימות שלי"[: len("הנה המשימות שלי")] or reply == "הנה המשימות שלך"
        mock_list.assert_awaited_once_with(filter_bucket=None)


@pytest.mark.asyncio
async def test_agent_tool_use_loop_limit() -> None:
    """Looping tool_use beyond MAX_TOOL_ITERATIONS returns Hebrew error."""
    from claude_agent.agent import CONVERSATION_HISTORY, MAX_TOOL_ITERATIONS

    CONVERSATION_HISTORY.clear()
    phone = "+972542159121"

    with (
        patch("claude_agent.agent.AsyncClient") as mock_client_class,
        patch("claude_agent.agent.notion.list_tasks", new=AsyncMock(return_value="x")),
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        # Always respond with tool_use → forces loop exhaustion.
        mock_client.messages.create = AsyncMock(
            return_value=_response(
                "tool_use",
                [_tool_use_block("tu", "notion_list_tasks", {})],
            )
        )

        reply = await run(phone, "loop forever")
        assert reply == HEBREW_ERROR
        assert mock_client.messages.create.await_count == MAX_TOOL_ITERATIONS
