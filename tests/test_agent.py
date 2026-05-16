"""Mocked unit tests for Claude agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_agent.agent import HEBREW_ERROR, run


@pytest.mark.asyncio
async def test_agent_run_single_message() -> None:
    """Test single message through Claude."""
    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="שלום, איך אני יכול לעזור?")]
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        reply = await run("+972542159121", "היי")
        assert reply == "שלום, איך אני יכול לעזור?"
        mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_agent_run_conversation_history() -> None:
    """Test that conversation history is maintained."""
    from claude_agent.agent import CONVERSATION_HISTORY

    phone = "+972542159121"
    CONVERSATION_HISTORY.clear()

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        def mock_create_response(model, max_tokens, system, messages, tools):
            assert len(messages) == 1
            assert messages[0]["role"] == "user"
            return MagicMock(content=[MagicMock(text="תשובה 1")])

        mock_client.messages.create = AsyncMock(side_effect=mock_create_response)

        reply1 = await run(phone, "שאלה 1")
        assert reply1 == "תשובה 1"
        assert len(CONVERSATION_HISTORY[phone]) == 2

        def mock_create_response2(model, max_tokens, system, messages, tools):
            assert len(messages) == 3
            assert messages[0]["role"] == "user"
            assert messages[1]["role"] == "assistant"
            assert messages[2]["role"] == "user"
            return MagicMock(content=[MagicMock(text="תשובה 2")])

        mock_client.messages.create = AsyncMock(side_effect=mock_create_response2)

        reply2 = await run(phone, "שאלה 2")
        assert reply2 == "תשובה 2"
        assert len(CONVERSATION_HISTORY[phone]) == 4


@pytest.mark.asyncio
async def test_agent_run_history_trimming() -> None:
    """Test that history is trimmed to MAX_HISTORY_TURNS."""
    from claude_agent.agent import CONVERSATION_HISTORY, MAX_HISTORY_TURNS

    phone = "+972999999999"
    CONVERSATION_HISTORY.clear()
    CONVERSATION_HISTORY[phone] = []

    for i in range(MAX_HISTORY_TURNS + 2):
        CONVERSATION_HISTORY[phone].append({"role": "user", "content": f"msg {i}"})
        CONVERSATION_HISTORY[phone].append(
            {"role": "assistant", "content": f"reply {i}"}
        )

    assert len(CONVERSATION_HISTORY[phone]) == (MAX_HISTORY_TURNS + 2) * 2

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(content=[MagicMock(text="reply")])
        )

        await run(phone, "new msg")

        max_len = MAX_HISTORY_TURNS * 2
        assert len(CONVERSATION_HISTORY[phone]) <= max_len


@pytest.mark.asyncio
async def test_agent_run_api_error() -> None:
    """Test error handling on API failure."""
    from claude_agent.agent import CONVERSATION_HISTORY

    phone = "+972111111111"
    CONVERSATION_HISTORY.clear()

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=Exception("API connection failed")
        )

        reply = await run(phone, "שאלה")
        assert reply == HEBREW_ERROR


@pytest.mark.asyncio
async def test_agent_separate_histories() -> None:
    """Test that different users have separate conversation histories."""
    from claude_agent.agent import CONVERSATION_HISTORY

    phone1 = "+972111111111"
    phone2 = "+972222222222"
    CONVERSATION_HISTORY.clear()

    with patch("claude_agent.agent.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            return_value=MagicMock(content=[MagicMock(text="reply")])
        )

        await run(phone1, "msg1")
        await run(phone2, "msg2")

        assert phone1 in CONVERSATION_HISTORY
        assert phone2 in CONVERSATION_HISTORY
        assert len(CONVERSATION_HISTORY[phone1]) == 2
        assert len(CONVERSATION_HISTORY[phone2]) == 2
