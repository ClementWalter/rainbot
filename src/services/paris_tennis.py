"""Paris Tennis website automation service.

This module provides automation for interacting with the Paris Tennis
booking website (tennis.paris.fr) using Playwright with stealth.
"""

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import (
    Page,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.config.settings import settings
from src.models.booking_request import BookingRequest, CourtType, normalize_time
from src.services.captcha_solver import CaptchaSolverService, get_captcha_service
from src.utils.browser import PlaywrightSession
from src.utils.timezone import now_paris

logger = logging.getLogger(__name__)


# Shim for legacy Selenium code paths (dead code but kept for compatibility)
class _SeleniumByShim:
    """Placeholder for Selenium's By class - legacy code paths."""

    XPATH = "xpath"
    CSS_SELECTOR = "css selector"


By = _SeleniumByShim()

# Default timeouts
DEFAULT_WAIT_TIMEOUT = 10
BOOKING_WAIT_TIMEOUT = 30

COURT_TYPE_KEYWORDS = {
    CourtType.INDOOR: ("indoor", "covered", "couvert", "interieur"),
    CourtType.OUTDOOR: ("outdoor", "uncovered", "decouvert", "exterieur"),
}

LOGIN_BUTTON_SELECTORS = (
    "#button_suivi_inscription",
    "button#button_suivi_inscription",
)

MON_PARIS_LINK_SELECTORS = (
    "a.parisian-account",
    "#mobileMonCompte",
    "a[href*='moncompte.paris.fr/moncompte']",
    "a[href*='moncompte.paris.fr']",
)

MON_PARIS_LOGIN_MENU_SELECTORS = ("#dropdownMenuMonParisUser",)

MON_PARIS_LOGIN_LINK_XPATHS = (
    "//a[contains(normalize-space(.), 'Se connecter à Mon Paris')]",
    "//a[contains(normalize-space(.), 'Se connecter') and contains(normalize-space(.), 'Mon Paris')]",
)

COOKIE_ACCEPT_SELECTORS = (
    "#tarteaucitronAllAllowed",
    "#tarteaucitronPersonalize2",
    "#tarteaucitronClosePanel",
    "#tarteaucitronCloseAlert",
)

PARIS_TENNIS_LOGOUT_SELECTORS = (
    "#banner-mon-compte__logout",
    "#banner-mon-compte_menu__logout",
)
CAPTCHA_SUBMIT_SELECTORS = (
    "button[type='submit']",
    "input[type='submit']",
    "button[name='submit']",
    "button[id*='captcha']",
    "input[id*='captcha']",
    ".captcha-submit",
)
CAPTCHA_SUBMIT_XPATHS = (
    ".//button[contains(translate(normalize-space(.), "
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'valider')]",
    ".//button[contains(translate(normalize-space(.), "
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirmer')]",
    ".//button[contains(translate(normalize-space(.), "
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'reserver')]",
    ".//input[@type='button' and contains(translate(@value, "
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'valider')]",
)
SEARCH_RESULTS_QUERY = "page=recherche&action=rechercher_creneau"
SEARCH_SLOTS_AJAX_PATH = "Portal.jsp?page=recherche&action=ajax_rechercher_creneau"
MIN_FACILITY_MATCH_LENGTH = 4

FRENCH_WEEKDAYS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
FRENCH_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _normalize_court_type_text(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value).strip().lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


@dataclass
class CourtSlot:
    """Represents an available court slot."""

    facility_name: str
    facility_code: str
    court_number: str
    date: datetime
    time_start: str
    time_end: str
    court_type: CourtType
    price: Optional[float] = None
    facility_address: Optional[str] = None
    equipment_id: Optional[str] = None
    court_id: Optional[str] = None
    reservation_start: Optional[datetime] = None
    reservation_end: Optional[datetime] = None
    captcha_request_id: Optional[str] = None


@dataclass
class BookingResult:
    """Result of a booking attempt."""

    success: bool
    confirmation_id: Optional[str] = None
    error_message: Optional[str] = None
    slot: Optional[CourtSlot] = None


