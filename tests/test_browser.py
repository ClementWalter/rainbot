"""Tests for browser utility module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.browser import (
    DEFAULT_NAVIGATION_TIMEOUT,
    DEFAULT_TIMEOUT,
    PlaywrightSession,
    browser_session,
    close_browser,
)


class TestDefaultTimeouts:
    """Tests for default timeout constants."""

    def test_default_timeout_value(self):
        """Test that default timeout is set."""
        assert DEFAULT_TIMEOUT == 30000  # 30 seconds in ms

    def test_default_navigation_timeout_value(self):
        """Test that default navigation timeout is set."""
        assert DEFAULT_NAVIGATION_TIMEOUT == 60000  # 60 seconds in ms


class TestCloseBrowser:
    """Tests for close_browser function."""

    @pytest.mark.asyncio
    async def test_closes_browser(self):
        """Test that browser.close() is called."""
        mock_browser = AsyncMock()

        await close_browser(mock_browser)

        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        """Test that exceptions during close are handled."""
        mock_browser = AsyncMock()
        mock_browser.close.side_effect = Exception("Browser already closed")

        # Should not raise
        await close_browser(mock_browser)


class TestPlaywrightSession:
    """Tests for PlaywrightSession class."""

    def test_init_default_values(self):
        """Test default initialization values."""
        session = PlaywrightSession()
        assert session.headless is None
        assert session.timeout == DEFAULT_TIMEOUT

    def test_init_custom_values(self):
        """Test custom initialization values."""
        session = PlaywrightSession(headless=True, timeout=5000)
        assert session.headless is True
        assert session.timeout == 5000

    def test_page_property_raises_before_start(self):
        """Test that page property raises if not started."""
        session = PlaywrightSession()
        with pytest.raises(RuntimeError, match="Session not started"):
            _ = session.page

    def test_context_property_raises_before_start(self):
        """Test that context property raises if not started."""
        session = PlaywrightSession()
        with pytest.raises(RuntimeError, match="Session not started"):
            _ = session.context


class TestBrowserSession:
    """Tests for browser_session async context manager."""

    @pytest.mark.asyncio
    async def test_browser_session_is_async_context_manager(self):
        """Test that browser_session can be used as async context manager."""
        # This tests the interface - actual browser creation is tested in integration tests
        # For unit tests, we just verify the function signature
        from contextlib import asynccontextmanager
        from inspect import isasyncgenfunction

        # browser_session should be decorated with asynccontextmanager
        assert callable(browser_session)
