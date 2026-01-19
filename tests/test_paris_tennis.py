"""Tests for the Paris Tennis service."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.models.booking_request import BookingRequest, CourtType, DayOfWeek
from src.services.paris_tennis import (
    BookingResult,
    CourtSlot,
    ParisTennisService,
    create_paris_tennis_session,
)
from src.utils.timezone import now_paris, PARIS_TZ


@pytest.fixture
def mock_driver():
    """Create a mock WebDriver."""
    driver = MagicMock()
    driver.page_source = ""
    return driver


@pytest.fixture
def service(mock_driver):
    """Create a ParisTennisService with mock driver."""
    return ParisTennisService(driver=mock_driver)


@pytest.fixture
def sample_booking_request():
    """Create a sample booking request."""
    return BookingRequest(
        id="req-1",
        user_id="user-1",
        day_of_week=DayOfWeek.MONDAY,
        time_start="18:00",
        time_end="20:00",
        facility_preferences=["facility-1", "facility-2"],
        court_type=CourtType.INDOOR,
        partner_name="Partner Name",
        partner_email="partner@example.com",
        active=True,
    )


@pytest.fixture
def sample_court_slot():
    """Create a sample court slot."""
    return CourtSlot(
        facility_name="Tennis Club Paris",
        facility_code="facility-1",
        court_number="3",
        date=datetime.now() + timedelta(days=1),
        time_start="18:00",
        time_end="19:00",
        court_type=CourtType.INDOOR,
        price=10.0,
    )


class TestCourtSlot:
    """Tests for CourtSlot dataclass."""

    def test_court_slot_creation(self, sample_court_slot):
        """Test CourtSlot can be created with all fields."""
        assert sample_court_slot.facility_name == "Tennis Club Paris"
        assert sample_court_slot.facility_code == "facility-1"
        assert sample_court_slot.court_number == "3"
        assert sample_court_slot.time_start == "18:00"
        assert sample_court_slot.time_end == "19:00"
        assert sample_court_slot.court_type == CourtType.INDOOR
        assert sample_court_slot.price == 10.0

    def test_court_slot_without_price(self):
        """Test CourtSlot can be created without price."""
        slot = CourtSlot(
            facility_name="Test",
            facility_code="test-1",
            court_number="1",
            date=datetime.now(),
            time_start="10:00",
            time_end="11:00",
            court_type=CourtType.ANY,
        )
        assert slot.price is None


class TestBookingResult:
    """Tests for BookingResult dataclass."""

    def test_successful_booking_result(self, sample_court_slot):
        """Test successful BookingResult."""
        result = BookingResult(
            success=True,
            confirmation_id="CONF-123",
            slot=sample_court_slot,
        )
        assert result.success is True
        assert result.confirmation_id == "CONF-123"
        assert result.error_message is None
        assert result.slot == sample_court_slot

    def test_failed_booking_result(self, sample_court_slot):
        """Test failed BookingResult."""
        result = BookingResult(
            success=False,
            error_message="Court no longer available",
            slot=sample_court_slot,
        )
        assert result.success is False
        assert result.confirmation_id is None
        assert result.error_message == "Court no longer available"


class TestParisTennisService:
    """Tests for ParisTennisService."""

    def test_service_initialization(self, mock_driver):
        """Test service initializes with driver."""
        service = ParisTennisService(driver=mock_driver)
        assert service.driver == mock_driver
        assert service._logged_in is False

    def test_service_without_driver_raises(self):
        """Test service without driver raises on access."""
        service = ParisTennisService()
        with pytest.raises(RuntimeError, match="No WebDriver available"):
            _ = service.driver

    def test_login_success(self, service, mock_driver):
        """Test successful login."""
        # Setup mock elements
        mock_email = MagicMock()
        mock_password = MagicMock()
        mock_button = MagicMock()
        mock_user_menu = MagicMock()

        # Configure find_element to return appropriate mocks
        def find_element_side_effect(by, value):
            if value == "username":
                return mock_email
            elif value == "password":
                return mock_password
            elif ".user-menu" in value:
                return mock_user_menu
            elif "submit" in value:
                return mock_button
            raise Exception(f"Unexpected element: {value}")

        mock_driver.find_element.side_effect = find_element_side_effect

        # Mock WebDriverWait
        with patch("src.services.paris_tennis.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.return_value = mock_email

            result = service.login("test@example.com", "password123")

            # Verify login attempted
            mock_driver.get.assert_called_once()
            assert service._logged_in is True
            assert result is True

    def test_login_element_not_found(self, service, mock_driver):
        """Test login fails when elements not found."""
        from selenium.common.exceptions import TimeoutException

        with patch("src.services.paris_tennis.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.side_effect = TimeoutException()

            result = service.login("test@example.com", "password")

            assert result is False
            assert service._logged_in is False

    def test_get_next_booking_date_future(self, service):
        """Test getting next booking date when day is in future."""
        today = now_paris()
        # Get a day that's definitely in the future this week
        future_day = (today.weekday() + 3) % 7
        result = service._get_next_booking_date(future_day)

        assert result.weekday() == future_day
        assert result.date() > today.date() or result.date() == today.date()

    def test_get_next_booking_date_past(self, service):
        """Test getting next booking date when day has passed."""
        today = now_paris()
        # Get yesterday's day of week
        past_day = (today.weekday() - 1) % 7
        result = service._get_next_booking_date(past_day)

        # Should be next week
        assert result.weekday() == past_day
        assert result.date() > today.date()

    def test_get_next_booking_date_uses_paris_timezone(self, service):
        """Test that _get_next_booking_date uses Paris timezone."""
        with patch("src.services.paris_tennis.now_paris") as mock_now:
            # Simulate a specific Paris time
            mock_paris_time = datetime(2024, 3, 15, 10, 0, 0, tzinfo=PARIS_TZ)  # Friday
            mock_now.return_value = mock_paris_time

            # Request booking for Monday (day_of_week=0)
            result = service._get_next_booking_date(0)

            # Should be Monday, March 18, 2024
            assert result.weekday() == 0
            assert result.date() == datetime(2024, 3, 18).date()
            mock_now.assert_called_once()

    def test_is_logged_in_true(self, service, mock_driver):
        """Test _is_logged_in returns True when user menu found."""
        mock_driver.find_element.return_value = MagicMock()
        assert service._is_logged_in() is True

    def test_is_logged_in_false(self, service, mock_driver):
        """Test _is_logged_in returns False when no indicators found."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()
        assert service._is_logged_in() is False

    def test_check_for_captcha_found(self, service, mock_driver):
        """Test CAPTCHA detection when present."""
        mock_driver.find_element.return_value = MagicMock()
        assert service._check_for_captcha() is True

    def test_check_for_captcha_not_found(self, service, mock_driver):
        """Test CAPTCHA detection when not present."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()
        assert service._check_for_captcha() is False

    def test_check_booking_success_true(self, service, mock_driver):
        """Test booking success detection when confirmed."""
        mock_driver.page_source = "Votre réservation confirmée avec succès"
        assert service._check_booking_success() is True

    def test_check_booking_success_false(self, service, mock_driver):
        """Test booking success detection when not confirmed."""
        mock_driver.page_source = "Erreur lors de la réservation"
        assert service._check_booking_success() is False

    def test_book_court_not_logged_in(self, service, sample_court_slot):
        """Test booking fails when not logged in."""
        result = service.book_court(sample_court_slot)

        assert result.success is False
        assert result.error_message == "Not logged in"

    def test_search_available_courts_empty(
        self, service, mock_driver, sample_booking_request
    ):
        """Test search returns empty list when no results."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()
        mock_driver.find_elements.return_value = []

        with patch("src.services.paris_tennis.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.return_value = MagicMock()

            result = service.search_available_courts(sample_booking_request)

            assert result == []

    def test_logout_success(self, service, mock_driver):
        """Test successful logout."""
        service._logged_in = True
        mock_link = MagicMock()
        mock_driver.find_element.return_value = mock_link

        result = service.logout()

        assert result is True
        assert service._logged_in is False
        mock_link.click.assert_called_once()

    def test_logout_link_not_found(self, service, mock_driver):
        """Test logout when link not found."""
        from selenium.common.exceptions import NoSuchElementException

        service._logged_in = True
        mock_driver.find_element.side_effect = NoSuchElementException()

        result = service.logout()

        assert result is False
        # _logged_in should still be True since logout failed
        assert service._logged_in is True


class TestCreateParisTennisSession:
    """Tests for create_paris_tennis_session context manager."""

    def test_session_creates_service(self):
        """Test session context manager creates service."""
        with patch("src.services.paris_tennis.browser_session") as mock_browser:
            mock_driver = MagicMock()
            mock_browser.return_value.__enter__.return_value = mock_driver

            with create_paris_tennis_session() as service:
                assert isinstance(service, ParisTennisService)
                assert service._driver == mock_driver

    def test_session_closes_browser(self):
        """Test session context manager closes browser."""
        with patch("src.services.paris_tennis.browser_session") as mock_browser:
            mock_context = MagicMock()
            mock_browser.return_value = mock_context
            mock_context.__enter__.return_value = MagicMock()

            with create_paris_tennis_session():
                pass

            mock_context.__exit__.assert_called_once()
