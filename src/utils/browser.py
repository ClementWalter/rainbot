"""Browser utility for Playwright management with stealth anti-detection.

This module provides Playwright browser instances with stealth capabilities
to bypass bot detection systems like LiveIdentity.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright_stealth import Stealth

from src.config.settings import settings

logger = logging.getLogger(__name__)

# Default timeouts (in milliseconds for Playwright)
DEFAULT_TIMEOUT = 30000  # 30 seconds
DEFAULT_NAVIGATION_TIMEOUT = 60000  # 60 seconds


async def create_browser_context(
    playwright: Playwright,
    headless: Optional[bool] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[Browser, BrowserContext]:
    """
    Create a new Firefox browser with stealth context.

    Args:
        playwright: Playwright instance
        headless: Whether to run headless (defaults to not debug mode)
        timeout: Default timeout in milliseconds

    Returns:
        Tuple of (Browser, BrowserContext)
    """
    if headless is None:
        headless = not settings.debug

    # Launch Firefox (better fingerprint evasion than Chrome)
    browser = await playwright.firefox.launch(
        headless=headless,
        firefox_user_prefs={
            # Disable telemetry
            "toolkit.telemetry.enabled": False,
            "toolkit.telemetry.unified": False,
            # Disable safe browsing (can leak info)
            "browser.safebrowsing.enabled": False,
            # Use French locale
            "intl.accept_languages": "fr-FR, fr, en-US, en",
        },
    )

    # Create context with realistic settings
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="fr-FR",
        timezone_id="Europe/Paris",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) " "Gecko/20100101 Firefox/134.0"
        ),
        # Accept French and English
        extra_http_headers={
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )

    context.set_default_timeout(timeout)
    context.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT)

    logger.info(f"Created Firefox browser with stealth (headless={headless})")
    return browser, context


async def create_stealth_page(context: BrowserContext) -> Page:
    """
    Create a new page in the context.

    Args:
        context: Browser context

    Returns:
        New Page instance
    """
    page = await context.new_page()
    return page


async def close_browser(browser: Browser) -> None:
    """
    Safely close a browser instance.

    Args:
        browser: The Browser to close
    """
    try:
        await browser.close()
        logger.info("Browser closed")
    except Exception as e:
        logger.warning(f"Error closing browser: {e}")


@asynccontextmanager
async def browser_session(
    headless: Optional[bool] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> AsyncGenerator[tuple[BrowserContext, Page], None]:
    """
    Async context manager for stealth browser sessions.

    Ensures the browser is properly closed even if an exception occurs.
    Uses playwright-stealth to bypass bot detection.

    Args:
        headless: Whether to run headless (defaults to not debug mode)
        timeout: Default timeout in milliseconds

    Yields:
        Tuple of (BrowserContext, Page) - the context and initial page

    Example:
        async with browser_session() as (context, page):
            await page.goto("https://example.com")
            # ... do work ...
        # Browser is automatically closed
    """
    async with Stealth().use_async(async_playwright()) as playwright:
        browser, context = await create_browser_context(
            playwright,
            headless=headless,
            timeout=timeout,
        )
        try:
            page = await create_stealth_page(context)
            yield context, page
        finally:
            await close_browser(browser)


# Synchronous wrapper for compatibility with existing code
def run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're already in an async context, create a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class PlaywrightSession:
    """
    Wrapper class for managing a Playwright browser session.

    Provides a more object-oriented interface for browser automation.
    """

    def __init__(
        self,
        headless: Optional[bool] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.headless = headless
        self.timeout = timeout
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._stealth_context = None  # The async context manager

    async def start(self) -> Page:
        """Start the browser session and return the page."""
        stealth = Stealth()
        self._stealth_context = stealth.use_async(async_playwright())
        self._playwright = await self._stealth_context.__aenter__()
        self._browser, self._context = await create_browser_context(
            self._playwright,
            headless=self.headless,
            timeout=self.timeout,
        )
        self._page = await create_stealth_page(self._context)
        return self._page

    async def close(self) -> None:
        """Close the browser session."""
        if self._browser:
            await close_browser(self._browser)
        if self._stealth_context:
            await self._stealth_context.__aexit__(None, None, None)

    @property
    def page(self) -> Page:
        """Get the current page."""
        if self._page is None:
            raise RuntimeError("Session not started. Call start() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        """Get the browser context."""
        if self._context is None:
            raise RuntimeError("Session not started. Call start() first.")
        return self._context

    async def __aenter__(self) -> "PlaywrightSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
