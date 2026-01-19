"""Paris Tennis website automation service.

This module provides automation for interacting with the Paris Tennis
booking website (tennis.paris.fr) using Selenium WebDriver.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

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
from src.models.booking_request import BookingRequest, CourtType
from src.utils.browser import browser_session

logger = logging.getLogger(__name__)

# Default timeouts
DEFAULT_WAIT_TIMEOUT = 10
BOOKING_WAIT_TIMEOUT = 30


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

    def __init__(self, driver: Optional[WebDriver] = None):
        """
        Initialize the Paris Tennis service.

        Args:
            driver: Optional WebDriver instance. If not provided,
                   a new browser session will be created for each operation.
        """
        self._driver = driver
        self._logged_in = False
        self.base_url = settings.paris_tennis.base_url
        self.login_url = settings.paris_tennis.login_url
        self.search_url = settings.paris_tennis.search_url

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

            # Wait for and fill email field
            email_field = wait.until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            email_field.clear()
            email_field.send_keys(email)

            # Fill password field
            password_field = self.driver.find_element(By.ID, "password")
            password_field.clear()
            password_field.send_keys(password)

            # Click login button
            login_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"
            )
            login_button.click()

            # Wait for successful login (check for user menu or redirect)
            time.sleep(2)  # Brief wait for page transition

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
            # Look for common indicators of being logged in
            # This may need adjustment based on actual website structure
            indicators = [
                (By.CSS_SELECTOR, ".user-menu"),
                (By.CSS_SELECTOR, ".logout"),
                (By.LINK_TEXT, "Déconnexion"),
                (By.PARTIAL_LINK_TEXT, "Mon compte"),
            ]
            for by, value in indicators:
                try:
                    self.driver.find_element(by, value)
                    return True
                except NoSuchElementException:
                    continue
            return False
        except WebDriverException:
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

            # Navigate to search page
            self.driver.get(self.search_url)
            wait = WebDriverWait(self.driver, DEFAULT_WAIT_TIMEOUT)

            # Set search date
            date_field = wait.until(
                EC.presence_of_element_located((By.ID, "date"))
            )
            date_str = target_date.strftime("%d/%m/%Y")
            date_field.clear()
            date_field.send_keys(date_str)

            # Set time range if fields exist
            self._set_time_range(request.time_start, request.time_end)

            # Set court type preference
            self._set_court_type(request.court_type)

            # Submit search
            search_button = self.driver.find_element(
                By.CSS_SELECTOR, "button[type='submit'], input[type='submit']"
            )
            search_button.click()

            # Wait for results
            time.sleep(2)

            # Parse results based on facility preferences
            for facility_code in request.facility_preferences:
                slots = self._parse_facility_results(
                    facility_code, target_date, request
                )
                available_slots.extend(slots)

            # If no specific facilities, get all available
            if not request.facility_preferences:
                available_slots = self._parse_all_results(target_date, request)

            logger.info(f"Found {len(available_slots)} available slots")
            return available_slots

        except TimeoutException:
            logger.error("Search page timeout")
            return []
        except WebDriverException as e:
            logger.error(f"WebDriver error during search: {e}")
            return []

    def _get_next_booking_date(self, day_of_week: int) -> datetime:
        """Get the next date for the given day of week."""
        today = datetime.now()
        days_ahead = day_of_week - today.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return today + timedelta(days=days_ahead)

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
                By.CSS_SELECTOR, ".time-slot.available"
            )

            for slot_elem in time_slots:
                slot = self._parse_slot_element(
                    slot_elem, facility_code, target_date, request
                )
                if slot and request.is_time_in_range(slot.time_start):
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
                By.CSS_SELECTOR, ".time-slot.available, .court-available"
            )

            for elem in available_elements:
                slot = self._parse_slot_element(elem, "", target_date, request)
                if slot and request.is_time_in_range(slot.time_start):
                    slots.append(slot)

        except NoSuchElementException:
            logger.debug("No available slots found")

        return slots

    def _parse_slot_element(
        self,
        element,
        facility_code: str,
        target_date: datetime,
        request: BookingRequest,
    ) -> Optional[CourtSlot]:
        """Parse a single slot element into CourtSlot."""
        try:
            time_start = element.get_attribute("data-start") or ""
            time_end = element.get_attribute("data-end") or ""
            court_number = element.get_attribute("data-court") or ""
            facility_name = element.get_attribute("data-facility-name") or ""

            if not facility_code:
                facility_code = element.get_attribute("data-facility") or ""

            return CourtSlot(
                facility_name=facility_name,
                facility_code=facility_code,
                court_number=court_number,
                date=target_date,
                time_start=time_start,
                time_end=time_end,
                court_type=request.court_type,
            )
        except Exception as e:
            logger.debug(f"Failed to parse slot element: {e}")
            return None

    def book_court(
        self,
        slot: CourtSlot,
        partner_name: Optional[str] = None,
    ) -> BookingResult:
        """
        Book a specific court slot.

        Args:
            slot: The CourtSlot to book
            partner_name: Name of the playing partner

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

            # Click on the slot to start booking
            # This will need to be adapted to actual website structure
            slot_selector = (
                f"[data-facility='{slot.facility_code}']"
                f"[data-court='{slot.court_number}']"
                f"[data-start='{slot.time_start}']"
            )
            slot_element = self.driver.find_element(By.CSS_SELECTOR, slot_selector)
            slot_element.click()

            wait = WebDriverWait(self.driver, BOOKING_WAIT_TIMEOUT)

            # Wait for booking form/modal
            time.sleep(1)

            # Fill partner name if required
            if partner_name:
                try:
                    partner_field = wait.until(
                        EC.presence_of_element_located((By.ID, "partnerName"))
                    )
                    partner_field.clear()
                    partner_field.send_keys(partner_name)
                except TimeoutException:
                    logger.debug("Partner name field not found")

            # Handle CAPTCHA if present
            # This will be handled by the captcha_solver service
            captcha_present = self._check_for_captcha()
            if captcha_present:
                logger.info("CAPTCHA detected - needs solving")
                return BookingResult(
                    success=False,
                    error_message="CAPTCHA verification required",
                    slot=slot,
                )

            # Confirm booking
            confirm_button = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".confirm-booking, #confirmBooking")
                )
            )
            confirm_button.click()

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
        ]
        for selector in captcha_selectors:
            try:
                self.driver.find_element(By.CSS_SELECTOR, selector)
                return True
            except NoSuchElementException:
                continue
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
