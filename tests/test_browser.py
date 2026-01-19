"""Tests for browser utility module."""

from unittest.mock import MagicMock, patch

import pytest
from selenium.webdriver.chrome.options import Options as ChromeOptions

from src.utils.browser import (
    DEFAULT_IMPLICIT_WAIT,
    DEFAULT_PAGE_LOAD_TIMEOUT,
    browser_session,
    close_browser,
    create_browser,
    create_chrome_options,
)


class TestCreateChromeOptions:
    """Tests for create_chrome_options function."""

    def test_headless_mode_enabled(self):
        """Test that headless mode is enabled when requested."""
        options = create_chrome_options(headless=True)
        assert isinstance(options, ChromeOptions)
        # Check headless argument is present
        assert any("--headless" in arg for arg in options.arguments)

    def test_headless_mode_disabled(self):
        """Test that headless mode is disabled when not requested."""
        options = create_chrome_options(headless=False)
        assert isinstance(options, ChromeOptions)
        # Check headless argument is not present
        assert not any("--headless" in arg for arg in options.arguments)

    def test_common_options_present(self):
        """Test that common stability options are present."""
        options = create_chrome_options(headless=True)
        assert "--no-sandbox" in options.arguments
        assert "--disable-dev-shm-usage" in options.arguments
        assert "--disable-gpu" in options.arguments

    def test_anti_detection_options(self):
        """Test that anti-automation-detection options are set."""
        options = create_chrome_options(headless=True)
        assert "--disable-blink-features=AutomationControlled" in options.arguments


class TestCreateBrowser:
    """Tests for create_browser function."""

    @patch("src.utils.browser.webdriver.Chrome")
    @patch("src.utils.browser.ChromeService")
    @patch("src.utils.browser.ChromeDriverManager")
    def test_creates_chrome_driver(self, mock_manager, mock_service, mock_chrome):
        """Test that Chrome driver is created with correct options."""
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        mock_manager.return_value.install.return_value = "/path/to/chromedriver"

        driver = create_browser(headless=True)

        mock_chrome.assert_called_once()
        mock_driver.implicitly_wait.assert_called_once_with(DEFAULT_IMPLICIT_WAIT)
        mock_driver.set_page_load_timeout.assert_called_once_with(DEFAULT_PAGE_LOAD_TIMEOUT)
        assert driver == mock_driver

    @patch("src.utils.browser.webdriver.Chrome")
    @patch("src.utils.browser.ChromeService")
    @patch("src.utils.browser.ChromeDriverManager")
    def test_custom_timeouts(self, mock_manager, mock_service, mock_chrome):
        """Test that custom timeouts are applied."""
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        mock_manager.return_value.install.return_value = "/path/to/chromedriver"

        create_browser(headless=True, implicit_wait=5, page_load_timeout=15)

        mock_driver.implicitly_wait.assert_called_once_with(5)
        mock_driver.set_page_load_timeout.assert_called_once_with(15)

    @patch("src.utils.browser.webdriver.Chrome")
    @patch("src.utils.browser.ChromeService")
    @patch("src.utils.browser.ChromeDriverManager")
    def test_executes_anti_detection_script(self, mock_manager, mock_service, mock_chrome):
        """Test that anti-webdriver-detection script is executed."""
        mock_driver = MagicMock()
        mock_chrome.return_value = mock_driver
        mock_manager.return_value.install.return_value = "/path/to/chromedriver"

        create_browser(headless=True)

        mock_driver.execute_cdp_cmd.assert_called_once()
        call_args = mock_driver.execute_cdp_cmd.call_args
        assert call_args[0][0] == "Page.addScriptToEvaluateOnNewDocument"


class TestCloseBrowser:
    """Tests for close_browser function."""

    def test_quits_driver(self):
        """Test that driver.quit() is called."""
        mock_driver = MagicMock()

        close_browser(mock_driver)

        mock_driver.quit.assert_called_once()

    def test_handles_exception_gracefully(self):
        """Test that exceptions during quit are handled."""
        mock_driver = MagicMock()
        mock_driver.quit.side_effect = Exception("Browser already closed")

        # Should not raise
        close_browser(mock_driver)


class TestBrowserSession:
    """Tests for browser_session context manager."""

    @patch("src.utils.browser.close_browser")
    @patch("src.utils.browser.create_browser")
    def test_yields_driver(self, mock_create, mock_close):
        """Test that context manager yields the created driver."""
        mock_driver = MagicMock()
        mock_create.return_value = mock_driver

        with browser_session(headless=True) as driver:
            assert driver == mock_driver

    @patch("src.utils.browser.close_browser")
    @patch("src.utils.browser.create_browser")
    def test_closes_browser_on_exit(self, mock_create, mock_close):
        """Test that browser is closed when exiting context."""
        mock_driver = MagicMock()
        mock_create.return_value = mock_driver

        with browser_session(headless=True):
            pass

        mock_close.assert_called_once_with(mock_driver)

    @patch("src.utils.browser.close_browser")
    @patch("src.utils.browser.create_browser")
    def test_closes_browser_on_exception(self, mock_create, mock_close):
        """Test that browser is closed even if exception occurs."""
        mock_driver = MagicMock()
        mock_create.return_value = mock_driver

        with pytest.raises(ValueError):
            with browser_session(headless=True):
                raise ValueError("Test error")

        mock_close.assert_called_once_with(mock_driver)

    @patch("src.utils.browser.close_browser")
    @patch("src.utils.browser.create_browser")
    def test_passes_options_to_create_browser(self, mock_create, mock_close):
        """Test that options are passed to create_browser."""
        mock_driver = MagicMock()
        mock_create.return_value = mock_driver

        with browser_session(headless=False, implicit_wait=5, page_load_timeout=20):
            pass

        mock_create.assert_called_once_with(
            headless=False,
            implicit_wait=5,
            page_load_timeout=20,
        )
