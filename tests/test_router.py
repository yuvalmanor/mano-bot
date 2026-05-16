"""Mocked unit tests for message router."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from router import HEBREW_ERROR, handle_message


@pytest.mark.asyncio
async def test_router_normal_path() -> None:
    """Test normal message routing to Claude and reply via WhatsApp."""
    with patch("router.run_claude") as mock_claude, patch(
        "router.send_message"
    ) as mock_whatsapp:
        mock_claude.return_value = "שלום!"
        mock_whatsapp.return_value = True

        await handle_message("+972542159121", "היי")

        mock_claude.assert_called_once_with("+972542159121", "היי")
        mock_whatsapp.assert_called_once_with("+972542159121", "שלום!")


@pytest.mark.asyncio
async def test_router_sends_hebrew_on_claude_error() -> None:
    """Test that router sends Hebrew error if Claude fails."""
    with patch("router.run_claude") as mock_claude, patch(
        "router.send_message"
    ) as mock_whatsapp:
        mock_claude.side_effect = Exception("Claude error")

        await handle_message("+972542159121", "היי")

        mock_whatsapp.assert_called_once_with("+972542159121", HEBREW_ERROR)


@pytest.mark.asyncio
async def test_router_sends_hebrew_on_whatsapp_error() -> None:
    """Test that router sends Hebrew error if WhatsApp send fails."""
    with patch("router.run_claude") as mock_claude, patch(
        "router.send_message"
    ) as mock_whatsapp:
        mock_claude.return_value = "תשובה"
        mock_whatsapp.side_effect = [Exception("WhatsApp send error"), None]

        await handle_message("+972542159121", "היי")

        assert mock_whatsapp.call_count == 2
        first_call = mock_whatsapp.call_args_list[0]
        assert first_call[0] == ("+972542159121", "תשובה")
        second_call = mock_whatsapp.call_args_list[1]
        assert second_call[0] == ("+972542159121", HEBREW_ERROR)


@pytest.mark.asyncio
async def test_router_handles_unhandled_exception() -> None:
    """Test that any unhandled exception still sends Hebrew error."""
    with patch("router.run_claude") as mock_claude, patch(
        "router.send_message"
    ) as mock_whatsapp:
        mock_claude.side_effect = RuntimeError("Unexpected error")

        await handle_message("+972542159121", "היי")

        mock_whatsapp.assert_called_once_with("+972542159121", HEBREW_ERROR)


@pytest.mark.asyncio
async def test_router_with_different_phones() -> None:
    """Test router handles different phone numbers correctly."""
    with patch("router.run_claude") as mock_claude, patch(
        "router.send_message"
    ) as mock_whatsapp:
        mock_claude.side_effect = lambda phone, msg: f"reply to {phone}"

        await handle_message("+972111111111", "msg1")
        await handle_message("+972222222222", "msg2")

        assert mock_claude.call_count == 2
        assert mock_whatsapp.call_count == 2
        first_call = mock_whatsapp.call_args_list[0]
        assert first_call[0][0] == "+972111111111"
        second_call = mock_whatsapp.call_args_list[1]
        assert second_call[0][0] == "+972222222222"
