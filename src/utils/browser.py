"""Browser utility for Selenium WebDriver management."""

import logging
from contextlib import contextmanager
from typing import Generator, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver
from webdriver_manager.chrome import ChromeDriverManager

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Default timeouts (in seconds)
DEFAULT_IMPLICIT_WAIT = 10
DEFAULT_PAGE_LOAD_TIMEOUT = 30


def create_chrome_options(headless: bool = True) -> ChromeOptions:
    """
    Create Chrome options for the WebDriver.

    Args:
        headless: Whether to run Chrome in headless mode

    Returns:
        Configured ChromeOptions instance
    """
    options = ChromeOptions()

    if headless:
        options.add_argument("--headless=new")

    # Common options for stability
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    # Reduce detection as automation
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Set a realistic user agent
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    return options


def create_browser(
    headless: Optional[bool] = None,
    implicit_wait: int = DEFAULT_IMPLICIT_WAIT,
    page_load_timeout: int = DEFAULT_PAGE_LOAD_TIMEOUT,
) -> WebDriver:
    """
    Create a new Chrome WebDriver instance.

    Args:
        headless: Whether to run headless (defaults to not debug mode)
        implicit_wait: Implicit wait timeout in seconds
        page_load_timeout: Page load timeout in seconds

    Returns:
        Configured WebDriver instance
    """
    if headless is None:
        headless = not settings.debug

    options = create_chrome_options(headless=headless)
    service = ChromeService(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(implicit_wait)
    driver.set_page_load_timeout(page_load_timeout)

    # Execute script to mask webdriver property
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        },
    )

    logger.info(f"Created Chrome browser (headless={headless})")
    return driver


def close_browser(driver: WebDriver) -> None:
    """
    Safely close a WebDriver instance.

    Args:
        driver: The WebDriver to close
    """
    try:
        driver.quit()
        logger.info("Browser closed")
    except Exception as e:
        logger.warning(f"Error closing browser: {e}")


@contextmanager
def browser_session(
    headless: Optional[bool] = None,
    implicit_wait: int = DEFAULT_IMPLICIT_WAIT,
    page_load_timeout: int = DEFAULT_PAGE_LOAD_TIMEOUT,
) -> Generator[WebDriver, None, None]:
    """
    Context manager for browser sessions.

    Ensures the browser is properly closed even if an exception occurs.

    Args:
        headless: Whether to run headless (defaults to not debug mode)
        implicit_wait: Implicit wait timeout in seconds
        page_load_timeout: Page load timeout in seconds

    Yields:
        Configured WebDriver instance

    Example:
        with browser_session() as browser:
            browser.get("https://example.com")
            # ... do work ...
        # Browser is automatically closed
    """
    driver = create_browser(
        headless=headless,
        implicit_wait=implicit_wait,
        page_load_timeout=page_load_timeout,
    )
    try:
        yield driver
    finally:
        close_browser(driver)
