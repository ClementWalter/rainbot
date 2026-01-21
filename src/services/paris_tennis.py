"""Paris Tennis website automation service.

This module provides automation for interacting with the Paris Tennis
booking website (tennis.paris.fr) using Selenium WebDriver.
"""

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.config.settings import settings
from src.models.booking_request import BookingRequest, CourtType, normalize_time
from src.services.captcha_solver import CaptchaSolverService, get_captcha_service
from src.utils.browser import browser_session
from src.utils.timezone import now_paris

logger = logging.getLogger(__name__)

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
        driver: Optional[WebDriver] = None,
        captcha_solver: Optional[CaptchaSolverService] = None,
    ):
        """
        Initialize the Paris Tennis service.

        Args:
            driver: Optional WebDriver instance. If not provided,
                   a new browser session will be created for each operation.
            captcha_solver: Optional CAPTCHA solver service. If not provided,
                           uses the global instance.
        """
        self._driver = driver
        self._captcha_solver = captcha_solver
        self._logged_in = False
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
    def driver(self) -> WebDriver:
        """Get the WebDriver instance."""
        if self._driver is None:
            raise RuntimeError("No WebDriver available. Use a browser session.")
        return self._driver

    def login(self, email: str, password: str) -> bool:
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
            self.driver.get(self.login_url)

            wait = WebDriverWait(self.driver, DEFAULT_WAIT_TIMEOUT)

            # Accept cookie banner if present
            self._accept_cookie_banner()

            # Click login entry point if we're on the public landing page
            self._click_login_entrypoint(wait)

            # If we are already logged in, short-circuit
            if self._is_logged_in():
                self._logged_in = True
                logger.info(f"Login already active for {email}")
                return True

            # Wait for and fill email field on the Mon Paris SSO form
            email_field = self._ensure_login_form(wait)
            email_field.clear()
            email_field.send_keys(email)

            # Fill password field
            password_field = self.driver.find_element(By.ID, "password")
            password_field.clear()
            password_field.send_keys(password)

            # Accept cookie banner if present on the SSO page
            self._accept_cookie_banner()

            # Click login button
            login_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"
            )
            login_button.click()

            # Wait for successful login (check for user menu or redirect)
            time.sleep(2)  # Brief wait for page transition

            # Solve CAPTCHA on the login flow if present, then resubmit.
            if self._solve_captcha_if_present(wait):
                self._submit_login_form_if_present()
                time.sleep(1)

            # Check if login was successful by looking for logout link or user info
            if self._is_logged_in():
                self._logged_in = True
                logger.info(f"Login successful for {email}")
                return True
            else:
                logger.warning(f"Login failed for {email}")
                return False

        except TimeoutException:
            logger.error("Login page elements not found - timeout")
            return False
        except NoSuchElementException as e:
            logger.error(f"Login element not found: {e}")
            return False
        except WebDriverException as e:
            logger.error(f"WebDriver error during login: {e}")
            return False

    def _is_logged_in(self) -> bool:
        """Check if currently logged in."""
        try:

            def is_element_visible(element) -> bool:
                try:
                    return element.is_displayed()
                except WebDriverException:
                    return False

            def has_visible_element(selector_list: list[tuple[By, str]]) -> bool:
                for by, value in selector_list:
                    try:
                        elements = self.driver.find_elements(by, value)
                    except WebDriverException:
                        continue
                    for element in elements:
                        if is_element_visible(element):
                            return True
                return False

            # Prefer explicit connected/disconnected nav state when available.
            if has_visible_element([(By.CSS_SELECTOR, ".navbar-collapse.connected")]):
                return True
            if has_visible_element([(By.CSS_SELECTOR, ".navbar-collapse.disconnected")]):
                return False

            # Visible login button indicates logged-out state on landing pages.
            if has_visible_element([(By.CSS_SELECTOR, "#button_suivi_inscription")]):
                return False

            # Fallback to other indicators when nav state is unavailable.
            indicators = [
                (By.CSS_SELECTOR, ".user-menu"),
                (By.CSS_SELECTOR, ".logout"),
                (By.CSS_SELECTOR, ".banner-mon-compte__connected-avatar"),
                (By.CSS_SELECTOR, "#banner-mon-compte__logout"),
                (By.CSS_SELECTOR, "#banner-mon-compte_menu__logout"),
                (By.LINK_TEXT, "Déconnexion"),
                (By.PARTIAL_LINK_TEXT, "Mon compte"),
            ]
            return has_visible_element(indicators)
        except WebDriverException:
            return False

    def _accept_cookie_banner(self) -> None:
        """Dismiss cookie banners if present."""
        for selector in COOKIE_ACCEPT_SELECTORS:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
                element.click()
                return
            except NoSuchElementException:
                continue
            except WebDriverException:
                continue
            except Exception:
                continue

    def _click_login_entrypoint(self, wait: WebDriverWait) -> bool:
        """Click the login entry point on the public landing page if present."""
        for selector in LOGIN_BUTTON_SELECTORS:
            try:
                element = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                element.click()
                return True
            except TimeoutException:
                continue
            except WebDriverException:
                continue

        # Fallback: match French login button text
        try:
            button = self.driver.find_element(
                By.XPATH,
                "//button[contains(normalize-space(.), 'Je me connecte') "
                "or contains(normalize-space(.), 'Se connecter')]",
            )
            button.click()
            return True
        except NoSuchElementException:
            pass
        except WebDriverException:
            pass

        if self._navigate_to_mon_paris(wait):
            return True

        return False

    def _navigate_to_mon_paris(self, wait: WebDriverWait) -> bool:
        """Navigate to the Mon Paris login entrypoint if visible on the page."""
        for selector in MON_PARIS_LINK_SELECTORS:
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
            except NoSuchElementException:
                continue
            except WebDriverException:
                continue

            href = element.get_attribute("href") or ""
            if href:
                try:
                    self.driver.get(href)
                    return True
                except WebDriverException:
                    continue

            # Fallback to clicking (may open a new tab)
            previous_handles = set(self.driver.window_handles)
            try:
                element.click()
            except WebDriverException:
                continue

            try:
                wait.until(lambda driver: len(driver.window_handles) > len(previous_handles))
            except TimeoutException:
                return True

            new_handles = [
                handle for handle in self.driver.window_handles if handle not in previous_handles
            ]
            if new_handles:
                try:
                    self.driver.switch_to.window(new_handles[-1])
                except WebDriverException:
                    return False
            return True
        return False

    def _open_mon_paris_login(self, wait: WebDriverWait) -> bool:
        """Click through the Mon Paris login dropdown to reach the SSO form."""
        current_url = self.driver.current_url or ""
        if "moncompte.paris.fr" not in current_url:
            return False

        self._accept_cookie_banner()

        for selector in MON_PARIS_LOGIN_MENU_SELECTORS:
            try:
                menu_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                menu_button.click()
                break
            except TimeoutException:
                continue
            except WebDriverException:
                continue

        for xpath in MON_PARIS_LOGIN_LINK_XPATHS:
            try:
                login_link = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                login_link.click()
                return True
            except TimeoutException:
                continue
            except WebDriverException:
                continue

        return False

    def _ensure_login_form(self, wait: WebDriverWait):
        """Ensure the Mon Paris login form is visible and return the email field."""
        try:
            return wait.until(EC.presence_of_element_located((By.ID, "username")))
        except TimeoutException:
            if self._open_mon_paris_login(wait):
                return wait.until(EC.presence_of_element_located((By.ID, "username")))
            raise

    def _submit_login_form_if_present(self) -> bool:
        """Submit the login form if it's still present after CAPTCHA solving."""
        try:
            password_field = self.driver.find_element(By.ID, "password")
            try:
                form = password_field.find_element(By.XPATH, "ancestor::form[1]")
            except NoSuchElementException:
                form = None
            if form is not None:
                self.driver.execute_script("arguments[0].submit();", form)
                return True
        except (NoSuchElementException, WebDriverException):
            pass

        try:
            submit_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"
            )
            submit_button.click()
            return True
        except (NoSuchElementException, WebDriverException):
            return False

    def search_available_courts(
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

        try:
            logger.info(f"Searching courts for {target_date.strftime('%Y-%m-%d')}")

            when_value = target_date.strftime("%d/%m/%Y")
            hour_range = self._format_hour_range(request.time_start, request.time_end)
            sel_in_out = self._get_indoor_outdoor_values(request.court_type)

            # Navigate to search page and load results context
            self.driver.get(self.search_url)
            wait = WebDriverWait(self.driver, DEFAULT_WAIT_TIMEOUT)
            self._accept_cookie_banner()

            facility_names = self._resolve_facility_preferences(request)
            captcha_request_id = self._ensure_search_results_page(
                wait,
                target_date=target_date,
                facility_names=facility_names if facility_names else None,
                hour_range=hour_range,
                sel_in_out=sel_in_out,
            )

            sel_coating = self._get_surface_values()
            if not facility_names:
                facility_names = self._resolve_facility_preferences(request)

            if not facility_names:
                logger.warning("No facility preferences resolved; falling back to DOM parsing")
                available_slots = self._parse_all_results(target_date, request)
                available_slots = self._filter_slots_by_facility_preferences(
                    available_slots, request
                )
                available_slots = self._sort_available_slots(available_slots, request)
                logger.info(f"Found {len(available_slots)} available slots (DOM fallback)")
                return available_slots

            for facility_name in facility_names:
                html, captcha_request_id = self._fetch_availability_html(
                    hour_range=hour_range,
                    when_value=when_value,
                    facility_name=facility_name,
                    sel_in_out=sel_in_out,
                    sel_coating=sel_coating,
                    captcha_request_id=captcha_request_id,
                )
                if not html:
                    continue
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
                available_slots = self._parse_all_results(target_date, request)
                available_slots = self._filter_slots_by_facility_preferences(
                    available_slots, request
                )

            available_slots = self._sort_available_slots(available_slots, request)

            logger.info(f"Found {len(available_slots)} available slots")
            return available_slots

        except TimeoutException:
            logger.error("Search page timeout")
            return []
        except WebDriverException as e:
            logger.error(f"WebDriver error during search: {e}")
            return []

    def _get_next_booking_date(self, day_of_week: int) -> datetime:
        """Get the next date for the given day of week in Paris timezone."""
        today = now_paris()
        days_ahead = day_of_week - today.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return today + timedelta(days=days_ahead)

    def _ensure_search_results_page(
        self,
        wait: WebDriverWait,
        target_date: Optional[datetime] = None,
        facility_names: Optional[list[str]] = None,
        hour_range: Optional[str] = None,
        sel_in_out: Optional[list[str]] = None,
    ) -> Optional[str]:
        """Ensure the search results page is loaded and return captcha request id if available."""
        try:
            current_url = self.driver.current_url or ""
            already_results = SEARCH_RESULTS_QUERY in current_url

            if not already_results and "page=recherche" not in current_url:
                self.driver.get(self.search_url)
                self._accept_cookie_banner()

            self._configure_search_form(
                target_date=target_date,
                facility_names=facility_names,
                hour_range=hour_range,
                sel_in_out=sel_in_out,
            )

            if already_results and not any([target_date, facility_names, hour_range, sel_in_out]):
                self._solve_captcha_if_present(wait)
                return self._get_captcha_request_id()

            if self._submit_search_form_if_present():
                try:
                    wait.until(lambda driver: SEARCH_RESULTS_QUERY in (driver.current_url or ""))
                except TimeoutException:
                    pass
                self._solve_captcha_if_present(wait)
                time.sleep(1)
                return self._get_captcha_request_id()

            # Click the search button to enter results context (fallback)
            search_button = wait.until(EC.element_to_be_clickable((By.ID, "rechercher")))
            search_button.click()
            wait.until(lambda driver: SEARCH_RESULTS_QUERY in (driver.current_url or ""))
            self._solve_captcha_if_present(wait)
            time.sleep(1)
            return self._get_captcha_request_id()
        except (TimeoutException, WebDriverException):
            return None

    def _solve_captcha_if_present(self, wait: Optional[WebDriverWait] = None) -> bool:
        """Solve CAPTCHA on the current page if detected."""
        try:
            if not self._check_for_captcha():
                return False
        except WebDriverException as e:
            logger.debug("CAPTCHA check failed: %s", e)
            return False

        if not (self._captcha_solver or settings.captcha.api_key):
            logger.warning("CAPTCHA detected but solver API key is not configured")
            return False

        logger.info("CAPTCHA detected - attempting to solve")
        try:
            captcha_result = self.captcha_solver.solve_captcha_from_page(self.driver, max_retries=3)
        except ValueError as e:
            logger.error("CAPTCHA solver not configured: %s", e)
            return False

        if not captcha_result.success:
            logger.error("CAPTCHA solving failed: %s", captcha_result.error_message)
            return False

        self._submit_captcha_form_if_present(wait)
        return True

    def _submit_search_form_if_present(self) -> bool:
        """Submit the hidden search form to reach the results context."""
        try:
            return bool(self.driver.execute_script("""
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
        except WebDriverException:
            return False

    def _format_french_date_label(self, target_date: datetime) -> str:
        """Format a date value as the French label used by the search input."""
        date_value = target_date.date()
        weekday = FRENCH_WEEKDAYS[date_value.weekday()]
        month = FRENCH_MONTHS[date_value.month - 1]
        return f"{weekday} {date_value.day} {month} {date_value.year}"

    def _configure_search_form(
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
            self.driver.execute_script(
                """
                const whenValue = arguments[0];
                const whenLabel = arguments[1];
                const hourRange = arguments[2];
                const facilityNames = arguments[3] || [];
                const selInOut = arguments[4] || [];

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
                """,
                when_value,
                when_label,
                hour_range,
                facility_names,
                sel_in_out,
            )
        except WebDriverException:
            return

    def _get_captcha_request_id(self) -> Optional[str]:
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
                element = self.driver.find_element(By.CSS_SELECTOR, selector)
            except NoSuchElementException:
                continue
            except WebDriverException:
                continue
            value = self._get_dom_element_attr(
                element,
                "value",
                "data-captcha-request-id",
                "data-captcharequestid",
            )
            if value:
                return value

        try:
            value = self.driver.execute_script("""
                const keys = ['captchaRequestId', 'captcha_request_id', 'captchaRequestID'];
                for (const key of keys) {
                    const candidate = window[key];
                    if (typeof candidate === 'string' && candidate.trim()) {
                        return candidate;
                    }
                }
                return null;
                """)
        except WebDriverException:
            value = None

        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned

        page_source = self.driver.page_source or ""
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

    def _read_li_antibot_tokens(self) -> tuple[Optional[str], Optional[str]]:
        """Read LiveIdentity token values from page inputs."""
        try:
            values = self.driver.execute_script("""
                const tokenInput = document.getElementById('li-antibot-token')
                    || document.querySelector("input[name='li-antibot-token']");
                const codeInput = document.getElementById('li-antibot-token-code')
                    || document.querySelector("input[name='li-antibot-token-code']");
                const token = tokenInput ? tokenInput.value : "";
                const code = codeInput ? codeInput.value : "";
                return [token, code];
                """)
        except WebDriverException:
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
        if "blacklist" in lowered or "invalid" in lowered:
            return False
        return lowered != "invalid response."

    def _ensure_valid_li_antibot_tokens(
        self, wait: Optional[WebDriverWait] = None
    ) -> tuple[Optional[str], Optional[str]]:
        """Refresh LiveIdentity tokens when they are present but invalid."""
        token, code = self._read_li_antibot_tokens()
        if token and not self._is_li_antibot_token_valid(token):
            logger.info("LiveIdentity token invalid; attempting refresh")
            self._solve_captcha_if_present(wait)
            token, code = self._read_li_antibot_tokens()
            if token and not self._is_li_antibot_token_valid(token):
                return None, None
        if not token:
            return None, None
        return token, code

    def _resolve_facility_preferences(self, request: BookingRequest) -> list[str]:
        """Resolve requested facility preferences against visible tennis names."""
        available = self._get_available_facility_names()
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

    def _get_available_facility_names(self) -> list[str]:
        """Return tennis names visible in the results bookmark list."""
        names: list[str] = []

        try:
            marker_names = self.driver.execute_script("""
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
        except WebDriverException:
            marker_names = []

        if isinstance(marker_names, (list, tuple)):
            names.extend(
                [name.strip() for name in marker_names if isinstance(name, str) and name.strip()]
            )

        try:
            favorites = self.driver.execute_script("return window.jsFav || []")
        except WebDriverException:
            favorites = []
        if isinstance(favorites, (list, tuple)):
            for name in favorites:
                if isinstance(name, str):
                    cleaned = name.strip()
                    if cleaned:
                        names.append(cleaned)

        try:
            elements = self.driver.find_elements(By.CSS_SELECTOR, ".tennisName")
            names.extend([element.text.strip() for element in elements if element.text])
        except WebDriverException:
            pass

        try:
            elements = self.driver.find_elements(By.CSS_SELECTOR, "#bookmarkList .tennis-label")
            names.extend([element.text.strip() for element in elements if element.text])
        except WebDriverException:
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
        try:
            elements = self.driver.find_elements(By.CSS_SELECTOR, "input[name='selCoating']")
            values = [element.get_attribute("value") for element in elements if element]
            return [value for value in values if value]
        except WebDriverException:
            return []

    def _fetch_availability_html(
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
                li_token, li_token_code = self._ensure_valid_li_antibot_tokens()
                response = self.driver.execute_async_script(
                    """
                    const callback = arguments[arguments.length - 1];
                    const hourRange = arguments[0];
                    const whenValue = arguments[1];
                    const facilityName = arguments[2];
                    const selInOut = arguments[3] || [];
                    const selCoating = arguments[4] || [];
                    const captchaRequestId = arguments[5];
                    const liToken = arguments[6] || "";
                    const liTokenCode = arguments[7] || "";
                    const ajaxUrl = arguments[8];
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

                    fetch(ajaxUrl, {
                        method: "POST",
                        headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8" },
                        body: params.toString(),
                    })
                        .then((response) => response.text())
                        .then((text) => callback({ ok: true, text }))
                        .catch((error) => callback({ ok: false, error: String(error) }));
                    """,
                    hour_range,
                    when_value,
                    facility_name,
                    sel_in_out,
                    sel_coating,
                    current_captcha_request_id,
                    li_token,
                    li_token_code,
                    ajax_url,
                )
                if not response or not response.get("ok"):
                    logger.debug("Failed to fetch availability for %s: %s", facility_name, response)
                    return None, current_captcha_request_id

                html = response.get("text")
                if attempt == 0 and self._looks_like_captcha_html(html):
                    logger.info(
                        "Availability response indicates CAPTCHA; attempting solve before retry"
                    )
                    if not self._solve_captcha_if_present():
                        logger.warning(
                            "CAPTCHA solve failed during availability fetch for %s",
                            facility_name,
                        )
                        return None, current_captcha_request_id
                    refreshed_id = self._get_captcha_request_id()
                    if refreshed_id:
                        current_captcha_request_id = refreshed_id
                    continue
                return html, current_captcha_request_id
            return None, current_captcha_request_id
        except WebDriverException as e:
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
            except WebDriverException:
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
            except NoSuchElementException:
                continue
            except WebDriverException:
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

    def _submit_reservation_form(
        self,
        slot: CourtSlot,
        captcha_request_id: Optional[str],
    ) -> None:
        """Submit the reservation form using slot identifiers."""
        reservation_start = slot.reservation_start or slot.date
        reservation_end = slot.reservation_end or slot.date

        date_deb = reservation_start.strftime("%Y/%m/%d %H:%M:%S")
        date_fin = reservation_end.strftime("%Y/%m/%d %H:%M:%S")
        action_url = urljoin(
            self.search_url,
            "Portal.jsp?page=reservation&view=reservation_creneau",
        )

        try:
            self.driver.execute_script(
                """
                const equipmentId = arguments[0];
                const courtId = arguments[1];
                const dateDeb = arguments[2];
                const dateFin = arguments[3];
                const captchaRequestId = arguments[4];
                const actionUrl = arguments[5];
                const liTokenInput = document.getElementById('li-antibot-token')
                    || document.querySelector("input[name='li-antibot-token']");
                const liTokenCodeInput = document.getElementById('li-antibot-token-code')
                    || document.querySelector("input[name='li-antibot-token-code']");
                const liToken = liTokenInput ? liTokenInput.value : "";
                const liTokenCode = liTokenCodeInput ? liTokenCodeInput.value : "";

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
                setInput("li-antibot-token", liToken);
                setInput("li-antibot-token-code", liTokenCode);
                if (captchaRequestId) {
                    setInput("captchaRequestId", captchaRequestId);
                }

                form.submit();
                """,
                slot.equipment_id,
                slot.court_id,
                date_deb,
                date_fin,
                captcha_request_id,
                action_url,
            )
        except WebDriverException as e:
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

    def _set_time_range(self, time_start: str, time_end: str) -> None:
        """Set time range filters if available."""
        try:
            start_field = self.driver.find_element(By.ID, "hourStart")
            start_field.clear()
            start_field.send_keys(time_start)

            end_field = self.driver.find_element(By.ID, "hourEnd")
            end_field.clear()
            end_field.send_keys(time_end)
        except NoSuchElementException:
            logger.debug("Time range fields not found, skipping")

    def _set_court_type(self, court_type: CourtType) -> None:
        """Set court type filter if available."""
        if court_type == CourtType.ANY:
            return

        try:
            # Look for court type checkbox/radio
            type_value = "couvert" if court_type == CourtType.INDOOR else "decouvert"
            selector = f"input[value='{type_value}']"
            checkbox = self.driver.find_element(By.CSS_SELECTOR, selector)
            if not checkbox.is_selected():
                checkbox.click()
        except NoSuchElementException:
            logger.debug("Court type filter not found, skipping")

    def _parse_facility_results(
        self,
        facility_code: str,
        target_date: datetime,
        request: BookingRequest,
    ) -> list[CourtSlot]:
        """Parse search results for a specific facility."""
        slots: list[CourtSlot] = []
        try:
            # Look for facility section in results
            facility_section = self.driver.find_element(
                By.CSS_SELECTOR, f"[data-facility='{facility_code}']"
            )

            # Find available time slots
            time_slots = facility_section.find_elements(
                By.CSS_SELECTOR,
                ".time-slot.available, .court-available, .buttonAllOk, "
                "button.buttonAllOk, a.buttonAllOk, input.buttonAllOk, "
                "[equipmentid], [data-equipment-id], [data-equipmentid]",
            )

            for slot_elem in time_slots:
                slot = self._parse_slot_element(slot_elem, facility_code, target_date, request)
                if (
                    slot
                    and request.is_time_in_range(slot.time_start)
                    and self._slot_matches_request(slot, request)
                ):
                    slots.append(slot)

        except NoSuchElementException:
            logger.debug(f"No results for facility {facility_code}")

        return slots

    def _parse_all_results(
        self,
        target_date: datetime,
        request: BookingRequest,
    ) -> list[CourtSlot]:
        """Parse all available slots from search results."""
        slots: list[CourtSlot] = []
        try:
            available_elements = self.driver.find_elements(
                By.CSS_SELECTOR,
                ".time-slot.available, .court-available, .buttonAllOk, "
                "button.buttonAllOk, a.buttonAllOk, input.buttonAllOk, "
                "[equipmentid], [data-equipment-id], [data-equipmentid]",
            )

            for elem in available_elements:
                slot = self._parse_slot_element(elem, "", target_date, request)
                if (
                    slot
                    and request.is_time_in_range(slot.time_start)
                    and self._slot_matches_request(slot, request)
                ):
                    slots.append(slot)

        except NoSuchElementException:
            logger.debug("No available slots found")

        return slots

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
            except WebDriverException:
                value = None
            if value:
                candidates.append(value)

        try:
            text_value = element.text
        except WebDriverException:
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
            except NoSuchElementException:
                court_container = None
            except WebDriverException:
                court_container = None

            if court_container:
                try:
                    court_span = court_container.find_element(By.CSS_SELECTOR, "span.court")
                    court_text = (court_span.text or "").strip()
                except NoSuchElementException:
                    court_text = ""
                except WebDriverException:
                    court_text = ""

                try:
                    price_desc_elem = court_container.find_element(
                        By.CSS_SELECTOR, ".price-description"
                    )
                    price_description = (price_desc_elem.text or "").strip()
                except NoSuchElementException:
                    price_description = ""
                except WebDriverException:
                    price_description = ""

                try:
                    price_elem = court_container.find_element(By.CSS_SELECTOR, ".price")
                    price_text = (price_elem.text or "").strip()
                except NoSuchElementException:
                    price_text = ""
                except WebDriverException:
                    price_text = ""

            if not court_text:
                try:
                    court_text = (element.text or "").strip()
                except WebDriverException:
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

    def book_court(
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

            wait = WebDriverWait(self.driver, BOOKING_WAIT_TIMEOUT)
            captcha_request_id = slot.captcha_request_id
            if not captcha_request_id:
                current_url = self.driver.current_url or ""
                if SEARCH_RESULTS_QUERY in current_url or "page=recherche" in current_url:
                    captcha_request_id = self._get_captcha_request_id()

            if not captcha_request_id:
                target_date = slot.reservation_start or slot.date
                facility_names = [slot.facility_name] if slot.facility_name else None
                hour_range = self._format_hour_range(slot.time_start, slot.time_end)
                sel_in_out = self._get_indoor_outdoor_values(slot.court_type)
                captcha_request_id = self._ensure_search_results_page(
                    wait,
                    target_date=target_date,
                    facility_names=facility_names,
                    hour_range=hour_range,
                    sel_in_out=sel_in_out,
                )
            self._submit_reservation_form(slot, captcha_request_id)
            self._wait_for_booking_state(wait)
            self._solve_captcha_if_present(wait)

            self._handle_reservation_details(
                player_name=player_name,
                player_email=player_email,
                partner_name=partner_name,
                partner_email=partner_email,
                wait=wait,
            )
            self._solve_captcha_if_present(wait)

            if self._handle_payment_step(wait=wait):
                logger.debug("Payment step handled")
            self._solve_captcha_if_present(wait)

            # Confirm booking if confirmation button is present
            try:
                confirm_button = wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".confirm-booking, #confirmBooking")
                    )
                )
                confirm_button.click()
            except TimeoutException:
                logger.debug("Confirmation button not found after CAPTCHA")

            # Wait for confirmation
            time.sleep(2)

            # Extract confirmation ID
            confirmation_id = self._extract_confirmation_id()

            if confirmation_id:
                logger.info(f"Booking successful! Confirmation: {confirmation_id}")
                return BookingResult(
                    success=True,
                    confirmation_id=confirmation_id,
                    slot=slot,
                )
            else:
                # Check for success message without explicit ID
                if self._check_booking_success():
                    return BookingResult(
                        success=True,
                        confirmation_id="CONFIRMED",
                        slot=slot,
                    )
                return BookingResult(
                    success=False,
                    error_message="Booking confirmation not received",
                    slot=slot,
                )

        except TimeoutException:
            logger.error("Booking timeout - elements not found")
            return BookingResult(
                success=False,
                error_message="Booking page timeout",
                slot=slot,
            )
        except WebDriverException as e:
            logger.error(f"WebDriver error during booking: {e}")
            return BookingResult(
                success=False,
                error_message=str(e),
                slot=slot,
            )

    def _check_for_captcha(self) -> bool:
        """Check if CAPTCHA verification is present."""
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
            "#captcha",
            "#li-antibot",
            "#formCaptcha",
        ]
        for selector in captcha_selectors:
            try:
                self.driver.find_element(By.CSS_SELECTOR, selector)
                return True
            except NoSuchElementException:
                continue
        page_source = (self.driver.page_source or "").lower()
        if (
            "recaptcha/api.js?render=" in page_source
            or "grecaptcha.execute" in page_source
            or "data-sitekey" in page_source
            or "li_antibot.loadantibot" in page_source
        ):
            return True
        return False

    def _wait_for_booking_state(self, wait: Optional[WebDriverWait]) -> None:
        """Wait for the reservation flow to reach a CAPTCHA or booking step."""
        if wait is None:
            return

        try:
            wait.until(
                lambda driver: self._check_for_captcha()
                or self._is_reservation_details_page()
                or self._is_payment_page()
            )
        except TimeoutException:
            pass

    def _submit_captcha_form_if_present(self, wait: Optional[WebDriverWait] = None) -> bool:
        """Submit the CAPTCHA form if it is present."""
        try:
            form = self.driver.find_element(By.ID, "formCaptcha")
        except NoSuchElementException:
            return False
        except WebDriverException:
            return False

        submitted = False
        for selector in CAPTCHA_SUBMIT_SELECTORS:
            try:
                button = form.find_element(By.CSS_SELECTOR, selector)
                button.click()
                submitted = True
                break
            except NoSuchElementException:
                continue
            except WebDriverException:
                continue

        if not submitted:
            for xpath in CAPTCHA_SUBMIT_XPATHS:
                try:
                    button = form.find_element(By.XPATH, xpath)
                    button.click()
                    submitted = True
                    break
                except NoSuchElementException:
                    continue
                except WebDriverException:
                    continue

        if not submitted:
            try:
                self.driver.execute_script("arguments[0].submit();", form)
                submitted = True
            except WebDriverException:
                submitted = False

        if submitted and wait is not None:
            try:
                wait.until_not(EC.presence_of_element_located((By.ID, "formCaptcha")))
            except TimeoutException:
                pass

        return submitted

    def _normalize_label_text(self, value: str) -> str:
        """Normalize label text for matching form fields."""
        return _normalize_court_type_text(value or "")

    def _get_input_label_text(self, element) -> str:
        """Return the best-effort label text for an input element."""
        label_text = ""
        try:
            label_text = self.driver.execute_script(
                """
                const el = arguments[0];
                const group = el.closest('.form-group');
                if (!group) {
                    return '';
                }
                const label = group.querySelector('label');
                return label ? (label.textContent || '') : '';
                """,
                element,
            )
        except WebDriverException:
            label_text = ""

        if label_text:
            return str(label_text)

        for attr in ("aria-label", "placeholder", "title", "name"):
            try:
                label_text = element.get_attribute(attr) or ""
            except WebDriverException:
                label_text = ""
            if label_text:
                break

        return str(label_text or "")

    def _element_is_visible(self, element) -> bool:
        """Return True if a Selenium element is displayed."""
        try:
            return element.is_displayed()
        except WebDriverException:
            return False

    def _has_visible_inputs(self, name: str) -> bool:
        """Return True if any visible inputs exist for the given name."""
        try:
            elements = self.driver.find_elements(By.NAME, name)
        except WebDriverException:
            return False

        return any(self._element_is_visible(element) for element in elements)

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

    def _fill_player_inputs(
        self,
        name: str,
        first_name: str,
        last_name: str,
        email: Optional[str],
    ) -> bool:
        """Fill player fields (name/email) when present on the reservation form."""
        try:
            elements = self.driver.find_elements(By.NAME, name)
        except WebDriverException:
            return False

        if not elements:
            return False

        filled = False
        fallback_values = [value for value in (last_name, first_name) if value]
        fallback_index = 0

        for element in elements:
            if not self._element_is_visible(element):
                continue

            try:
                current_value = element.get_attribute("value") or ""
            except WebDriverException:
                current_value = ""
            if str(current_value).strip():
                continue

            label_text = self._normalize_label_text(self._get_input_label_text(element))
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
                element.clear()
                element.send_keys(target)
                filled = True
            except WebDriverException:
                continue

        return filled

    def _click_if_present(self, by: By, value: str) -> bool:
        """Click an element if it exists."""
        try:
            element = self.driver.find_element(by, value)
        except (NoSuchElementException, WebDriverException):
            return False

        if not self._element_is_visible(element):
            return False

        try:
            element.click()
            return True
        except WebDriverException:
            try:
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except WebDriverException:
                return False

    def _is_reservation_details_page(self) -> bool:
        """Return True if the reservation details form is present."""
        try:
            current_url = self.driver.current_url or ""
        except WebDriverException:
            current_url = ""

        if "view=reservation_creneau" in current_url:
            return True

        try:
            if self.driver.find_elements(By.ID, "submitControle"):
                return True
        except WebDriverException:
            return False

        return self._has_visible_inputs("player1") or self._has_visible_inputs("player")

    def _handle_reservation_details(
        self,
        player_name: Optional[str],
        player_email: Optional[str],
        partner_name: Optional[str],
        partner_email: Optional[str],
        wait: Optional[WebDriverWait] = None,
    ) -> bool:
        """Fill reservation details and advance to the payment step when possible."""
        if not self._is_reservation_details_page():
            return False

        first_name, last_name = self._split_full_name(player_name)
        filled_primary = False
        if self._has_visible_inputs("player1"):
            filled_primary = self._fill_player_inputs(
                "player1", first_name, last_name, player_email
            )
        elif self._has_visible_inputs("player"):
            filled_primary = self._fill_player_inputs("player", first_name, last_name, player_email)

        if partner_name:
            if not self._has_visible_inputs("player2"):
                self._click_if_present(By.CSS_SELECTOR, ".addPlayer")
                time.sleep(0.5)
            partner_first, partner_last = self._split_full_name(partner_name)
            self._fill_player_inputs("player2", partner_first, partner_last, partner_email)

        if self._click_if_present(By.ID, "submitControle"):
            if wait is not None:
                try:
                    wait.until(lambda driver: "view=methode_paiement" in (driver.current_url or ""))
                except TimeoutException:
                    pass
            return True

        return filled_primary

    def _is_payment_page(self) -> bool:
        """Return True if the payment selection form is present."""
        try:
            current_url = self.driver.current_url or ""
        except WebDriverException:
            current_url = ""

        if "view=methode_paiement" in current_url:
            return True

        try:
            if self.driver.find_elements(By.ID, "order_select_payment_form"):
                return True
            if self.driver.find_elements(By.ID, "paymentMode"):
                return True
        except WebDriverException:
            return False

        return False

    def _handle_payment_step(self, wait: Optional[WebDriverWait] = None) -> bool:
        """Select carnet payment on the payment page and advance."""
        if not self._is_payment_page():
            return False

        selected = self._select_carnet_payment_if_present()
        if selected:
            if not self._click_if_present(By.ID, "submit"):
                self._click_if_present(By.ID, "envoyer")
            if wait is not None:
                try:
                    wait.until(
                        lambda driver: "view=methode_paiement" not in (driver.current_url or "")
                    )
                except TimeoutException:
                    pass
        return selected

    def _select_carnet_payment_if_present(self) -> bool:
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
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    try:
                        if hasattr(element, "is_selected") and element.is_selected():
                            return True
                        element.click()
                        return True
                    except WebDriverException:
                        continue

            label_xpath = (
                "//label[contains(translate(normalize-space(.), "
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'carnet')]"
            )
            labels = self.driver.find_elements(By.XPATH, label_xpath)
            for label in labels:
                try:
                    label.click()
                    return True
                except WebDriverException:
                    continue

            price_selectors = [
                ".price-item.option",
                ".priceTable .option",
                ".price-item",
            ]
            for selector in price_selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    try:
                        text = (element.text or "").strip().lower()
                    except WebDriverException:
                        text = ""
                    if "carnet" in text or "ticket" in text:
                        element.click()
                        return True

            selects = self.driver.find_elements(By.TAG_NAME, "select")
            for select in selects:
                try:
                    options = select.find_elements(By.TAG_NAME, "option")
                except WebDriverException:
                    continue
                for option in options:
                    text = (option.text or "").strip().lower()
                    value = (option.get_attribute("value") or "").strip().lower()
                    if "carnet" in text or "carnet" in value:
                        option.click()
                        return True

            return False
        except WebDriverException as e:
            logger.debug(f"Failed to select carnet payment option: {e}")
            return False

    def _extract_confirmation_id(self) -> Optional[str]:
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
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    text = elem.text or elem.get_attribute("data-confirmation-id")
                    if text:
                        return text.strip()
                except NoSuchElementException:
                    continue
            return None
        except WebDriverException:
            return None

    def _check_booking_success(self) -> bool:
        """Check for booking success indicators."""
        success_indicators = [
            "réservation confirmée",
            "booking confirmed",
            "succès",
            "success",
        ]
        page_text = self.driver.page_source.lower()
        return any(indicator in page_text for indicator in success_indicators)

    def logout(self) -> bool:
        """Log out of the Paris Tennis website."""
        try:
            logout_link = None
            for selector in PARIS_TENNIS_LOGOUT_SELECTORS:
                try:
                    logout_link = self.driver.find_element(By.CSS_SELECTOR, selector)
                    break
                except NoSuchElementException:
                    continue

            if logout_link is None:
                logout_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "Déconnexion")

            logout_link.click()
            self._logged_in = False
            logger.info("Logged out successfully")
            return True
        except NoSuchElementException:
            logger.warning("Logout link not found")
            return False


def create_paris_tennis_session():
    """
    Context manager for Paris Tennis service with browser session.

    Usage:
        with create_paris_tennis_session() as service:
            if service.login(email, password):
                slots = service.search_available_courts(request)
    """
    return _ParisTennisSession()


class _ParisTennisSession:
    """Context manager wrapper for ParisTennisService with browser."""

    def __enter__(self) -> ParisTennisService:
        self._browser_context = browser_session()
        driver = self._browser_context.__enter__()
        self._service = ParisTennisService(driver=driver)
        return self._service

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._browser_context.__exit__(exc_type, exc_val, exc_tb)