class ParisTennisService:
    """
    Service for automating Paris Tennis website interactions.

    Provides methods for:
    - User login
    - Searching for available courts
    - Completing the booking process
    """

    def __init__(
        self,
        page: Optional[Page] = None,
        captcha_solver: Optional[CaptchaSolverService] = None,
    ):
        """
        Initialize the Paris Tennis service.

        Args:
            page: Optional Playwright Page instance. If not provided,
                   a new browser session will be created for each operation.
            captcha_solver: Optional CAPTCHA solver service. If not provided,
                           uses the global instance.

        """
        self._page = page
        self._captcha_solver = captcha_solver
        self._logged_in = False
        self._captcha_solve_failed = False  # Track if captcha solving has failed
        self.base_url = settings.paris_tennis.base_url
        self.login_url = settings.paris_tennis.login_url
        self.search_url = settings.paris_tennis.search_url

    @property
    def captcha_solver(self) -> CaptchaSolverService:
        """Get the CAPTCHA solver service."""
        if self._captcha_solver is None:
            self._captcha_solver = get_captcha_service()
        return self._captcha_solver

    @property
    def page(self) -> Page:
        """Get the Playwright Page instance."""
        if self._page is None:
            raise RuntimeError("No Page available. Use a browser session.")
        return self._page

    # Compatibility alias
    @property
    def driver(self) -> Page:
        """Alias for page (backward compatibility)."""
        return self.page

    async def login(self, email: str, password: str) -> bool:
        """
        Log into the Paris Tennis website.

        Args:
            email: Paris Tennis account email
            password: Paris Tennis account password

        Returns:
            True if login successful, False otherwise

        """
        try:
            logger.info(f"Attempting login for {email}")
            await self.page.goto(self.login_url)

            # Accept cookie banner if present
            await self._accept_cookie_banner()

            # Click login entry point if we're on the public landing page
            await self._click_login_entrypoint()

            # If we are already logged in, short-circuit
            if await self._is_logged_in():
                self._logged_in = True
                logger.info(f"Login already active for {email}")
                return True

            # Wait for and fill email field on the Mon Paris SSO form
            await self._ensure_login_form()
            await self.page.fill("#username", email)

            # Fill password field
            await self.page.fill("#password", password)

            # Accept cookie banner if present on the SSO page
            await self._accept_cookie_banner()

            # Click login button
            await self.page.click("button[type='submit'], input[type='submit']")

            # Wait for successful login (check for user menu or redirect)
            await asyncio.sleep(2)  # Brief wait for page transition

            # Solve CAPTCHA on the login flow if present, then resubmit.
            if await self._solve_captcha_if_present():
                await self._submit_login_form_if_present()
                await asyncio.sleep(1)

            # Check if login was successful by looking for logout link or user info
            if await self._is_logged_in():
                self._logged_in = True
                logger.info(f"Login successful for {email}")
                return True
            else:
                logger.warning(f"Login failed for {email}")
                return False

        except PlaywrightTimeoutError:
            logger.error("Login page elements not found - timeout")
            return False
        except PlaywrightError as e:
            logger.error(f"Playwright error during login: {e}")
            return False

    async def _is_logged_in(self) -> bool:
        """Check if currently logged in."""
        try:

            async def is_visible(selector: str) -> bool:
                """Check if selector is visible with short timeout."""
                try:
                    locator = self.page.locator(selector)
                    return await locator.first.is_visible(timeout=500)
                except PlaywrightError:
                    return False

            # Prefer explicit connected/disconnected nav state when available.
            if await is_visible(".navbar-collapse.connected"):
                return True
            if await is_visible(".navbar-collapse.disconnected"):
                return False

            # Visible login button indicates logged-out state on landing pages.
            if await is_visible("#button_suivi_inscription"):
                return False

            # Fallback to other indicators when nav state is unavailable.
            indicators = [
                ".user-menu",
                ".logout",
                ".banner-mon-compte__connected-avatar",
                "#banner-mon-compte__logout",
                "#banner-mon-compte_menu__logout",
                "a:has-text('Déconnexion')",
                "a:has-text('Mon compte')",
            ]
            for selector in indicators:
                if await is_visible(selector):
                    return True
            return False
        except PlaywrightError:
            return False

    async def _accept_cookie_banner(self) -> None:
        """Dismiss cookie banners if present."""
        for selector in COOKIE_ACCEPT_SELECTORS:
            try:
                locator = self.page.locator(selector)
                if await locator.first.is_visible(timeout=500):
                    await locator.first.click()
                    return
            except PlaywrightError:
                continue  # nosec B112 - intentional retry loop
            except Exception:
                continue  # nosec B112 - intentional retry loop

    async def _click_login_entrypoint(self) -> bool:
        """Click the login entry point on the public landing page if present."""
        for selector in LOGIN_BUTTON_SELECTORS:
            try:
                locator = self.page.locator(selector)
                if await locator.first.is_visible(timeout=2000):
                    await locator.first.click()
                    return True
            except PlaywrightTimeoutError:
                continue
            except PlaywrightError:
                continue

        # Fallback: match French login button text
        try:
            button = self.page.locator(
                "button:has-text('Je me connecte'), button:has-text('Se connecter')"
            )
            if await button.first.is_visible(timeout=1000):
                await button.first.click()
                return True
        except PlaywrightError:
            pass

        if await self._navigate_to_mon_paris():
            return True

        return False

    async def _navigate_to_mon_paris(self) -> bool:
        """Navigate to the Mon Paris login entrypoint if visible on the page."""
        for selector in MON_PARIS_LINK_SELECTORS:
            try:
                locator = self.page.locator(selector)
                if not await locator.first.is_visible(timeout=1000):
                    continue

                href = await locator.first.get_attribute("href") or ""
                if href:
                    await self.page.goto(href)
                    return True

                # Click may open a new tab
                async with self.page.context.expect_page(timeout=5000) as new_page_info:
                    await locator.first.click()
                new_page = await new_page_info.value
                # Switch to new page if opened
                self._page = new_page
                return True
            except PlaywrightError:
                continue
        return False

    async def _open_mon_paris_login(self) -> bool:
        """Click through the Mon Paris login dropdown to reach the SSO form."""
        current_url = self.page.url or ""
        if "moncompte.paris.fr" not in current_url:
            return False

        await self._accept_cookie_banner()

        for selector in MON_PARIS_LOGIN_MENU_SELECTORS:
            try:
                locator = self.page.locator(selector)
                if await locator.first.is_visible(timeout=2000):
                    await locator.first.click()
                    break
            except PlaywrightError:
                continue

        # Look for login link
        login_link = self.page.locator("a:has-text('Se connecter à Mon Paris')")
        try:
            if await login_link.first.is_visible(timeout=2000):
                await login_link.first.click()
                return True
        except PlaywrightError:
            pass

        return False

    async def _ensure_login_form(self) -> None:
        """Ensure the Mon Paris login form is visible."""
        try:
            await self.page.wait_for_selector("#username", timeout=DEFAULT_WAIT_TIMEOUT * 1000)
        except PlaywrightTimeoutError:
            if await self._open_mon_paris_login():
                await self.page.wait_for_selector("#username", timeout=DEFAULT_WAIT_TIMEOUT * 1000)
            else:
                raise

    async def _submit_login_form_if_present(self) -> bool:
        """Submit the login form if it's still present after CAPTCHA solving."""
        try:
            password_field = self.page.locator("#password")
            if await password_field.first.is_visible(timeout=1000):
                # Try to submit the form
                await self.page.evaluate("""
                    const passwordField = document.getElementById('password');
                    if (passwordField) {
                        const form = passwordField.closest('form');
                        if (form) {
                            form.submit();
                            return true;
                        }
                    }
                    return false;
                """)
                return True
        except PlaywrightError:
            pass

        try:
            submit_button = self.page.locator("button[type='submit'], input[type='submit']")
            if await submit_button.first.is_visible(timeout=1000):
                await submit_button.first.click()
                return True
        except PlaywrightError:
            return False
        return False

    async def check_availability_quick(
        self,
        request: BookingRequest,
        target_date: Optional[datetime] = None,
    ) -> tuple[bool, int]:
        """
        Quick availability check WITHOUT login or CAPTCHA solving.

        This method checks for available slots without requiring authentication,
        allowing us to skip login (and CAPTCHA) when no slots are available.

        Args:
            request: BookingRequest with user preferences
            target_date: Specific date to search. If None, searches next
                        occurrence of request.day_of_week

        Returns:
            (has_slots, slot_count) - (True, N) if N slots found
                                      (True, 0) if check failed (fail-open)
                                      (False, 0) if definitely no slots

        """
        if target_date is None:
            target_date = self._get_next_booking_date(request.day_of_week.value)

        try:
            logger.info(f"Quick availability check for {target_date.strftime('%Y-%m-%d')}")

            when_value = target_date.strftime("%d/%m/%Y")
            hour_range = self._format_hour_range(request.time_start, request.time_end)
            sel_in_out = self._get_indoor_outdoor_values(request.court_type)

            await self.page.goto(self.search_url)
            await self._accept_cookie_banner()

            facility_names = await self._resolve_facility_preferences(request)
            await self._ensure_search_results_page(
                target_date=target_date,
                facility_names=facility_names if facility_names else None,
                hour_range=hour_range,
                sel_in_out=sel_in_out,
            )

            if not facility_names:
                # Can't determine facilities, fail open
                logger.debug("No facility names resolved, failing open")
                return True, 0

            # Check first facility only (quick check)
            html = await self._fetch_availability_html_no_captcha(
                hour_range=hour_range,
                when_value=when_value,
                facility_name=facility_names[0],
                sel_in_out=sel_in_out,
                sel_coating=[],
            )

            if html is None:
                # Failed or CAPTCHA - fail open, let normal flow handle it
                logger.debug("AJAX fetch returned None, failing open")
                return True, 0

            # Parse and filter slots
            slots = self._parse_available_slots_html(
                html=html,
                facility_name=facility_names[0],
                target_date=target_date,
                request=request,
                captcha_request_id=None,
            )

            logger.info(f"Quick check: {len(slots)} slots for {facility_names[0]}")

            # If first facility has slots, definitely has availability
            if len(slots) > 0:
                return True, len(slots)

            # If first facility has no slots but there are other facilities,
            # fail open because we didn't check all facilities
            if len(facility_names) > 1:
                logger.info(
                    f"First facility ({facility_names[0]}) has no slots, "
                    f"but {len(facility_names) - 1} other facilities not checked - failing open"
                )
                return True, 0

            # Only one facility and it has no slots - definitively no availability
            return False, 0

        except Exception as e:
            logger.warning(f"Quick availability check failed: {e}")
            return True, 0  # Fail open

    async def _fetch_availability_html_no_captcha(
        self,
        hour_range: str,
        when_value: str,
        facility_name: str,
        sel_in_out: list[str],
        sel_coating: list[str],
    ) -> Optional[str]:
        """
        Fetch availability HTML WITHOUT CAPTCHA solving.

        Returns None if CAPTCHA encountered (caller should fail-open).
        This is used for quick availability checks before login.
        """
        try:
            ajax_url = urljoin(self.search_url, SEARCH_SLOTS_AJAX_PATH)
            li_token, li_token_code = await self._ensure_valid_li_antibot_tokens()

            response = await self.page.evaluate(
                """async ([hourRange, whenValue, facilityName, selInOut, selCoating,
                          liToken, liTokenCode, ajaxUrl]) => {
                selInOut = selInOut || [];
                selCoating = selCoating || [];
                const params = new URLSearchParams();
                params.append("hourRange", hourRange);
                params.append("when", whenValue);
                params.append("selWhereTennisName", facilityName);
                selInOut.forEach((value) => params.append("selInOut", value));
                selCoating.forEach((value) => params.append("selCoating", value));
                if (liToken) {
                    params.append("li-antibot-token", liToken);
                }
                if (liTokenCode) {
                    params.append("li-antibot-token-code", liTokenCode);
                }

                try {
                    const response = await fetch(ajaxUrl, {
                        method: "POST",
                        headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
                        body: params.toString(),
                    });
                    const text = await response.text();
                    return { ok: true, text };
                } catch (error) {
                    return { ok: false, error: String(error) };
                }
                }""",
                [
                    hour_range,
                    when_value,
                    facility_name,
                    sel_in_out,
                    sel_coating,
                    li_token or "",
                    li_token_code or "",
                    ajax_url,
                ],
            )

            if not response or not response.get("ok"):
                logger.debug("Failed to fetch availability for %s: %s", facility_name, response)
                return None

            html = response.get("text")
            if self._looks_like_captcha_html(html):
                # Don't solve - just report we can't check
                logger.debug("CAPTCHA encountered during quick check, failing open")
                return None

            return html
        except PlaywrightError as e:
            logger.debug("Availability fetch failed for %s: %s", facility_name, e)
            return None

    async def search_available_courts(
        self,
        request: BookingRequest,
        target_date: Optional[datetime] = None,
    ) -> list[CourtSlot]:
        """
        Search for available courts matching the booking request.

        Args:
            request: BookingRequest with user preferences
            target_date: Specific date to search. If None, searches next
                        occurrence of request.day_of_week

        Returns:
            List of available CourtSlot objects

        """
        if target_date is None:
            target_date = self._get_next_booking_date(request.day_of_week.value)

        available_slots: list[CourtSlot] = []
        # Reset captcha failure flag for new search
        self._captcha_solve_failed = False

        try:
            logger.info(f"Searching courts for {target_date.strftime('%Y-%m-%d')}")

            when_value = target_date.strftime("%d/%m/%Y")
            hour_range = self._format_hour_range(request.time_start, request.time_end)
            sel_in_out = self._get_indoor_outdoor_values(request.court_type)

            # Navigate to search page and load results context
            await self.page.goto(self.search_url)
            await self._accept_cookie_banner()

            facility_names = await self._resolve_facility_preferences(request)
            captcha_request_id = await self._ensure_search_results_page(
                target_date=target_date,
                facility_names=facility_names if facility_names else None,
                hour_range=hour_range,
                sel_in_out=sel_in_out,
            )

            sel_coating = self._get_surface_values()
            if not facility_names:
                facility_names = await self._resolve_facility_preferences(request)

            if not facility_names:
                logger.warning("No facility preferences resolved; falling back to DOM parsing")
                available_slots = await self._parse_all_results(target_date, request)
                available_slots = self._filter_slots_by_facility_preferences(
                    available_slots, request
                )
                available_slots = self._sort_available_slots(available_slots, request)
                logger.info(f"Found {len(available_slots)} available slots (DOM fallback)")
                return available_slots

            consecutive_failures = 0
            max_consecutive_failures = 3
            for facility_name in facility_names:
                html, captcha_request_id = await self._fetch_availability_html(
                    hour_range=hour_range,
                    when_value=when_value,
                    facility_name=facility_name,
                    sel_in_out=sel_in_out,
                    sel_coating=sel_coating,
                    captcha_request_id=captcha_request_id,
                )
                if not html:
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.warning(
                            "Too many consecutive AJAX failures (%d); "
                            "falling back to DOM parsing",
                            consecutive_failures,
                        )
                        break
                    continue
                consecutive_failures = 0  # Reset on success
                slots = self._parse_available_slots_html(
                    html=html,
                    facility_name=facility_name,
                    target_date=target_date,
                    request=request,
                    captcha_request_id=captcha_request_id,
                )
                available_slots.extend(slots)

            available_slots = self._filter_slots_by_facility_preferences(available_slots, request)

            if not available_slots:
                logger.info(
                    "AJAX availability search returned no slots; falling back to DOM parsing"
                )
                available_slots = await self._parse_all_results(target_date, request)
                available_slots = self._filter_slots_by_facility_preferences(
                    available_slots, request
                )

            available_slots = self._sort_available_slots(available_slots, request)

            logger.info(f"Found {len(available_slots)} available slots")
            return available_slots

        except PlaywrightTimeoutError:
            logger.error("Search page timeout")
            return []
        except PlaywrightError as e:
            logger.error(f"Playwright error during search: {e}")
            return []

    def _get_next_booking_date(self, day_of_week: int) -> datetime:
        """Get the next date for the given day of week in Paris timezone."""
        today = now_paris()
        days_ahead = day_of_week - today.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    async def _ensure_search_results_page(
        self,
        target_date: Optional[datetime] = None,
        facility_names: Optional[list[str]] = None,
        hour_range: Optional[str] = None,
        sel_in_out: Optional[list[str]] = None,
    ) -> Optional[str]:
        """Ensure the search results page is loaded and return captcha request id if available."""
        try:
            current_url = self.page.url or ""
            already_results = SEARCH_RESULTS_QUERY in current_url

            if not already_results and "page=recherche" not in current_url:
                await self.page.goto(self.search_url)
                await self._accept_cookie_banner()

            await self._configure_search_form(
                target_date=target_date,
                facility_names=facility_names,
                hour_range=hour_range,
                sel_in_out=sel_in_out,
            )

            if already_results and not any([target_date, facility_names, hour_range, sel_in_out]):
                # Note: Captcha is only on reservation page, not search page
                return await self._get_captcha_request_id()

            if await self._submit_search_form_if_present():
                try:
                    await self.page.wait_for_url(f"**{SEARCH_RESULTS_QUERY}**", timeout=10000)
                except PlaywrightTimeoutError:
                    pass
                # Note: Captcha is only on reservation page, not search page
                await asyncio.sleep(1)
                return await self._get_captcha_request_id()

            # Click the search button to enter results context (fallback)
            search_button = self.page.locator("#rechercher")
            await search_button.click()
            try:
                await self.page.wait_for_url(f"**{SEARCH_RESULTS_QUERY}**", timeout=10000)
            except PlaywrightTimeoutError:
                pass
            # Note: Captcha is only on reservation page, not search page
            await asyncio.sleep(1)
            return await self._get_captcha_request_id()
        except (PlaywrightTimeoutError, PlaywrightError):
            return None

    async def _solve_captcha_if_present(self) -> bool:
        """Solve CAPTCHA on the current page if detected."""
        try:
            if not await self._check_for_captcha():
                return False
        except PlaywrightError as e:
            logger.debug("CAPTCHA check failed: %s", e)
            return False

        if not (self._captcha_solver or settings.captcha.api_key):
            logger.warning("CAPTCHA detected but solver API key is not configured")
            return False

        logger.info("CAPTCHA detected - attempting to solve")
        try:
            captcha_result = await self.captcha_solver.solve_captcha_from_page_async(
                self.page, max_retries=3
            )
        except ValueError as e:
            logger.error("CAPTCHA solver not configured: %s", e)
            return False

        if not captcha_result.success:
            logger.error("CAPTCHA solving failed: %s", captcha_result.error_message)
            return False
        if not captcha_result.token and (
            "no captcha detected" in (captcha_result.error_message or "").lower()
        ):
            logger.error("CAPTCHA detected but solver did not detect a CAPTCHA")
            return False

        # Wait for li-antibot-token-code to be populated by LiveIdentity JS
        logger.debug("Waiting for li-antibot-token-code to be populated...")
        for _ in range(10):  # Wait up to 5 seconds
            await asyncio.sleep(0.5)
            token, code = await self._read_li_antibot_tokens()
            if token and code:
                logger.info(f"Both token and code populated (code length: {len(code)})")
                break
        else:
            logger.warning("li-antibot-token-code not populated after 5 seconds, proceeding anyway")

        await self._submit_captcha_form_if_present()
        return True

    async def _submit_search_form_if_present(self) -> bool:
        """Submit the hidden search form to reach the results context."""
        try:
            return bool(await self.page.evaluate("""
                    const button = document.getElementById('rechercher');
                    if (button) {
                        button.click();
                        return true;
                    }
                    const form = document.getElementById('search_form');
                    if (!form) {
                        return false;
                    }
                    const event = new Event('submit', { bubbles: true, cancelable: true });
                    const proceed = form.dispatchEvent(event);
                    if (proceed) {
                        form.submit();
                    }
                    return true;
                    """))
        except PlaywrightError:
            return False

    def _format_french_date_label(self, target_date: datetime) -> str:
        """Format a date value as the French label used by the search input."""
        date_value = target_date.date()
        weekday = FRENCH_WEEKDAYS[date_value.weekday()]
        month = FRENCH_MONTHS[date_value.month - 1]
        return f"{weekday} {date_value.day} {month} {date_value.year}"

    async def _configure_search_form(
        self,
        target_date: Optional[datetime],
        facility_names: Optional[list[str]],
        hour_range: Optional[str],
        sel_in_out: Optional[list[str]],
    ) -> None:
        """Update search form values to match the desired search parameters."""
        if not any([target_date, facility_names, hour_range, sel_in_out]):
            return

        when_value = target_date.strftime("%d/%m/%Y") if target_date else ""
        when_label = self._format_french_date_label(target_date) if target_date else ""
        facility_names = [name for name in (facility_names or []) if name]
        sel_in_out = [value for value in (sel_in_out or []) if value]
        hour_range = hour_range or ""

        try:
            await self.page.evaluate(
                """([whenValue, whenLabel, hourRange, facilityNames, selInOut]) => {
                facilityNames = facilityNames || [];
                selInOut = selInOut || [];

                const form = document.getElementById('search_form');
                if (!form) {
                    return false;
                }

                const whenInput = form.querySelector("input[name='when']");
                if (whenInput && whenValue) {
                    whenInput.value = whenValue;
                    whenInput.dispatchEvent(new Event('input', { bubbles: true }));
                    whenInput.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const visibleWhen = document.getElementById('when');
                if (visibleWhen && (whenLabel || whenValue)) {
                    visibleWhen.value = whenLabel || whenValue;
                    visibleWhen.dispatchEvent(new Event('input', { bubbles: true }));
                    visibleWhen.dispatchEvent(new Event('change', { bubbles: true }));
                }

                const hourInput = form.querySelector("input[name='hourRange']");
                if (hourInput && hourRange) {
                    hourInput.value = hourRange;
                    hourInput.dispatchEvent(new Event('input', { bubbles: true }));
                    hourInput.dispatchEvent(new Event('change', { bubbles: true }));
                }

                if (facilityNames.length) {
                    const whereInput = document.getElementById('where');
                    if (whereInput) {
                        whereInput.value = facilityNames.join(', ');
                        whereInput.dispatchEvent(new Event('input', { bubbles: true }));
                        whereInput.dispatchEvent(new Event('change', { bubbles: true }));
                    }

                    form.querySelectorAll("input[name='selWhereTennisName']").forEach((el) => el.remove());
                    const whereSelect = form.querySelector("select[name='selWhereTennisName']");
                    if (whereSelect) {
                        while (whereSelect.options.length) {
                            whereSelect.remove(0);
                        }
                        facilityNames.forEach((name) => {
                            const option = document.createElement('option');
                            option.value = name;
                            option.text = name;
                            option.selected = true;
                            whereSelect.appendChild(option);
                        });
                    } else {
                        facilityNames.forEach((name) => {
                            const input = document.createElement('input');
                            input.type = 'hidden';
                            input.name = 'selWhereTennisName';
                            input.value = name;
                            form.appendChild(input);
                        });
                    }
                }

                if (selInOut.length) {
                    const desired = new Set(selInOut);
                    form.querySelectorAll("input[name='selInOut']").forEach((input) => {
                        input.checked = desired.has(input.value);
                    });
                }

                return true;
                }""",
                [when_value, when_label, hour_range, facility_names, sel_in_out],
            )
        except PlaywrightError:
            return

    async def _get_captcha_request_id(self) -> Optional[str]:
        """Extract captchaRequestId from the results page if present."""
        selectors = (
            "#captchaRequestId",
            "input[name='captchaRequestId']",
            "input[name='captcha_request_id']",
            "[data-captcha-request-id]",
            "[data-captcharequestid]",
        )
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() == 0:
                    continue
                for attr in ("value", "data-captcha-request-id", "data-captcharequestid"):
                    value = await locator.first.get_attribute(attr)
                    if value and value.strip():
                        return value.strip()
            except PlaywrightError:
                continue

        try:
            value = await self.page.evaluate("""
                const keys = ['captchaRequestId', 'captcha_request_id', 'captchaRequestID'];
                for (const key of keys) {
                    const candidate = window[key];
                    if (typeof candidate === 'string' && candidate.trim()) {
                        return candidate;
                    }
                }
                return null;
                """)
        except PlaywrightError:
            value = None

        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned

        page_source = await self.page.content() or ""
        if page_source:
            patterns = [
                r"captchaRequestId\s*[:=]\s*['\"]([^'\"]+)['\"]",
                r"captcha_request_id\s*[:=]\s*['\"]([^'\"]+)['\"]",
                r"data-captcha-request-id=['\"]([^'\"]+)['\"]",
                r"data-captcharequestid=['\"]([^'\"]+)['\"]",
                r"name=['\"]captchaRequestId['\"][^>]*value=['\"]([^'\"]+)['\"]",
                r"name=['\"]captcha_request_id['\"][^>]*value=['\"]([^'\"]+)['\"]",
            ]
            for pattern in patterns:
                match = re.search(pattern, page_source, re.IGNORECASE)
                if not match:
                    continue
                candidate = match.group(1).strip()
                if candidate:
                    return candidate

        return None

    def _extract_captcha_request_id_from_soup(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract captchaRequestId from a parsed HTML fragment."""
        if soup is None:
            return None

        selectors = (
            "#captchaRequestId",
            "input[name='captchaRequestId']",
            "input[name='captcha_request_id']",
            "[data-captcha-request-id]",
            "[data-captcharequestid]",
        )
        for selector in selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            for attr in ("value", "data-captcha-request-id", "data-captcharequestid"):
                value = element.get(attr)
                if value:
                    return str(value).strip()

        html = str(soup)
        if not html:
            return None

        patterns = [
            r"captchaRequestId\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"captcha_request_id\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"data-captcha-request-id=['\"]([^'\"]+)['\"]",
            r"data-captcharequestid=['\"]([^'\"]+)['\"]",
            r"name=['\"]captchaRequestId['\"][^>]*value=['\"]([^'\"]+)['\"]",
            r"name=['\"]captcha_request_id['\"][^>]*value=['\"]([^'\"]+)['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip()
            if candidate:
                return candidate

        return None

    async def _read_li_antibot_tokens(self) -> tuple[Optional[str], Optional[str]]:
        """Read LiveIdentity token values from page inputs."""
        try:
            values = await self.page.evaluate("""
                const tokenInput = document.getElementById('li-antibot-token')
                    || document.querySelector("input[name='li-antibot-token']");
                const codeInput = document.getElementById('li-antibot-token-code')
                    || document.querySelector("input[name='li-antibot-token-code']");
                const token = tokenInput ? tokenInput.value : "";
                const code = codeInput ? codeInput.value : "";
                return [token, code];
                """)
        except PlaywrightError:
            return None, None

        if not isinstance(values, (list, tuple)) or len(values) < 2:
            return None, None

        token = values[0] if values[0] is not None else ""
        code = values[1] if values[1] is not None else ""
        if not isinstance(token, str):
            token = str(token)
        if not isinstance(code, str):
            code = str(code)
        token = token.strip()
        code = code.strip()
        return (token or None, code or None)

    def _is_li_antibot_token_valid(self, token: Optional[str]) -> bool:
        """Return True if the LiveIdentity token looks usable."""
        if not token or not isinstance(token, str):
            return False
        lowered = token.strip().lower()
        if not lowered:
            return False
        invalid_markers = ("blacklist", "invalid", "error", "erreur")
        if any(marker in lowered for marker in invalid_markers):
            return False
        return lowered != "invalid response."

    async def _ensure_valid_li_antibot_tokens(self) -> tuple[Optional[str], Optional[str]]:
        """Refresh LiveIdentity tokens when they are present but invalid."""
        # Just read tokens - captcha solving is only needed on reservation page
        token, code = await self._read_li_antibot_tokens()
        if token and not self._is_li_antibot_token_valid(token):
            # Token is invalid but we don't solve captcha during search
            # The AJAX will fail and we'll fall back to DOM parsing
            return None, None
        if not token:
            return None, None
        return token, code

    async def _resolve_facility_preferences(self, request: BookingRequest) -> list[str]:
        """Resolve requested facility preferences against visible tennis names."""
        available = await self._get_available_facility_names()
        if not request.facility_preferences:
            return available

        if not available:
            return [pref for pref in request.facility_preferences if pref]

        normalized_available = [
            (self._normalize_facility_code(name), name) for name in available if name
        ]
        normalized_lookup = {normalized: name for normalized, name in normalized_available}
        resolved: list[str] = []
        for pref in request.facility_preferences:
            if not pref:
                continue
            if pref in available:
                resolved.append(pref)
                continue
            normalized_pref = self._normalize_facility_code(pref)
            if normalized_pref in normalized_lookup:
                resolved.append(normalized_lookup[normalized_pref])
                continue

            matched = self._match_facility_preference(normalized_pref, normalized_available)
            if matched:
                resolved.append(matched)
            else:
                resolved.append(pref)
        return resolved

    async def _get_available_facility_names(self) -> list[str]:
        """Return tennis names visible in the results bookmark list."""
        names: list[str] = []

        try:
            marker_names = await self.page.evaluate("""
                const markers = window.mapMarkers;
                if (!markers) {
                    return [];
                }

                const nameKeys = [
                    'name',
                    'nom',
                    'label',
                    'title',
                    'libelle',
                    'tennisName',
                    'facilityName',
                    'siteName',
                ];

                const collectKeys = (value) => {
                    if (!value) {
                        return [];
                    }
                    if (value instanceof Map) {
                        return Array.from(value.keys());
                    }
                    if (typeof value === 'object') {
                        return Object.keys(value);
                    }
                    return [];
                };

                const collectNameValues = (value) => {
                    if (!value) {
                        return [];
                    }
                    if (typeof value === 'string') {
                        return [value];
                    }
                    if (Array.isArray(value)) {
                        const results = [];
                        value.forEach((item) => results.push(...collectNameValues(item)));
                        return results;
                    }
                    if (value instanceof Map) {
                        const results = [];
                        for (const item of value.values()) {
                            results.push(...collectNameValues(item));
                        }
                        return results;
                    }
                    if (typeof value === 'object') {
                        const results = [];
                        nameKeys.forEach((key) => {
                            const candidate = value[key];
                            if (typeof candidate === 'string') {
                                results.push(candidate);
                            }
                        });
                        const mapSelect = value.mapSelectTennis || value['mapSelectTennis'];
                        if (mapSelect) {
                            results.push(...collectNameValues(mapSelect));
                        }
                        const mapList = value.map || value['map'];
                        if (mapList) {
                            results.push(...collectNameValues(mapList));
                        }
                        return results;
                    }
                    return [];
                };

                const collectValueKeys = (mapLike) => {
                    if (!mapLike || typeof mapLike.values !== 'function') {
                        return [];
                    }
                    const results = [];
                    for (const value of mapLike.values()) {
                        results.push(...collectKeys(value));
                    }
                    return results;
                };

                const extractFromObject = (obj) => {
                    if (!obj || typeof obj !== 'object') {
                        return [];
                    }
                    const mapSelect = obj.mapSelectTennis || obj['mapSelectTennis'];
                    let keys = collectKeys(mapSelect);
                    if (!keys.length) {
                        const mapList = obj.map || obj['map'];
                        keys = collectKeys(mapList);
                    }
                    return keys;
                };

                if (typeof markers.get === 'function') {
                    const mapSelect = markers.get('mapSelectTennis');
                    let keys = collectKeys(mapSelect);
                    if (!keys.length) {
                        const mapList = markers.get('map');
                        keys = collectKeys(mapList);
                    }
                    const valueKeys = collectValueKeys(markers);
                    const valueNames = collectNameValues(markers);
                    if (!keys.length) {
                        keys = collectKeys(markers);
                    }
                    if (valueNames.length) {
                        return valueNames.concat(valueKeys, keys);
                    }
                    if (valueKeys.length) {
                        return valueKeys.concat(keys);
                    }
                    return keys;
                }

                const objectNames = collectNameValues(markers);
                const objectKeys = extractFromObject(markers);
                if (objectNames.length) {
                    return objectNames.concat(objectKeys);
                }
                if (objectKeys.length) {
                    return objectKeys;
                }

                return collectKeys(markers);
                """)
        except PlaywrightError:
            marker_names = []

        if isinstance(marker_names, (list, tuple)):
            names.extend(
                [name.strip() for name in marker_names if isinstance(name, str) and name.strip()]
            )

        try:
            favorites = await self.page.evaluate("window.jsFav || []")
        except PlaywrightError:
            favorites = []
        if isinstance(favorites, (list, tuple)):
            for name in favorites:
                if isinstance(name, str):
                    cleaned = name.strip()
                    if cleaned:
                        names.append(cleaned)

        try:
            elements = self.page.locator(".tennisName")
            count = await elements.count()
            for i in range(count):
                text = await elements.nth(i).text_content()
                if text and text.strip():
                    names.append(text.strip())
        except PlaywrightError:
            pass

        try:
            elements = self.page.locator("#bookmarkList .tennis-label")
            count = await elements.count()
            for i in range(count):
                text = await elements.nth(i).text_content()
                if text and text.strip():
                    names.append(text.strip())
        except PlaywrightError:
            pass

        seen: set[str] = set()
        deduped: list[str] = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                deduped.append(name)

        return deduped

    def _normalize_facility_code(self, name: str) -> str:
        """Normalize a facility name into a slug-like code."""
        normalized = _normalize_court_type_text(name)
        normalized = re.sub(r"[^a-z0-9]+", "", normalized)
        return normalized

    def _normalized_facility_preferences(self, request: BookingRequest) -> list[str]:
        """Return normalized facility preferences for matching."""
        return [
            self._normalize_facility_code(pref) for pref in request.facility_preferences if pref
        ]

    def _match_facility_preference(
        self,
        normalized_pref: str,
        normalized_available: list[tuple[str, str]],
    ) -> Optional[str]:
        """Find a unique substring match for a facility preference."""
        if not normalized_pref or len(normalized_pref) < MIN_FACILITY_MATCH_LENGTH:
            return None

        matches = []
        for normalized_name, name in normalized_available:
            if not normalized_name:
                continue
            if normalized_pref in normalized_name or normalized_name in normalized_pref:
                matches.append(name)

        if len(matches) == 1:
            return matches[0]
        return None

    def _format_hour_range(self, time_start: str, time_end: str) -> str:
        """Format hour range string for the Paris Tennis slider."""
        start_norm = normalize_time(time_start) or "08:00"
        end_norm = normalize_time(time_end) or "22:00"

        def hour_value(value: str, round_up: bool) -> int:
            try:
                hours, minutes = value.split(":")[:2]
                hour = int(hours)
                minute = int(minutes)
            except ValueError:
                return 8 if not round_up else 22
            if round_up and minute > 0:
                return min(22, hour + 1)
            return max(8, hour)

        start_hour = hour_value(start_norm, round_up=False)
        end_hour = hour_value(end_norm, round_up=True)
        end_hour = max(start_hour + 1, end_hour)
        end_hour = min(22, end_hour)
        return f"{start_hour}-{end_hour}"

    def _get_indoor_outdoor_values(self, court_type: CourtType) -> list[str]:
        """Map court type to Paris Tennis indoor/outdoor checkbox values."""
        if court_type == CourtType.INDOOR:
            return ["V"]
        if court_type == CourtType.OUTDOOR:
            return ["F"]
        return ["V", "F"]

    def _get_surface_values(self) -> list[str]:
        """Fetch available surface ids for search filtering."""
        # This method is sync and doesn't need browser access - just return empty
        # Surface values are optional for search
        return []

    async def _fetch_availability_html(
        self,
        hour_range: str,
        when_value: str,
        facility_name: str,
        sel_in_out: list[str],
        sel_coating: list[str],
        captcha_request_id: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Fetch available slots HTML and the latest captchaRequestId via AJAX."""
        try:
            ajax_url = urljoin(self.search_url, SEARCH_SLOTS_AJAX_PATH)
            current_captcha_request_id = captcha_request_id
            for attempt in range(2):
                li_token, li_token_code = await self._ensure_valid_li_antibot_tokens()
                response = await self.page.evaluate(
                    """async ([hourRange, whenValue, facilityName, selInOut, selCoating,
                              captchaRequestId, liToken, liTokenCode, ajaxUrl]) => {
                    selInOut = selInOut || [];
                    selCoating = selCoating || [];
                    const params = new URLSearchParams();
                    params.append("hourRange", hourRange);
                    params.append("when", whenValue);
                    params.append("selWhereTennisName", facilityName);
                    selInOut.forEach((value) => params.append("selInOut", value));
                    selCoating.forEach((value) => params.append("selCoating", value));
                    if (captchaRequestId) {
                        params.append("captchaRequestId", captchaRequestId);
                    }
                    if (liToken) {
                        params.append("li-antibot-token", liToken);
                    }
                    if (liTokenCode) {
                        params.append("li-antibot-token-code", liTokenCode);
                    }

                    try {
                        const response = await fetch(ajaxUrl, {
                            method: "POST",
                            headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
                            body: params.toString(),
                        });
                        const text = await response.text();
                        return { ok: true, text };
                    } catch (error) {
                        return { ok: false, error: String(error) };
                    }
                    }""",
                    [
                        hour_range,
                        when_value,
                        facility_name,
                        sel_in_out,
                        sel_coating,
                        current_captcha_request_id,
                        li_token or "",
                        li_token_code or "",
                        ajax_url,
                    ],
                )
                if not response or not response.get("ok"):
                    logger.debug("Failed to fetch availability for %s: %s", facility_name, response)
                    return None, current_captcha_request_id

                html = response.get("text")
                if attempt == 0 and self._looks_like_captcha_html(html):
                    logger.info(
                        "Availability response indicates CAPTCHA; attempting solve before retry"
                    )
                    if not await self._solve_captcha_if_present():
                        logger.warning(
                            "CAPTCHA solve failed during availability fetch for %s",
                            facility_name,
                        )
                        return None, current_captcha_request_id
                    refreshed_id = await self._get_captcha_request_id()
                    if refreshed_id:
                        current_captcha_request_id = refreshed_id
                    continue
                return html, current_captcha_request_id
            return None, current_captcha_request_id
        except PlaywrightError as e:
            logger.debug("Availability fetch failed for %s: %s", facility_name, e)
            return None, current_captcha_request_id

    def _looks_like_captcha_html(self, html: Optional[str]) -> bool:
        """Return True if the response HTML appears to be a CAPTCHA gate."""
        if not html:
            return False
        lowered = str(html).lower()
        markers = (
            "g-recaptcha",
            "recaptcha",
            "li-antibot",
            "li_antibot",
            "formcaptcha",
            "captcha-input",
            "captcha-answer",
        )
        return any(marker in lowered for marker in markers)

    def _parse_available_slots_html(
        self,
        html: str,
        facility_name: str,
        target_date: datetime,
        request: BookingRequest,
        captcha_request_id: Optional[str],
    ) -> list[CourtSlot]:
        """Parse AJAX availability HTML into CourtSlot objects."""
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        fallback_captcha_request_id = (
            self._extract_captcha_request_id_from_soup(soup) or captcha_request_id
        )
        slot_elements = self._find_slot_elements(soup)
        slots: list[CourtSlot] = []

        for element in slot_elements:
            slot = self._parse_slot_button(
                button=element,
                facility_name=facility_name,
                target_date=target_date,
                captcha_request_id=fallback_captcha_request_id,
            )
            if not slot:
                continue
            if request.is_time_in_range(slot.time_start) and self._slot_matches_request(
                slot, request
            ):
                slots.append(slot)

        return slots

    def _find_slot_elements(self, soup: BeautifulSoup) -> list:
        """Return candidate slot elements from AJAX HTML."""
        selectors = [
            "button",
            "a",
            "input",
            ".buttonAllOk",
            "[equipmentid]",
            "[data-equipment-id]",
            "[data-equipmentid]",
        ]
        elements = []
        seen_ids: set[int] = set()
        for selector in selectors:
            for element in soup.select(selector):
                element_id = id(element)
                if element_id in seen_ids:
                    continue
                seen_ids.add(element_id)
                elements.append(element)
        return elements

    def _get_slot_button_attr(self, button, *names: str) -> Optional[str]:
        """Return the first non-empty attribute value from a slot button."""
        if button is None:
            return None
        for name in names:
            value = button.get(name)
            if value:
                return str(value).strip()
        return None

    def _get_dom_element_attr(self, element, *names: str) -> Optional[str]:
        """Return the first non-empty attribute value from a Selenium element."""
        if element is None:
            return None
        for name in names:
            try:
                value = element.get_attribute(name)
            except Exception:
                value = None
            if value is None:
                continue
            if not isinstance(value, str):
                value = str(value)
            value = value.strip()
            if value:
                return value
        return None

    def _normalize_slot_param_key(self, key: str) -> Optional[str]:
        """Normalize slot parameter keys from URLs/JS snippets."""
        if not key:
            return None
        cleaned = re.sub(r"[^a-z0-9]", "", key.lower())
        mapping = {
            "equipmentid": "equipment_id",
            "courtid": "court_id",
            "datedeb": "date_deb",
            "datefin": "date_fin",
            "price": "price",
            "typeprice": "type_price",
            "indooroutdoor": "indoor_outdoor",
            "captcharequestid": "captcha_request_id",
        }
        return mapping.get(cleaned)

    def _looks_like_datetime(self, value: str) -> bool:
        """Return True if a string looks like a date/time value."""
        if not value:
            return False
        if not re.search(r"\d{1,2}:\d{2}", value):
            return False
        return bool(
            re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", value)
            or re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", value)
        )

    def _extract_positional_slot_params(self, args: list[str]) -> dict[str, str]:
        """Extract slot identifiers from positional JavaScript arguments."""
        if len(args) < 4:
            return {}
        date_indices = [i for i, arg in enumerate(args) if self._looks_like_datetime(arg)]
        if len(date_indices) < 2:
            return {}
        first, second = date_indices[-2], date_indices[-1]
        if second != first + 1 or first < 2:
            return {}
        return {
            "equipmentId": args[first - 2],
            "courtId": args[first - 1],
            "dateDeb": args[first],
            "dateFin": args[second],
        }

    def _extract_slot_params_from_text(self, value: Optional[str]) -> dict[str, str]:
        """Parse slot identifiers from URL/query strings or JS snippets."""
        if not value:
            return {}

        raw = str(value)
        params: dict[str, str] = {}

        def add_param(key: str, val: Optional[str]) -> None:
            normalized = self._normalize_slot_param_key(key)
            if not normalized:
                return
            if normalized in params:
                return
            if val is None:
                return
            cleaned = str(val).strip()
            if not cleaned:
                return
            params[normalized] = cleaned

        if "?" in raw:
            parsed = urlparse(raw)
            query = parsed.query or raw.split("?", 1)[1]
            query = query.split("#", 1)[0]
            for key, values in parse_qs(query, keep_blank_values=True).items():
                if values:
                    add_param(key, values[0])
        elif "=" in raw and "&" in raw:
            query = raw.split("#", 1)[0]
            for key, values in parse_qs(query, keep_blank_values=True).items():
                if values:
                    add_param(key, values[0])

        key_pattern = (
            r"(equipmentId|equipmentid|courtId|courtid|dateDeb|datedeb|dateFin|datefin"
            r"|price|typePrice|typeprice|indoorOutdoor|indooroutdoor"
            r"|captchaRequestId|captcharequestid)\s*[:=]\s*['\"]([^'\"]+)"
        )
        for match in re.finditer(key_pattern, raw):
            add_param(match.group(1), match.group(2))

        args = re.findall(r"['\"]([^'\"]+)['\"]", raw)
        for key, val in self._extract_positional_slot_params(args).items():
            add_param(key, val)

        return params

    def _extract_slot_params_from_sources(self, *values: Optional[str]) -> dict[str, str]:
        """Merge slot parameters from multiple attribute sources."""
        merged: dict[str, str] = {}
        for value in values:
            params = self._extract_slot_params_from_text(value)
            for key, val in params.items():
                if key not in merged:
                    merged[key] = val
        return merged

    def _parse_slot_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse slot date strings from AJAX results into datetimes."""
        if not value:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None

        formats = (
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%d-%m-%Y %H:%M",
        )
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _parse_price_value(self, value: Optional[str]) -> Optional[float]:
        """Parse a price string into a float."""
        if not value:
            return None
        cleaned = re.sub(r"[^\d,\.]", "", str(value))
        if not cleaned:
            return None
        if cleaned.count(",") == 1 and cleaned.count(".") == 0:
            cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _extract_facility_from_panel_id(self, value: Optional[str]) -> Optional[str]:
        """Extract facility name from panel IDs like collapseJesseOwens08h."""
        if not value:
            return None
        for prefix in ("collapse", "courtList", "head"):
            if value.startswith(prefix):
                trimmed = value[len(prefix) :]
                break
        else:
            return None
        trimmed = re.sub(r"\d{1,2}h\d{0,2}$", "", trimmed, flags=re.IGNORECASE)
        trimmed = trimmed.strip()
        return trimmed or None

    def _infer_facility_name_from_dom(self, element) -> Optional[str]:
        """Infer facility name from DOM ancestors when missing on slot elements."""
        xpaths = (
            "ancestor::*[starts-with(@id,'collapse')][1]",
            "ancestor::*[starts-with(@id,'courtList')][1]",
            "ancestor::*[starts-with(@id,'head')][1]",
        )
        for xpath in xpaths:
            try:
                ancestor = element.find_element(By.XPATH, xpath)
            except Exception:
                continue
            raw_id = self._get_dom_element_attr(ancestor, "id")
            facility = self._extract_facility_from_panel_id(raw_id)
            if facility:
                return facility
        return None

    def _extract_facility_address(self, button) -> Optional[str]:
        """Best-effort extraction of a facility address from an availability button."""
        if button is None:
            return None

        address_attrs = (
            "data-facility-address",
            "data-address",
            "data-adresse",
            "data-facility-adresse",
        )

        for element in [button, *list(button.parents)]:
            try:
                attrs = element.attrs
            except AttributeError:
                continue
            for attr in address_attrs:
                value = attrs.get(attr)
                if value:
                    return str(value).strip()

        container = button.find_parent(
            lambda tag: tag.name in ("div", "section", "article")
            and (
                tag.has_attr("data-facility")
                or tag.has_attr("data-facility-name")
                or any(
                    key in cls.lower()
                    for cls in tag.get("class", [])
                    for key in ("facility", "tennis", "centre", "center")
                )
            )
        )
        if not container:
            return None

        address_node = container.find(
            lambda tag: tag.name in ("div", "span", "p", "li")
            and any(
                key in cls.lower() for cls in tag.get("class", []) for key in ("address", "adresse")
            )
        )
        if address_node:
            text_value = address_node.get_text(" ", strip=True)
            if text_value:
                return text_value

        label_node = container.find(string=re.compile(r"adresse", re.IGNORECASE))
        if label_node:
            label_text = str(label_node).strip()
            cleaned = re.sub(r"adresse\s*[:\-]?\s*", "", label_text, flags=re.IGNORECASE)
            cleaned = cleaned.strip()
            if cleaned and cleaned.lower() != "adresse":
                return cleaned

            parent_text = label_node.parent.get_text(" ", strip=True)
            cleaned_parent = re.sub(
                r"adresse\s*[:\-]?\s*", "", parent_text, flags=re.IGNORECASE
            ).strip()
            if cleaned_parent and cleaned_parent.lower() != "adresse":
                return cleaned_parent

        return None

    def _parse_slot_button(
        self,
        button,
        facility_name: str,
        target_date: datetime,
        captcha_request_id: Optional[str],
    ) -> Optional[CourtSlot]:
        """Parse a buttonAllOk element into a CourtSlot."""
        equipment_id = self._get_slot_button_attr(
            button,
            "equipmentid",
            "data-equipmentid",
            "data-equipment-id",
        )
        court_id = self._get_slot_button_attr(
            button,
            "courtid",
            "data-courtid",
            "data-court-id",
        )
        date_deb = self._get_slot_button_attr(
            button,
            "datedeb",
            "data-datedeb",
            "data-date-deb",
        )
        date_fin = self._get_slot_button_attr(
            button,
            "datefin",
            "data-datefin",
            "data-date-fin",
        )
        price_value = self._get_slot_button_attr(
            button,
            "price",
            "data-price",
        )
        type_price = (
            self._get_slot_button_attr(
                button,
                "typeprice",
                "data-typeprice",
                "data-type-price",
            )
            or ""
        )
        indoor_outdoor = (
            self._get_slot_button_attr(
                button,
                "indooroutdoor",
                "data-indooroutdoor",
                "data-indoor-outdoor",
            )
            or ""
        )
        button_captcha_request_id = self._get_slot_button_attr(
            button,
            "captcharequestid",
            "data-captcharequestid",
            "data-captcha-request-id",
        )
        if button_captcha_request_id:
            captcha_request_id = button_captcha_request_id

        extra_params = self._extract_slot_params_from_sources(
            self._get_slot_button_attr(button, "href"),
            self._get_slot_button_attr(button, "onclick"),
        )
        if extra_params:
            equipment_id = equipment_id or extra_params.get("equipment_id")
            court_id = court_id or extra_params.get("court_id")
            date_deb = date_deb or extra_params.get("date_deb")
            date_fin = date_fin or extra_params.get("date_fin")
            price_value = price_value or extra_params.get("price")
            type_price = type_price or extra_params.get("type_price", "")
            indoor_outdoor = indoor_outdoor or extra_params.get("indoor_outdoor", "")
            if not button_captcha_request_id:
                captcha_request_id = captcha_request_id or extra_params.get("captcha_request_id")

        if not equipment_id or not court_id or not date_deb or not date_fin:
            return None

        reservation_start = self._parse_slot_datetime(date_deb)
        reservation_end = self._parse_slot_datetime(date_fin)

        time_start = reservation_start.strftime("%H:%M") if reservation_start else ""
        time_end = reservation_end.strftime("%H:%M") if reservation_end else ""

        court_text = ""
        court_info = button.find_parent("div", class_="tennis-court")
        if court_info:
            court_span = court_info.find("span", class_="court")
            court_text = court_span.get_text(strip=True) if court_span else ""

        court_number = self._parse_court_number(court_text)
        court_type = self._parse_court_type_from_text(
            court_text, " ".join([type_price, indoor_outdoor]).strip()
        )
        facility_address = self._extract_facility_address(button)

        price = None
        if price_value:
            try:
                price = float(price_value)
            except ValueError:
                price = None

        facility_code = self._normalize_facility_code(facility_name)

        return CourtSlot(
            facility_name=facility_name,
            facility_code=facility_code,
            court_number=court_number or "",
            date=reservation_start or target_date,
            time_start=time_start,
            time_end=time_end,
            court_type=court_type,
            price=price,
            facility_address=facility_address,
            equipment_id=equipment_id,
            court_id=court_id,
            reservation_start=reservation_start,
            reservation_end=reservation_end,
            captcha_request_id=captcha_request_id,
        )

    def _parse_court_number(self, text: str) -> str:
        """Extract court number from the court description text."""
        if not text:
            return ""
        match = re.search(r"court\s*(?:n[°oº]?\s*)?(\d+)", text, re.IGNORECASE)
        if match:
            return match.group(1)
        return text.strip()

    def _parse_court_type_from_text(self, court_text: str, price_text: str) -> CourtType:
        """Infer court type from court/price labels."""
        combined = " ".join([court_text or "", price_text or ""]).lower()
        normalized = _normalize_court_type_text(combined)
        if "decouvert" in normalized or "exterieur" in normalized:
            return CourtType.OUTDOOR
        if "couvert" in normalized:
            return CourtType.INDOOR
        return CourtType.ANY

    async def _submit_reservation_form(
        self,
        slot: CourtSlot,
        captcha_request_id: Optional[str],
        li_token: Optional[str] = None,
        li_token_code: Optional[str] = None,
    ) -> None:
        """Submit the reservation form using slot identifiers."""
        reservation_start = slot.reservation_start or slot.date
        reservation_end = slot.reservation_end or slot.date

        date_deb = reservation_start.strftime("%Y/%m/%d %H:%M:%S")
        date_fin = reservation_end.strftime("%Y/%m/%d %H:%M:%S")
        action_url = urljoin(
            self.search_url,
            "Portal.jsp?page=reservation&view=reservation_captcha",
        )

        try:
            await self.page.evaluate(
                """([equipmentId, courtId, dateDeb, dateFin, captchaRequestId, liToken, liTokenCode, actionUrl]) => {
                let form = document.getElementById("formReservation");
                if (!form) {
                    form = document.createElement("form");
                    form.id = "formReservation";
                    document.body.appendChild(form);
                }
                form.method = "post";
                form.action = actionUrl;

                const setInput = (name, value) => {
                    let input = form.querySelector(`input[name='${name}']`);
                    if (!input) {
                        input = document.createElement("input");
                        input.type = "hidden";
                        input.name = name;
                        form.appendChild(input);
                    }
                    input.value = value;
                };

                setInput("equipmentId", equipmentId);
                setInput("courtId", courtId);
                setInput("dateDeb", dateDeb);
                setInput("dateFin", dateFin);
                setInput("annulation", "false");
                if (liToken) {
                    setInput("li-antibot-token", liToken);
                    if (liTokenCode) {
                        setInput("li-antibot-token-code", liTokenCode);
                    }
                }
                if (captchaRequestId) {
                    setInput("captchaRequestId", captchaRequestId);
                }

                form.submit();
                }""",
                [
                    slot.equipment_id,
                    slot.court_id,
                    date_deb,
                    date_fin,
                    captcha_request_id,
                    li_token or "",
                    li_token_code or "",
                    action_url,
                ],
            )
        except PlaywrightError as e:
            logger.error("Failed to submit reservation form: %s", e)

    def _sort_available_slots(
        self,
        slots: list[CourtSlot],
        request: BookingRequest,
    ) -> list[CourtSlot]:
        """
        Sort available slots by facility preference order, then by earliest time.

        This ensures we respect PRD priority logic: preferred facilities first,
        and the earliest available time within each facility.
        """
        if not slots:
            return slots

        normalized_prefs = self._normalized_facility_preferences(request)
        facility_order = {pref: index for index, pref in enumerate(normalized_prefs) if pref}

        def facility_rank(slot: CourtSlot) -> int:
            slot_key_source = slot.facility_code or slot.facility_name or ""
            normalized_slot = self._normalize_facility_code(slot_key_source)
            if normalized_slot in facility_order:
                return facility_order[normalized_slot]

            for index, pref in enumerate(normalized_prefs):
                if not pref or len(pref) < MIN_FACILITY_MATCH_LENGTH:
                    continue
                if pref in normalized_slot or normalized_slot in pref:
                    return index

            return len(normalized_prefs)

        def sort_key(slot: CourtSlot) -> tuple[int, str]:
            facility_index = facility_rank(slot)
            time_key = normalize_time(slot.time_start)
            if not time_key:
                time_key = "99:99"
            return (facility_index, time_key)

        return sorted(slots, key=sort_key)

    def _slot_matches_facility_preferences(
        self,
        slot: CourtSlot,
        request: BookingRequest,
    ) -> bool:
        """Check whether a slot matches the requested facility preferences."""
        normalized_prefs = self._normalized_facility_preferences(request)
        if not normalized_prefs:
            return True

        candidates: list[str] = []
        for value in (slot.facility_code, slot.facility_name):
            if not value:
                continue
            normalized_value = self._normalize_facility_code(value)
            if normalized_value and normalized_value not in candidates:
                candidates.append(normalized_value)

        if not candidates:
            return False

        for candidate in candidates:
            if candidate in normalized_prefs:
                return True

        for candidate in candidates:
            for pref in normalized_prefs:
                if not pref or len(pref) < MIN_FACILITY_MATCH_LENGTH:
                    continue
                if pref in candidate or candidate in pref:
                    return True

        return False

    def _filter_slots_by_facility_preferences(
        self,
        slots: list[CourtSlot],
        request: BookingRequest,
    ) -> list[CourtSlot]:
        """Filter slots to those matching the requested facility preferences."""
        if not slots:
            return slots
        if not request.facility_preferences:
            return slots
        return [slot for slot in slots if self._slot_matches_facility_preferences(slot, request)]

    async def _set_time_range(self, time_start: str, time_end: str) -> None:
        """Set time range filters if available."""
        try:
            start_field = self.page.locator("#hourStart")
            if await start_field.count() > 0:
                await start_field.clear()
                await start_field.fill(time_start)

            end_field = self.page.locator("#hourEnd")
            if await end_field.count() > 0:
                await end_field.clear()
                await end_field.fill(time_end)
        except PlaywrightError:
            logger.debug("Time range fields not found, skipping")

    async def _set_court_type(self, court_type: CourtType) -> None:
        """Set court type filter if available."""
        if court_type == CourtType.ANY:
            return

        try:
            # Look for court type checkbox/radio
            type_value = "couvert" if court_type == CourtType.INDOOR else "decouvert"
            selector = f"input[value='{type_value}']"
            checkbox = self.page.locator(selector)
            if await checkbox.count() > 0:
                if not await checkbox.is_checked():
                    await checkbox.click()
        except PlaywrightError:
            logger.debug("Court type filter not found, skipping")

    async def _parse_facility_results(
        self,
        facility_code: str,
        target_date: datetime,
        request: BookingRequest,
    ) -> list[CourtSlot]:
        """Parse search results for a specific facility."""
        slots: list[CourtSlot] = []
        try:
            # Look for facility section in results
            facility_section = self.page.locator(f"[data-facility='{facility_code}']")
            if await facility_section.count() == 0:
                logger.debug(f"No results for facility {facility_code}")
                return slots

            # Find available time slots
            selector = (
                ".time-slot.available, .court-available, .buttonAllOk, "
                "button.buttonAllOk, a.buttonAllOk, input.buttonAllOk, "
                "[equipmentid], [data-equipment-id], [data-equipmentid]"
            )
            time_slots = facility_section.locator(selector)
            count = await time_slots.count()

            for i in range(count):
                slot = await self._parse_slot_locator(
                    time_slots.nth(i), facility_code, target_date, request
                )
                if (
                    slot
                    and request.is_time_in_range(slot.time_start)
                    and self._slot_matches_request(slot, request)
                ):
                    slots.append(slot)

        except PlaywrightError as e:
            logger.debug(f"Error parsing facility results: {e}")

        return slots

    async def _parse_all_results(
        self,
        target_date: datetime,
        request: BookingRequest,
    ) -> list[CourtSlot]:
        """Parse all available slots from search results."""
        slots: list[CourtSlot] = []
        try:
            selector = (
                ".time-slot.available, .court-available, .buttonAllOk, "
                "button.buttonAllOk, a.buttonAllOk, input.buttonAllOk, "
                "[equipmentid], [data-equipment-id], [data-equipmentid]"
            )
            available_elements = self.page.locator(selector)
            count = await available_elements.count()

            for i in range(count):
                slot = await self._parse_slot_locator(
                    available_elements.nth(i), "", target_date, request
                )
                if (
                    slot
                    and request.is_time_in_range(slot.time_start)
                    and self._slot_matches_request(slot, request)
                ):
                    slots.append(slot)

        except PlaywrightError as e:
            logger.debug(f"Error parsing all results: {e}")

        return slots

    async def _parse_slot_locator(
        self,
        locator,
        facility_code: str,
        target_date: datetime,
        request: BookingRequest,
    ) -> Optional[CourtSlot]:
        """Parse a Playwright locator into a CourtSlot."""
        try:

            async def get_attr(*names: str) -> Optional[str]:
                for name in names:
                    try:
                        value = await locator.get_attribute(name)
                        if value:
                            return str(value).strip()
                    except PlaywrightError:
                        continue
                return None

            equipment_id = await get_attr(
                "equipmentId", "equipmentid", "data-equipment-id", "data-equipmentid"
            )
            court_id = await get_attr("courtId", "courtid", "data-court-id", "data-courtid")
            date_deb = await get_attr("dateDeb", "datedeb", "data-date-deb", "data-datedeb")
            date_fin = await get_attr("dateFin", "datefin", "data-date-fin", "data-datefin")

            if not equipment_id or not court_id:
                return None

            facility_name = (
                await get_attr(
                    "data-facility-name", "data-facilityname", "facilityName", "facility"
                )
                or ""
            )

            if not facility_code:
                facility_code = (
                    await get_attr(
                        "data-facility", "data-facility-code", "data-facilitycode", "facilityCode"
                    )
                    or ""
                )

            reservation_start = self._parse_slot_datetime(date_deb) if date_deb else None
            reservation_end = self._parse_slot_datetime(date_fin) if date_fin else None

            time_start = reservation_start.strftime("%H:%M") if reservation_start else ""
            time_end = reservation_end.strftime("%H:%M") if reservation_end else ""

            if not time_start:
                time_start = normalize_time(
                    await get_attr("data-start", "data-deb", "start", "hourStart") or ""
                )
            if not time_end:
                time_end = normalize_time(
                    await get_attr("data-end", "data-fin", "end", "hourEnd") or ""
                )

            court_number = (
                await get_attr(
                    "data-court", "data-court-number", "courtNumber", "courtnumber", "court"
                )
                or ""
            )

            # Detect court type
            indoor_outdoor = (
                await get_attr("indooroutdoor", "data-indooroutdoor", "data-indoor-outdoor") or ""
            )
            court_type = self._determine_court_type(indoor_outdoor)

            return CourtSlot(
                facility_name=facility_name or facility_code,
                facility_code=facility_code or self._normalize_facility_code(facility_name),
                court_number=court_number,
                date=target_date,
                time_start=time_start,
                time_end=time_end,
                court_type=court_type,
                equipment_id=equipment_id,
                court_id=court_id,
                reservation_start=reservation_start,
                reservation_end=reservation_end,
            )

        except PlaywrightError as e:
            logger.debug(f"Failed to parse slot locator: {e}")
            return None

    def _detect_court_type_from_element(self, element) -> Optional[CourtType]:
        """Best-effort court type detection from DOM attributes or text."""
        attributes = [
            "data-court-type",
            "data-court_type",
            "data-type",
            "data-surface",
            "data-cover",
            "data-covered",
            "data-court-cover",
            "class",
            "aria-label",
            "title",
        ]

        candidates: list[str] = []
        for attr in attributes:
            try:
                value = element.get_attribute(attr)
            except Exception:
                value = None
            if value:
                candidates.append(value)

        try:
            text_value = element.text
        except Exception:
            text_value = ""
        if text_value:
            candidates.append(text_value)

        for candidate in candidates:
            normalized = _normalize_court_type_text(candidate)
            if not normalized:
                continue
            for court_type, keywords in COURT_TYPE_KEYWORDS.items():
                if any(keyword in normalized for keyword in keywords):
                    return court_type

        return None

    def _parse_slot_element(
        self,
        element,
        facility_code: str,
        target_date: datetime,
        request: BookingRequest,
    ) -> Optional[CourtSlot]:
        """Parse a single slot element into CourtSlot."""
        try:
            get_attr = self._get_dom_element_attr

            facility_name = (
                get_attr(
                    element,
                    "data-facility-name",
                    "data-facilityname",
                    "facilityName",
                    "facility",
                )
                or ""
            )
            facility_address = (
                get_attr(
                    element,
                    "data-facility-address",
                    "data-address",
                    "data-adresse",
                )
                or ""
            )

            if not facility_code:
                facility_code = (
                    get_attr(
                        element,
                        "data-facility",
                        "data-facility-code",
                        "data-facilitycode",
                        "facilityCode",
                    )
                    or ""
                )
            if not facility_name:
                facility_name = self._infer_facility_name_from_dom(element) or ""
            if not facility_name and facility_code:
                facility_name = facility_code
            if not facility_code and facility_name:
                facility_code = self._normalize_facility_code(facility_name)

            equipment_id = get_attr(
                element,
                "equipmentId",
                "equipmentid",
                "data-equipment-id",
                "data-equipmentid",
            )
            court_id = get_attr(
                element,
                "courtId",
                "courtid",
                "data-court-id",
                "data-courtid",
            )
            date_deb = get_attr(
                element,
                "dateDeb",
                "datedeb",
                "data-date-deb",
                "data-datedeb",
            )
            date_fin = get_attr(
                element,
                "dateFin",
                "datefin",
                "data-date-fin",
                "data-datefin",
            )
            extra_params = self._extract_slot_params_from_sources(
                get_attr(element, "href"),
                get_attr(element, "onclick"),
            )
            if extra_params:
                equipment_id = equipment_id or extra_params.get("equipment_id")
                court_id = court_id or extra_params.get("court_id")
                date_deb = date_deb or extra_params.get("date_deb")
                date_fin = date_fin or extra_params.get("date_fin")
            reservation_start = self._parse_slot_datetime(date_deb) if date_deb else None
            reservation_end = self._parse_slot_datetime(date_fin) if date_fin else None

            time_start = reservation_start.strftime("%H:%M") if reservation_start else ""
            time_end = reservation_end.strftime("%H:%M") if reservation_end else ""
            if not time_start:
                time_start = normalize_time(
                    get_attr(element, "data-start", "data-deb", "start", "hourStart") or ""
                )
            if not time_end:
                time_end = normalize_time(
                    get_attr(element, "data-end", "data-fin", "end", "hourEnd") or ""
                )

            court_number = (
                get_attr(
                    element,
                    "data-court",
                    "data-court-number",
                    "courtNumber",
                    "courtnumber",
                    "court",
                )
                or ""
            )
            court_text = ""
            price_description = ""
            price_text = ""
            try:
                court_container = element.find_element(
                    By.XPATH, "ancestor::*[contains(@class,'tennis-court')][1]"
                )
            except Exception:
                court_container = None

            if court_container:
                try:
                    court_span = court_container.find_element(By.CSS_SELECTOR, "span.court")
                    court_text = (court_span.text or "").strip()
                except Exception:
                    court_text = ""

                try:
                    price_desc_elem = court_container.find_element(
                        By.CSS_SELECTOR, ".price-description"
                    )
                    price_description = (price_desc_elem.text or "").strip()
                except Exception:
                    price_description = ""

                try:
                    price_elem = court_container.find_element(By.CSS_SELECTOR, ".price")
                    price_text = (price_elem.text or "").strip()
                except Exception:
                    price_text = ""

            if not court_text:
                try:
                    court_text = (element.text or "").strip()
                except Exception:
                    court_text = ""

            if court_text:
                parsed_court = self._parse_court_number(court_text)
                if parsed_court and not court_number:
                    court_number = parsed_court

            type_price = (
                get_attr(
                    element,
                    "typePrice",
                    "typeprice",
                    "data-type-price",
                    "data-typeprice",
                )
                or ""
            )
            indoor_outdoor = (
                get_attr(
                    element,
                    "indoorOutdoor",
                    "indooroutdoor",
                    "data-indoor-outdoor",
                    "data-indooroutdoor",
                )
                or ""
            )
            if extra_params:
                type_price = type_price or extra_params.get("type_price", "")
                indoor_outdoor = indoor_outdoor or extra_params.get("indoor_outdoor", "")
            combined_price_text = " ".join(
                [text for text in (type_price, indoor_outdoor, price_description) if text]
            ).strip()

            detected_type = self._detect_court_type_from_element(element)
            court_type = detected_type or self._parse_court_type_from_text(
                court_text, combined_price_text
            )

            price_value = get_attr(element, "price", "data-price", "data-price-value")
            if extra_params:
                price_value = price_value or extra_params.get("price")
            price = self._parse_price_value(price_value)
            if price is None and price_text:
                price = self._parse_price_value(price_text)

            captcha_request_id = None
            if extra_params:
                captcha_request_id = extra_params.get("captcha_request_id")

            return CourtSlot(
                facility_name=facility_name,
                facility_code=facility_code,
                court_number=court_number,
                date=reservation_start or target_date,
                time_start=time_start,
                time_end=time_end,
                court_type=court_type,
                facility_address=facility_address if facility_address else None,
                price=price,
                equipment_id=equipment_id,
                court_id=court_id,
                reservation_start=reservation_start,
                reservation_end=reservation_end,
                captcha_request_id=captcha_request_id,
            )
        except Exception as e:
            logger.debug(f"Failed to parse slot element: {e}")
            return None

    def _slot_matches_request(self, slot: CourtSlot, request: BookingRequest) -> bool:
        """Validate slot against request court type preference."""
        if request.court_type == CourtType.ANY:
            return True
        if slot.court_type == CourtType.ANY:
            return True
        if slot.court_type != request.court_type:
            logger.debug(
                "Skipping slot %s/%s due to court type mismatch (%s != %s)",
                slot.facility_code,
                slot.court_number,
                slot.court_type.value,
                request.court_type.value,
            )
            return False
        return True

    async def book_court(
        self,
        slot: CourtSlot,
        partner_name: Optional[str] = None,
        player_name: Optional[str] = None,
        player_email: Optional[str] = None,
        partner_email: Optional[str] = None,
    ) -> BookingResult:
        """
        Book a specific court slot.

        Args:
            slot: The CourtSlot to book
            partner_name: Name of the playing partner
            player_name: Name of the booking user for reservation forms
            player_email: Email of the booking user for reservation forms
            partner_email: Email of the partner for reservation forms

        Returns:
            BookingResult with success status and confirmation ID

        """
        if not self._logged_in:
            return BookingResult(
                success=False,
                error_message="Not logged in",
            )

        try:
            logger.info(
                f"Attempting to book {slot.facility_name} court {slot.court_number} "
                f"at {slot.time_start}"
            )

            if not slot.equipment_id or not slot.court_id or not slot.reservation_start:
                return BookingResult(
                    success=False,
                    error_message="Missing reservation identifiers for slot",
                    slot=slot,
                )

            captcha_request_id = slot.captcha_request_id
            if not captcha_request_id:
                current_url = self.page.url or ""
                if SEARCH_RESULTS_QUERY in current_url or "page=recherche" in current_url:
                    captcha_request_id = await self._get_captcha_request_id()

            if not captcha_request_id:
                target_date = slot.reservation_start or slot.date
                facility_names = [slot.facility_name] if slot.facility_name else None
                hour_range = self._format_hour_range(slot.time_start, slot.time_end)
                sel_in_out = self._get_indoor_outdoor_values(slot.court_type)
                captcha_request_id = await self._ensure_search_results_page(
                    target_date=target_date,
                    facility_names=facility_names,
                    hour_range=hour_range,
                    sel_in_out=sel_in_out,
                )
            li_token, li_token_code = await self._ensure_valid_li_antibot_tokens()
            if not li_token:
                li_token_code = None
            await self._submit_reservation_form(
                slot,
                captcha_request_id,
                li_token,
                li_token_code,
            )
            await self._wait_for_booking_state()
            logger.info(f"Booking state reached, URL: {self.page.url}")
            await self._solve_captcha_if_present()
            logger.info("First captcha check completed")

            logger.info("Handling reservation details...")
            handled = await self._handle_reservation_details(
                player_name=player_name,
                player_email=player_email,
                partner_name=partner_name,
                partner_email=partner_email,
            )
            logger.info(f"Reservation details handled: {handled}, URL: {self.page.url}")
            await self._solve_captcha_if_present()
            logger.info("Second captcha check completed")

            if await self._handle_payment_step():
                logger.info("Payment step handled successfully")
            else:
                logger.info("No payment step found or not handled")
            await self._solve_captcha_if_present()
            logger.info(f"Third captcha check completed, URL: {self.page.url}")

            # Confirm booking if confirmation button is present
            try:
                confirm_button = self.page.locator(".confirm-booking, #confirmBooking")
                await confirm_button.first.wait_for(
                    state="visible", timeout=BOOKING_WAIT_TIMEOUT * 1000
                )
                await confirm_button.first.click()
                logger.info("Clicked confirmation button")
            except PlaywrightTimeoutError:
                logger.debug("Confirmation button not found after CAPTCHA")

            # Wait for confirmation
            await asyncio.sleep(2)
            logger.info(f"Final page URL: {self.page.url}")

            # Log page content for debugging
            try:
                page_text = await self.page.text_content("body")
                if page_text:
                    logger.debug(f"Page text preview: {page_text[:500]}...")
            except Exception as e:
                logger.debug(f"Could not get page text: {e}")

            # Extract confirmation ID
            confirmation_id = await self._extract_confirmation_id()

            if confirmation_id:
                logger.info(f"Booking successful! Confirmation: {confirmation_id}")
                return BookingResult(
                    success=True,
                    confirmation_id=confirmation_id,
                    slot=slot,
                )
            else:
                # Check for success via URL or specific DOM elements
                if await self._check_booking_success():
                    logger.info("Booking success detected (no explicit confirmation ID)")
                    return BookingResult(
                        success=True,
                        confirmation_id="CONFIRMED",
                        slot=slot,
                    )
                # No confirmation ID and no reliable success signal
                logger.warning(f"No booking confirmation detected. URL: {self.page.url}")
                return BookingResult(
                    success=False,
                    error_message="Booking confirmation not received",
                    slot=slot,
                )

        except PlaywrightTimeoutError:
            logger.error("Booking timeout - elements not found")
            return BookingResult(
                success=False,
                error_message="Booking page timeout",
                slot=slot,
            )
        except PlaywrightError as e:
            logger.error(f"Playwright error during booking: {e}")
            return BookingResult(
                success=False,
                error_message=str(e),
                slot=slot,
            )

    async def _check_for_captcha(self) -> bool:
        """Check if CAPTCHA verification is present."""
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
            "#captcha",
            "#li-antibot",
            "#formCaptcha",
            # Paris Tennis security verification page
            "fieldset img[src*='Captcha']",
            "fieldset img[src*='captcha']",
        ]
        for selector in captcha_selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() > 0:
                    logger.debug(f"CAPTCHA detected via selector: {selector}")
                    return True
            except PlaywrightError:
                continue
        page_source = (await self.page.content() or "").lower()
        if (
            "recaptcha/api.js?render=" in page_source
            or "grecaptcha.execute" in page_source
            or "data-sitekey" in page_source
            or "li_antibot.loadantibot" in page_source
        ):
            return True
        # Paris Tennis: check for security verification page
        if "vérification de sécurité" in page_source or "verification de securite" in page_source:
            logger.debug("CAPTCHA detected: security verification page")
            return True
        return False

    async def _wait_for_booking_state(self, timeout: int = BOOKING_WAIT_TIMEOUT) -> None:
        """Wait for the reservation flow to reach a CAPTCHA or booking step."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if (
                await self._check_for_captcha()
                or await self._is_reservation_details_page()
                or await self._is_payment_page()
            ):
                return
            await asyncio.sleep(0.5)

    async def _submit_captcha_form_if_present(self) -> bool:
        """Submit the CAPTCHA form if it is present."""
        try:
            form = self.page.locator("#formCaptcha")
            if await form.count() == 0:
                return False
        except PlaywrightError:
            return False

        submitted = False
        for selector in CAPTCHA_SUBMIT_SELECTORS:
            try:
                button = form.locator(selector)
                if await button.count() > 0 and await button.first.is_visible():
                    await button.first.click()
                    submitted = True
                    break
            except PlaywrightError:
                continue

        if not submitted:
            # Try submit buttons with text
            try:
                button = form.locator("button:has-text('Valider'), button:has-text('Confirmer')")
                if await button.count() > 0 and await button.first.is_visible():
                    await button.first.click()
                    submitted = True
            except PlaywrightError:
                pass

        if not submitted:
            try:
                await self.page.evaluate("""
                    const form = document.getElementById('formCaptcha');
                    if (form) form.submit();
                """)
                submitted = True
            except PlaywrightError:
                submitted = False

        if submitted:
            try:
                # Wait for the captcha form to disappear
                await self.page.wait_for_selector("#formCaptcha", state="detached", timeout=10000)
            except PlaywrightTimeoutError:
                pass

        return submitted

    def _normalize_label_text(self, value: str) -> str:
        """Normalize label text for matching form fields."""
        return _normalize_court_type_text(value or "")

    async def _get_input_label_text(self, locator) -> str:
        """Return the best-effort label text for an input element."""
        try:
            label_text = await self.page.evaluate(
                """(el) => {
                    const group = el.closest('.form-group');
                    if (!group) return '';
                    const label = group.querySelector('label');
                    return label ? (label.textContent || '') : '';
                }""",
                await locator.element_handle(),
            )
            if label_text:
                return str(label_text)
        except PlaywrightError:
            pass

        for attr in ("aria-label", "placeholder", "title", "name"):
            try:
                value = await locator.get_attribute(attr)
                if value:
                    return str(value)
            except PlaywrightError:
                continue

        return ""

    async def _has_visible_inputs(self, name: str) -> bool:
        """Return True if any visible inputs exist for the given name."""
        try:
            locator = self.page.locator(f"input[name='{name}']")
            count = await locator.count()
            for i in range(count):
                if await locator.nth(i).is_visible():
                    return True
            return False
        except PlaywrightError:
            return False

    def _split_full_name(self, full_name: Optional[str]) -> tuple[str, str]:
        """Split a full name into first and last names."""
        if not full_name:
            return "", ""
        cleaned = " ".join(str(full_name).strip().split())
        if not cleaned:
            return "", ""
        if "," in cleaned:
            last, first = [part.strip() for part in cleaned.split(",", 1)]
            if not first:
                first = last
            if not last:
                last = first
            return first, last
        parts = cleaned.split(" ")
        if len(parts) == 1:
            return parts[0], parts[0]
        return parts[0], " ".join(parts[1:])

    async def _fill_player_inputs(
        self,
        name: str,
        first_name: str,
        last_name: str,
        email: Optional[str],
    ) -> bool:
        """Fill player fields (name/email) when present on the reservation form."""
        try:
            locator = self.page.locator(f"input[name='{name}']")
            count = await locator.count()
        except PlaywrightError:
            return False

        if count == 0:
            return False

        filled = False
        fallback_values = [value for value in (last_name, first_name) if value]
        fallback_index = 0

        for i in range(count):
            element = locator.nth(i)
            try:
                if not await element.is_visible():
                    continue
            except PlaywrightError:
                continue

            try:
                current_value = await element.input_value() or ""
            except PlaywrightError:
                current_value = ""
            if str(current_value).strip():
                continue

            label_text = self._normalize_label_text(await self._get_input_label_text(element))
            target = None

            if "prenom" in label_text:
                target = first_name
            elif "nom" in label_text:
                target = last_name
            elif "mail" in label_text or "email" in label_text:
                target = email
            elif fallback_index < len(fallback_values):
                target = fallback_values[fallback_index]
                fallback_index += 1

            if not target:
                continue

            try:
                await element.clear()
                await element.fill(target)
                filled = True
            except PlaywrightError:
                continue

        return filled

    async def _click_if_present(self, selector: str) -> bool:
        """Click an element if it exists and is visible."""
        try:
            locator = self.page.locator(selector)
            if await locator.count() == 0:
                return False
            if not await locator.first.is_visible():
                return False
            await locator.first.click()
            return True
        except PlaywrightError:
            try:
                await self.page.evaluate(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (el) el.click();
                    }""",
                    selector,
                )
                return True
            except PlaywrightError:
                return False

    async def _is_reservation_details_page(self) -> bool:
        """Return True if the reservation details form is present."""
        try:
            current_url = self.page.url or ""
        except PlaywrightError:
            current_url = ""

        if "view=reservation_creneau" in current_url:
            return True

        try:
            if await self.page.locator("#submitControle").count() > 0:
                return True
        except PlaywrightError:
            return False

        return await self._has_visible_inputs("player1") or await self._has_visible_inputs("player")

    async def _handle_reservation_details(
        self,
        player_name: Optional[str],
        player_email: Optional[str],
        partner_name: Optional[str],
        partner_email: Optional[str],
        timeout: int = DEFAULT_WAIT_TIMEOUT,
    ) -> bool:
        """Fill reservation details and advance to the payment step when possible."""
        if not await self._is_reservation_details_page():
            logger.debug("Not on reservation details page")
            return False

        logger.debug(
            f"On reservation details page, filling player: {player_name}, partner: {partner_name}"
        )

        # Check if there's a captcha on this page first
        if await self._check_for_captcha():
            logger.warning("Captcha detected on reservation details page!")

        # Paris Tennis form asks for PARTNER details, not the primary player
        # The logged-in user is automatically the primary player (booking owner)
        # We only need to fill in partner/guest information
        filled_partner = False
        if partner_name:
            partner_first, partner_last = self._split_full_name(partner_name)
            logger.debug(f"Split partner name: first={partner_first}, last={partner_last}")
            # Fill player1 (first row) with partner info
            if await self._has_visible_inputs("player1"):
                logger.debug("Found player1 inputs - filling with partner info")
                filled_partner = await self._fill_player_inputs(
                    "player1", partner_first, partner_last, partner_email
                )
                logger.debug(f"Filled player1 with partner: {filled_partner}")
            elif await self._has_visible_inputs("player"):
                logger.debug("Found player inputs - filling with partner info")
                filled_partner = await self._fill_player_inputs(
                    "player", partner_first, partner_last, partner_email
                )
                logger.debug(f"Filled player with partner: {filled_partner}")
        else:
            logger.debug("No partner name provided, skipping partner form filling")

        # Check if button exists before clicking
        submit_button = self.page.locator("#submitControle")
        button_count = await submit_button.count()
        logger.info(f"Found {button_count} #submitControle button(s)")

        # Log form state before submit
        try:
            form_state = await self.page.evaluate("""() => {
                const form = document.querySelector('form');
                if (!form) return {formFound: false};
                const inputs = form.querySelectorAll('input');
                const fields = [];
                inputs.forEach(i => {
                    fields.push({name: i.name, id: i.id, type: i.type, hasValue: !!i.value, valuePreview: i.value ? i.value.slice(0, 30) : ''});
                });
                // Check specifically for captcha/token fields
                const tokenInput = document.querySelector('input[name="li-antibot-token"]');
                const codeInput = document.querySelector('input[name="li-antibot-token-code"]');
                return {
                    formFound: true,
                    formId: form.id,
                    formAction: form.action,
                    fieldCount: inputs.length,
                    fields: fields,
                    hasLiToken: !!tokenInput,
                    liTokenValue: tokenInput ? (tokenInput.value ? tokenInput.value.slice(0, 30) + '...' : 'EMPTY') : 'NOT_FOUND',
                    hasLiCode: !!codeInput,
                    liCodeValue: codeInput ? (codeInput.value || 'EMPTY') : 'NOT_FOUND'
                };
            }""")
            logger.info(
                f"Form state before submit: formId={form_state.get('formId')}, fields={form_state.get('fieldCount')}, liToken={form_state.get('liTokenValue')}, liCode={form_state.get('liCodeValue')}"
            )
            logger.debug(f"Full form state: {form_state}")
        except Exception as e:
            logger.debug(f"Failed to get form state: {e}")

        # Check if submit button is disabled and try to enable it
        try:
            button_state = await self.page.evaluate("""() => {
                // Try multiple selectors for the submit button
                const selectors = [
                    '#submitControle',
                    'button.btn-next',
                    'button[type="submit"]',
                    '.btn-primary:not(.btn-prev)',
                    'a.btn-primary:not(.btn-prev)'
                ];
                for (const sel of selectors) {
                    const btn = document.querySelector(sel);
                    if (btn && (btn.textContent || '').toLowerCase().includes('suivante')) {
                        const isDisabled = btn.disabled || btn.classList.contains('disabled') || btn.hasAttribute('disabled');
                        return {
                            found: true,
                            selector: sel,
                            text: btn.textContent.trim().slice(0, 50),
                            disabled: isDisabled,
                            tagName: btn.tagName
                        };
                    }
                }
                // Fallback to #submitControle
                const btn = document.querySelector('#submitControle');
                if (btn) {
                    return {
                        found: true,
                        selector: '#submitControle',
                        text: btn.textContent ? btn.textContent.trim().slice(0, 50) : '',
                        disabled: btn.disabled || btn.classList.contains('disabled'),
                        tagName: btn.tagName
                    };
                }
                return {found: false};
            }""")
            logger.info(f"Submit button state: {button_state}")

            if button_state.get("disabled"):
                logger.warning("Submit button is DISABLED, attempting to enable...")
                # Try to enable the button and trigger LI_ANTIBOT callback
                await self.page.evaluate("""() => {
                    // Find all potential submit buttons
                    const buttons = document.querySelectorAll('#submitControle, button.btn-next, button[type="submit"], .btn-primary');
                    buttons.forEach(btn => {
                        btn.disabled = false;
                        btn.removeAttribute('disabled');
                        btn.classList.remove('disabled');
                    });
                    // Try to trigger LI_ANTIBOT callbacks
                    if (typeof LI_ANTIBOT !== 'undefined') {
                        console.log('LI_ANTIBOT found:', Object.keys(LI_ANTIBOT));
                        if (LI_ANTIBOT.isValid) {
                            LI_ANTIBOT.isValid = () => true;
                        }
                    }
                    // Trigger form validation
                    const form = document.querySelector('form');
                    if (form && form.checkValidity) {
                        form.checkValidity();
                    }
                }""")
                await asyncio.sleep(0.5)
                logger.info("Attempted to enable submit button")
        except Exception as e:
            logger.debug(f"Failed to check/enable button state: {e}")

        clicked = await self._click_if_present("#submitControle")
        if not clicked:
            # Try alternative selectors for the submit button
            for selector in [
                "button.btn-next",
                ".btn-primary:not(.btn-prev)",
                "button:has-text('Etape suivante')",
            ]:
                clicked = await self._click_if_present(selector)
                if clicked:
                    logger.info(f"Clicked {selector} instead of #submitControle")
                    break

        if not clicked:
            # Last resort: try to submit the form directly via JavaScript
            logger.warning("Could not click button, trying form.submit() directly")
            try:
                await self.page.evaluate("""() => {
                    const form = document.querySelector('form');
                    if (form) {
                        // Trigger submit event
                        const event = new Event('submit', {bubbles: true, cancelable: true});
                        if (form.dispatchEvent(event)) {
                            form.submit();
                        }
                        return true;
                    }
                    return false;
                }""")
                clicked = True
                logger.info("Submitted form via JavaScript")
            except Exception as e:
                logger.debug(f"Form submit failed: {e}")

        if clicked:
            logger.info("Clicked submit button, waiting for payment page...")
            try:
                await self.page.wait_for_url("**/view=methode_paiement**", timeout=timeout * 1000)
                logger.info("Navigated to payment page")
            except PlaywrightTimeoutError:
                logger.warning(f"Timeout waiting for payment page, current URL: {self.page.url}")
                # Take a screenshot for debugging
                try:
                    screenshot_path = "/tmp/reservation_submit_failed.png"
                    await self.page.screenshot(path=screenshot_path, full_page=True)
                    logger.warning(f"Screenshot saved to {screenshot_path}")
                except Exception as e:
                    logger.debug(f"Failed to take screenshot: {e}")
                # Check for error messages on the page
                try:
                    # Paris Tennis specific error selectors
                    error_selectors = [
                        ".error",
                        ".alert-danger",
                        ".portlet-msg-error",
                        ".alert",
                        ".message-error",
                        ".msg-erreur",
                        ".erreur",
                        ".alert-error",
                        ".ui-messages-error",
                        ".ui-message-error",
                        "[class*='error']",
                        "[class*='erreur']",
                    ]
                    for selector in error_selectors:
                        try:
                            locator = self.page.locator(selector)
                            if await locator.count() > 0:
                                error_text = await locator.first.text_content()
                                if error_text and error_text.strip():
                                    logger.warning(
                                        f"Error message ({selector}): {error_text.strip()[:500]}"
                                    )
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"Error checking for messages: {e}")
                # Log page text to understand what's visible - extract lines with error keywords
                try:
                    body_text = await self.page.text_content("body")
                    if body_text:
                        # Look for keywords indicating an error or captcha
                        lower_text = body_text.lower()
                        if "captcha" in lower_text or "vérification" in lower_text:
                            logger.warning("Page appears to have a captcha/verification challenge")
                        if "erreur" in lower_text or "error" in lower_text:
                            logger.warning("Page appears to have an error")
                            # Extract lines containing error keywords
                            lines = body_text.split("\n")
                            for line in lines:
                                line = line.strip()
                                if line and (
                                    "erreur" in line.lower()
                                    or "error" in line.lower()
                                    or "invalid" in line.lower()
                                ):
                                    logger.warning(f"Error line: {line[:300]}")
                        # Log first 1500 chars for debugging
                        logger.info(f"Page body text preview: {body_text[:1500]}")
                except Exception as e:
                    logger.debug(f"Error getting body text: {e}")
                # Also check for captcha fields on this form
                try:
                    captcha_fields = await self.page.evaluate("""() => {
                        const form = document.querySelector('form');
                        if (!form) return {formFound: false};
                        const inputs = form.querySelectorAll('input');
                        const fields = [];
                        inputs.forEach(i => {
                            fields.push({name: i.name, id: i.id, type: i.type, value: i.value ? i.value.slice(0, 50) : ''});
                        });
                        return {formFound: true, formId: form.id, formAction: form.action, fieldCount: inputs.length, fields: fields};
                    }""")
                    logger.info(f"Form state after submit: {captcha_fields}")
                except Exception as e:
                    logger.debug(f"Failed to get form state: {e}")
            return True
        else:
            logger.warning("#submitControle button not found or not clickable")

        return filled_partner

    async def _is_payment_page(self) -> bool:
        """Return True if the payment selection form is present."""
        try:
            current_url = self.page.url or ""
        except PlaywrightError:
            current_url = ""

        if "view=methode_paiement" in current_url:
            return True

        try:
            if await self.page.locator("#order_select_payment_form").count() > 0:
                return True
            if await self.page.locator("#paymentMode").count() > 0:
                return True
        except PlaywrightError:
            return False

        return False

    async def _handle_payment_step(self, timeout: int = DEFAULT_WAIT_TIMEOUT) -> bool:
        """Select carnet payment on the payment page and advance."""
        if not await self._is_payment_page():
            return False

        selected = await self._select_carnet_payment_if_present()
        if selected:
            if not await self._click_if_present("#submit"):
                await self._click_if_present("#envoyer")
            try:
                # Wait for URL to change away from payment page
                await self.page.wait_for_function(
                    """() => !window.location.href.includes('view=methode_paiement')""",
                    timeout=timeout * 1000,
                )
            except PlaywrightTimeoutError:
                pass
        return selected

    async def _select_carnet_payment_if_present(self) -> bool:
        """
        Attempt to select a carnet payment option if one is present.

        Returns:
            True if a carnet option was found/selected, False otherwise.

        """
        try:
            input_selectors = [
                "input[type='radio'][value*='carnet']",
                "input[type='radio'][name*='carnet']",
                "input[type='radio'][id*='carnet']",
                "input[type='checkbox'][value*='carnet']",
                "input[type='checkbox'][name*='carnet']",
                "input[type='checkbox'][id*='carnet']",
                "[data-payment*='carnet']",
            ]

            for selector in input_selectors:
                locator = self.page.locator(selector)
                count = await locator.count()
                for i in range(count):
                    elem = locator.nth(i)
                    try:
                        if await elem.is_checked():
                            return True
                        await elem.click()
                        return True
                    except PlaywrightError:
                        continue

            # Try labels containing "carnet"
            labels = self.page.locator("label")
            count = await labels.count()
            for i in range(count):
                label = labels.nth(i)
                try:
                    text = (await label.text_content() or "").strip().lower()
                    if "carnet" in text:
                        await label.click()
                        return True
                except PlaywrightError:
                    continue

            price_selectors = [
                ".price-item.option",
                ".priceTable .option",
                ".price-item",
            ]
            for selector in price_selectors:
                locator = self.page.locator(selector)
                count = await locator.count()
                for i in range(count):
                    elem = locator.nth(i)
                    try:
                        text = (await elem.text_content() or "").strip().lower()
                    except PlaywrightError:
                        text = ""
                    if "carnet" in text or "ticket" in text:
                        await elem.click()
                        return True

            selects = self.page.locator("select")
            select_count = await selects.count()
            for i in range(select_count):
                select = selects.nth(i)
                options = select.locator("option")
                option_count = await options.count()
                for j in range(option_count):
                    option = options.nth(j)
                    try:
                        text = (await option.text_content() or "").strip().lower()
                        value = (await option.get_attribute("value") or "").strip().lower()
                        if "carnet" in text or "carnet" in value:
                            await select.select_option(value=await option.get_attribute("value"))
                            return True
                    except PlaywrightError:
                        continue

            return False
        except PlaywrightError as e:
            logger.debug(f"Failed to select carnet payment option: {e}")
            return False

    async def _extract_confirmation_id(self) -> Optional[str]:
        """Extract booking confirmation ID from page."""
        try:
            # Look for confirmation ID in various places
            selectors = [
                ".confirmation-id",
                "#confirmationId",
                "[data-confirmation-id]",
            ]
            for selector in selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        text = await locator.first.text_content()
                        if not text:
                            text = await locator.first.get_attribute("data-confirmation-id")
                        if text:
                            return text.strip()
                except PlaywrightError:
                    continue
            return None
        except PlaywrightError:
            return None

    async def _check_booking_success(self) -> bool:
        """Check for booking success indicators.

        Only returns True for specific, reliable confirmation signals:
        - Confirmation page URL patterns
        - Specific confirmation DOM elements
        Does NOT match generic text like "success" which causes false positives.
        """
        try:
            # Check URL for confirmation page pattern
            current_url = self.page.url.lower()
            if any(
                pattern in current_url
                for pattern in ["confirmation", "confirmed", "success", "recapitulatif"]
            ):
                logger.info(f"Booking success detected via URL: {current_url}")
                return True

            # Check for specific confirmation elements (not generic text)
            confirmation_selectors = [
                ".booking-confirmation",
                ".reservation-confirmation",
                "#booking-success",
                "[data-booking-confirmed]",
                ".confirmation-message",
                # Paris Tennis specific
                ".recapitulatif-reservation",
                "#recapitulatif",
            ]
            for selector in confirmation_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0 and await locator.first.is_visible():
                        logger.info(f"Booking success detected via element: {selector}")
                        return True
                except Exception:
                    continue

            # No reliable confirmation signal found
            return False
        except Exception as e:
            logger.debug(f"Error checking booking success: {e}")
            return False

    async def logout(self) -> bool:
        """Log out of the Paris Tennis website."""
        try:
            for selector in PARIS_TENNIS_LOGOUT_SELECTORS:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0 and await locator.first.is_visible():
                        await locator.first.click()
                        self._logged_in = False
                        logger.info("Logged out successfully")
                        return True
                except PlaywrightError:
                    continue

            # Fallback: try link with "Déconnexion" text
            logout_link = self.page.locator("a:has-text('Déconnexion')")
            if await logout_link.count() > 0:
                await logout_link.first.click()
                self._logged_in = False
                logger.info("Logged out successfully")
                return True

            logger.warning("Logout link not found")
            return False
        except PlaywrightError:
            logger.warning("Logout link not found")
            return False


def create_paris_tennis_session(headless: Optional[bool] = None):
    """
    Async context manager for Paris Tennis service with browser session.

    Usage:
        async with create_paris_tennis_session() as service:
            if await service.login(email, password):
                slots = await service.search_available_courts(request)
    """
    return _ParisTennisSession(headless=headless)


class _ParisTennisSession:
    """Async context manager wrapper for ParisTennisService with browser."""

    def __init__(self, headless: Optional[bool] = None):
        self._headless = headless
        self._session: Optional[PlaywrightSession] = None
        self._service: Optional[ParisTennisService] = None

    async def __aenter__(self) -> ParisTennisService:
        self._session = PlaywrightSession(headless=self._headless)
        await self._session.start()
        self._service = ParisTennisService(page=self._session.page)
        return self._service

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
