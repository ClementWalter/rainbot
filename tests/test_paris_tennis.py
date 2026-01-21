"""Tests for the Paris Tennis service."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import urljoin

import pytest
from selenium.webdriver.common.by import By

from src.models.booking_request import BookingRequest, CourtType, DayOfWeek
from src.services.paris_tennis import (
    BookingResult,
    CourtSlot,
    ParisTennisService,
    create_paris_tennis_session,
)
from src.utils.timezone import PARIS_TZ, now_paris


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
        from selenium.common.exceptions import NoSuchElementException, TimeoutException

        with patch("src.services.paris_tennis.WebDriverWait") as mock_wait:
            mock_wait.return_value.until.side_effect = TimeoutException()
            mock_driver.find_element.side_effect = NoSuchElementException()

            result = service.login("test@example.com", "password")

            assert result is False
            assert service._logged_in is False

    def test_navigate_to_mon_paris_uses_href(self, service, mock_driver):
        """Test Mon Paris navigation uses link href when available."""
        element = MagicMock()
        element.get_attribute.return_value = "https://moncompte.paris.fr/moncompte/"
        mock_driver.find_element.return_value = element

        result = service._navigate_to_mon_paris(MagicMock())

        assert result is True
        mock_driver.get.assert_called_once_with("https://moncompte.paris.fr/moncompte/")

    def test_get_next_booking_date_future(self, service):
        """Test getting next booking date when day is in future this week."""
        today = now_paris()
        # Get a day that's definitely in the future this week
        future_day = (today.weekday() + 3) % 7
        result = service._get_next_booking_date(future_day)

        assert result.weekday() == future_day
        # PRD requires "Future dates only: Cannot book same-day courts"
        assert result.date() > today.date()

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

    def test_sort_available_slots_respects_facility_order_and_time(self, service):
        """Test slot sorting respects facility preference order and earliest time."""
        request = BookingRequest(
            id="req-1",
            user_id="user-1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="22:00",
            facility_preferences=["FAC2", "FAC1"],
            court_type=CourtType.ANY,
        )

        slots = [
            CourtSlot(
                facility_name="Facility 1",
                facility_code="FAC1",
                court_number="1",
                date=now_paris(),
                time_start="19:00",
                time_end="20:00",
                court_type=CourtType.ANY,
            ),
            CourtSlot(
                facility_name="Facility 2",
                facility_code="FAC2",
                court_number="2",
                date=now_paris(),
                time_start="10:00",
                time_end="11:00",
                court_type=CourtType.ANY,
            ),
            CourtSlot(
                facility_name="Facility 2",
                facility_code="FAC2",
                court_number="3",
                date=now_paris(),
                time_start="9:00",
                time_end="10:00",
                court_type=CourtType.ANY,
            ),
            CourtSlot(
                facility_name="Facility 1",
                facility_code="FAC1",
                court_number="4",
                date=now_paris(),
                time_start="18:00",
                time_end="19:00",
                court_type=CourtType.ANY,
            ),
        ]

        sorted_slots = service._sort_available_slots(slots, request)

        assert [(slot.facility_code, slot.time_start) for slot in sorted_slots] == [
            ("FAC2", "9:00"),
            ("FAC2", "10:00"),
            ("FAC1", "18:00"),
            ("FAC1", "19:00"),
        ]

    def test_sort_available_slots_without_preferences_sorts_by_time(self, service):
        """Test slot sorting falls back to earliest time when no preferences exist."""
        request = BookingRequest(
            id="req-1",
            user_id="user-1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="22:00",
            facility_preferences=[],
            court_type=CourtType.ANY,
        )

        slots = [
            CourtSlot(
                facility_name="Facility 1",
                facility_code="FAC1",
                court_number="1",
                date=now_paris(),
                time_start="19:00",
                time_end="20:00",
                court_type=CourtType.ANY,
            ),
            CourtSlot(
                facility_name="Facility 2",
                facility_code="FAC2",
                court_number="2",
                date=now_paris(),
                time_start="9:00",
                time_end="10:00",
                court_type=CourtType.ANY,
            ),
            CourtSlot(
                facility_name="Facility 3",
                facility_code="FAC3",
                court_number="3",
                date=now_paris(),
                time_start="12:00",
                time_end="13:00",
                court_type=CourtType.ANY,
            ),
        ]

        sorted_slots = service._sort_available_slots(slots, request)

        assert [slot.time_start for slot in sorted_slots] == [
            "9:00",
            "12:00",
            "19:00",
        ]

    def test_sort_available_slots_respects_preference_codes_as_substrings(self, service):
        """Test slot sorting respects preference codes embedded in facility names."""
        request = BookingRequest(
            id="req-1",
            user_id="user-1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="22:00",
            facility_preferences=["FAC001", "FAC002"],
            court_type=CourtType.ANY,
        )

        slots = [
            CourtSlot(
                facility_name="Tennis Center FAC002",
                facility_code="tenniscenterfac002",
                court_number="1",
                date=now_paris(),
                time_start="09:00",
                time_end="10:00",
                court_type=CourtType.ANY,
            ),
            CourtSlot(
                facility_name="Tennis Center FAC001",
                facility_code="tenniscenterfac001",
                court_number="2",
                date=now_paris(),
                time_start="18:00",
                time_end="19:00",
                court_type=CourtType.ANY,
            ),
        ]

        sorted_slots = service._sort_available_slots(slots, request)

        assert [slot.facility_code for slot in sorted_slots] == [
            "tenniscenterfac001",
            "tenniscenterfac002",
        ]

    def test_parse_court_number_extracts_numeric(self, service):
        """Test court number parsing extracts digits from common labels."""
        assert service._parse_court_number("Court n° 3") == "3"
        assert service._parse_court_number("court no 12") == "12"
        assert service._parse_court_number("Court 7") == "7"
        assert service._parse_court_number("Court Central") == "Court Central"

    def test_submit_reservation_form_uses_absolute_action_url(self, service, mock_driver):
        """Ensure reservation form uses an absolute action URL."""
        start_time = now_paris()
        slot = CourtSlot(
            facility_name="Facility",
            facility_code="FAC1",
            court_number="1",
            date=start_time,
            time_start="08:00",
            time_end="09:00",
            court_type=CourtType.ANY,
            equipment_id="equip-1",
            court_id="court-1",
            reservation_start=start_time,
            reservation_end=start_time + timedelta(hours=1),
        )

        service._submit_reservation_form(slot, captcha_request_id="captcha-1")

        args, _ = mock_driver.execute_script.call_args
        assert args[-1] == urljoin(
            service.search_url,
            "Portal.jsp?page=reservation&view=reservation_captcha",
        )

    def test_parse_slot_element_detects_court_type_from_attributes(
        self,
        service,
        sample_booking_request,
    ):
        """Test slot parsing detects court type from element attributes."""
        from selenium.common.exceptions import NoSuchElementException

        element = MagicMock()

        def get_attribute_side_effect(name):
            return {
                "data-start": "18:00",
                "data-end": "19:00",
                "data-court": "3",
                "data-facility-name": "Tennis Club Paris",
                "data-facility-address": "123 Rue de Tennis",
                "data-facility": "facility-1",
                "data-court-type": "outdoor",
            }.get(name, "")

        element.get_attribute.side_effect = get_attribute_side_effect
        element.text = ""
        element.find_element.side_effect = NoSuchElementException()

        slot = service._parse_slot_element(
            element,
            "facility-1",
            now_paris(),
            sample_booking_request,
        )

        assert slot is not None
        assert slot.court_type == CourtType.OUTDOOR

    def test_parse_slot_element_parses_dom_booking_identifiers(
        self,
        service,
        sample_booking_request,
    ):
        """Test slot parsing extracts booking identifiers from DOM attributes."""
        from selenium.common.exceptions import NoSuchElementException

        element = MagicMock()
        attrs = {
            "data-facility-name": "Tennis Club Paris",
            "data-facility-address": "123 Rue de Tennis",
            "data-facility": "facility-1",
            "data-court": "3",
            "equipmentid": "E123",
            "courtid": "C456",
            "datedeb": "2025/01/15 18:00:00",
            "datefin": "2025/01/15 19:00:00",
            "typeprice": "Decouvert",
            "indooroutdoor": "Exterieur",
            "price": "10",
        }

        def get_attribute_side_effect(name):
            return attrs.get(name.lower(), "")

        element.get_attribute.side_effect = get_attribute_side_effect
        element.text = ""
        element.find_element.side_effect = NoSuchElementException()

        slot = service._parse_slot_element(
            element,
            "facility-1",
            now_paris(),
            sample_booking_request,
        )

        assert slot is not None
        assert slot.equipment_id == "E123"
        assert slot.court_id == "C456"
        assert slot.time_start == "18:00"
        assert slot.time_end == "19:00"
        assert slot.price == 10.0
        assert slot.court_type == CourtType.OUTDOOR

    def test_parse_slot_element_infers_facility_from_panel_id(
        self,
        service,
        sample_booking_request,
    ):
        """Test facility inference from collapse panel IDs."""
        from selenium.common.exceptions import NoSuchElementException

        element = MagicMock()
        attrs = {
            "equipmentid": "E999",
            "courtid": "C999",
            "datedeb": "2025/01/15 08:00:00",
            "datefin": "2025/01/15 09:00:00",
        }

        def get_attribute_side_effect(name):
            return attrs.get(name.lower(), "")

        element.get_attribute.side_effect = get_attribute_side_effect
        element.text = ""

        collapse = MagicMock()
        collapse.get_attribute.return_value = "collapseJesseOwens08h"

        def find_element_side_effect(by, value):
            if by == By.XPATH and "collapse" in value:
                return collapse
            raise NoSuchElementException()

        element.find_element.side_effect = find_element_side_effect

        slot = service._parse_slot_element(
            element,
            "",
            now_paris(),
            sample_booking_request,
        )

        assert slot is not None
        assert slot.facility_name == "JesseOwens"
        assert slot.facility_code == "jesseowens"

    def test_parse_available_slots_html_extracts_facility_address(
        self,
        service,
        sample_booking_request,
    ):
        """Test availability parsing captures facility address from AJAX HTML."""
        html = """
        <div class="facility-card" data-facility-address="15 Rue du Tennis, 75001 Paris">
            <div class="tennis-court">
                <span class="court">Court n° 3</span>
                <button class="buttonAllOk"
                    equipmentid="E1"
                    courtid="C1"
                    datedeb="2025/01/15 18:00:00"
                    datefin="2025/01/15 19:00:00"
                    price="10"
                    typeprice="Couvert"></button>
            </div>
        </div>
        """

        slots = service._parse_available_slots_html(
            html=html,
            facility_name="Tennis Club Paris",
            target_date=now_paris(),
            request=sample_booking_request,
            captcha_request_id=None,
        )

        assert slots
        assert slots[0].facility_address == "15 Rue du Tennis, 75001 Paris"

    def test_parse_available_slots_html_accepts_data_attributes(
        self,
        service,
        sample_booking_request,
    ):
        """Test availability parsing handles data-* slot attributes."""
        html = """
        <div class="tennis-court">
            <button data-equipment-id="E2"
                data-court-id="C2"
                data-date-deb="2025/01/15 18:00:00"
                data-date-fin="2025/01/15 19:00:00"
                data-price="12"
                data-type-price="Decouvert"
                data-captcha-request-id="CAP-123"></button>
        </div>
        """

        slots = service._parse_available_slots_html(
            html=html,
            facility_name="Tennis Club Paris",
            target_date=now_paris(),
            request=replace(sample_booking_request, court_type=CourtType.ANY),
            captcha_request_id="CAP-DEFAULT",
        )

        assert slots
        slot = slots[0]
        assert slot.equipment_id == "E2"
        assert slot.court_id == "C2"
        assert slot.captcha_request_id == "CAP-123"
        assert slot.price == 12.0
        assert slot.court_type == CourtType.OUTDOOR

    def test_parse_available_slots_html_accepts_anchor_elements(
        self,
        service,
        sample_booking_request,
    ):
        """Test availability parsing handles anchor elements."""
        html = """
        <div class="tennis-court">
            <a class="buttonAllOk"
                data-equipment-id="E4"
                data-court-id="C4"
                data-date-deb="2025/01/15 18:00:00"
                data-date-fin="2025/01/15 19:00:00"
                data-type-price="Couvert"></a>
        </div>
        """

        slots = service._parse_available_slots_html(
            html=html,
            facility_name="Facility",
            target_date=now_paris(),
            request=sample_booking_request,
            captcha_request_id=None,
        )

        assert slots
        slot = slots[0]
        assert slot.equipment_id == "E4"
        assert slot.court_id == "C4"

    def test_parse_available_slots_html_accepts_input_elements(
        self,
        service,
        sample_booking_request,
    ):
        """Test availability parsing handles input elements."""
        html = """
        <div class="tennis-court">
            <input type="button" class="buttonAllOk"
                equipmentid="E5"
                courtid="C5"
                datedeb="2025/01/15 18:00:00"
                datefin="2025/01/15 19:00:00"
                typeprice="Couvert" />
        </div>
        """

        slots = service._parse_available_slots_html(
            html=html,
            facility_name="Facility",
            target_date=now_paris(),
            request=sample_booking_request,
            captcha_request_id=None,
        )

        assert slots
        slot = slots[0]
        assert slot.equipment_id == "E5"
        assert slot.court_id == "C5"

    def test_parse_available_slots_html_accepts_date_formats_without_seconds(
        self,
        service,
        sample_booking_request,
    ):
        """Test availability parsing handles date strings without seconds."""
        html = """
        <div class="tennis-court">
            <button class="buttonAllOk"
                equipmentid="E3"
                courtid="C3"
                datedeb="2025-01-15 18:00"
                datefin="2025-01-15 19:00"
                price="10"
                typeprice="Couvert"></button>
        </div>
        """

        slots = service._parse_available_slots_html(
            html=html,
            facility_name="Tennis Club Paris",
            target_date=now_paris(),
            request=sample_booking_request,
            captcha_request_id=None,
        )

        assert slots
        slot = slots[0]
        assert slot.time_start == "18:00"
        assert slot.time_end == "19:00"

    def test_parse_facility_results_filters_mismatched_court_type(
        self,
        service,
        sample_booking_request,
    ):
        """Test facility parsing skips slots with mismatched court type."""
        mock_section = MagicMock()
        mock_section.find_elements.return_value = [MagicMock()]
        service.driver.find_element.return_value = mock_section

        slot = CourtSlot(
            facility_name="Facility 1",
            facility_code="facility-1",
            court_number="1",
            date=now_paris(),
            time_start="18:00",
            time_end="19:00",
            court_type=CourtType.OUTDOOR,
        )

        with patch.object(service, "_parse_slot_element", return_value=slot):
            results = service._parse_facility_results(
                "facility-1",
                now_paris(),
                sample_booking_request,
            )

        assert results == []

    def test_slot_matches_request_allows_unknown_type(self, service, sample_booking_request):
        """Test that unknown slot types are allowed when preference is set."""
        slot = CourtSlot(
            facility_name="Facility 1",
            facility_code="FAC1",
            court_number="1",
            date=now_paris(),
            time_start="18:00",
            time_end="19:00",
            court_type=CourtType.ANY,
        )

        assert service._slot_matches_request(slot, sample_booking_request) is True

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

    def test_check_for_captcha_detects_recaptcha_script(self, service, mock_driver):
        """Test CAPTCHA detection when only reCAPTCHA script is present."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()
        mock_driver.page_source = (
            "<script src='https://www.google.com/recaptcha/api.js?render=sitekey'></script>"
        )

        assert service._check_for_captcha() is True

    def test_submit_captcha_form_clicks_submit_button(self, service, mock_driver):
        """Test captcha form submission clicks a submit button when present."""
        mock_form = MagicMock()
        mock_button = MagicMock()
        mock_form.find_element.return_value = mock_button
        mock_driver.find_element.return_value = mock_form

        assert service._submit_captcha_form_if_present() is True
        mock_button.click.assert_called_once()

    def test_submit_captcha_form_falls_back_to_js_submit(self, service, mock_driver):
        """Test captcha form submission falls back to JS submit when no button found."""
        from selenium.common.exceptions import NoSuchElementException

        mock_form = MagicMock()
        mock_form.find_element.side_effect = NoSuchElementException()
        mock_driver.find_element.return_value = mock_form

        assert service._submit_captcha_form_if_present() is True
        mock_driver.execute_script.assert_called_once()

    def test_submit_search_form_if_present_success(self, service, mock_driver):
        """Test search form submission uses JS when form exists."""
        mock_driver.execute_script.return_value = True

        assert service._submit_search_form_if_present() is True
        mock_driver.execute_script.assert_called_once()

    def test_submit_search_form_if_present_failure(self, service, mock_driver):
        """Test search form submission handles WebDriver errors."""
        from selenium.common.exceptions import WebDriverException

        mock_driver.execute_script.side_effect = WebDriverException("boom")

        assert service._submit_search_form_if_present() is False

    def test_get_captcha_request_id_from_named_input(self, service, mock_driver):
        """Test captchaRequestId extraction from named input."""
        from selenium.common.exceptions import NoSuchElementException

        mock_input = MagicMock()
        mock_input.get_attribute.return_value = "CAP-789"

        def find_element_side_effect(by, value):
            if by == By.CSS_SELECTOR and value == "input[name='captchaRequestId']":
                return mock_input
            raise NoSuchElementException()

        mock_driver.find_element.side_effect = find_element_side_effect

        assert service._get_captcha_request_id() == "CAP-789"

    def test_get_captcha_request_id_from_window_variable(self, service, mock_driver):
        """Test captchaRequestId extraction from window variables."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()
        mock_driver.execute_script.return_value = "CAP-456"

        assert service._get_captcha_request_id() == "CAP-456"

    def test_get_captcha_request_id_from_page_source(self, service, mock_driver):
        """Test captchaRequestId extraction from page source."""
        from selenium.common.exceptions import NoSuchElementException

        mock_driver.find_element.side_effect = NoSuchElementException()
        mock_driver.execute_script.return_value = None
        mock_driver.page_source = "<script>var captchaRequestId = 'CAP-321';</script>"

        assert service._get_captcha_request_id() == "CAP-321"

    def test_ensure_search_results_page_submits_form(self, service, mock_driver):
        """Test search results page uses form submission when available."""
        mock_driver.current_url = (
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?"
            "page=recherche&view=recherche_creneau"
        )
        wait = MagicMock()
        wait.until.return_value = True

        with patch.object(service, "_submit_search_form_if_present", return_value=True) as submit:
            with patch.object(service, "_solve_captcha_if_present", return_value=False) as solve:
                with patch.object(service, "_get_captcha_request_id", return_value="captcha-123"):
                    result = service._ensure_search_results_page(wait)

        assert result == "captcha-123"
        submit.assert_called_once()
        solve.assert_called_once_with(wait)

    def test_ensure_search_results_page_configures_form(self, service, mock_driver):
        """Test search results page configures the form before submission."""
        mock_driver.current_url = (
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?"
            "page=recherche&view=recherche_creneau"
        )
        wait = MagicMock()
        wait.until.return_value = True
        target_date = datetime(2026, 1, 21)

        with patch.object(service, "_configure_search_form") as configure:
            with patch.object(service, "_submit_search_form_if_present", return_value=True):
                with patch.object(
                    service, "_solve_captcha_if_present", return_value=False
                ) as solve:
                    with patch.object(
                        service, "_get_captcha_request_id", return_value="captcha-456"
                    ):
                        result = service._ensure_search_results_page(
                            wait,
                            target_date=target_date,
                            facility_names=["Jesse Owens"],
                            hour_range="8-22",
                            sel_in_out=["V"],
                        )

        assert result == "captcha-456"
        configure.assert_called_once_with(
            target_date=target_date,
            facility_names=["Jesse Owens"],
            hour_range="8-22",
            sel_in_out=["V"],
        )
        solve.assert_called_once_with(wait)

    def test_solve_captcha_if_present_submits_form(self, service):
        """Test CAPTCHA solve attempts submit the form when successful."""
        service._captcha_solver = MagicMock()
        service._captcha_solver.solve_captcha_from_page.return_value = MagicMock(
            success=True, token="token"
        )

        with patch.object(service, "_check_for_captcha", return_value=True):
            with patch.object(service, "_submit_captcha_form_if_present") as submit:
                result = service._solve_captcha_if_present()

        assert result is True
        submit.assert_called_once()

    def test_check_booking_success_true(self, service, mock_driver):
        """Test booking success detection when confirmed."""
        mock_driver.page_source = "Votre réservation confirmée avec succès"
        assert service._check_booking_success() is True

    def test_check_booking_success_false(self, service, mock_driver):
        """Test booking success detection when not confirmed."""
        mock_driver.page_source = "Erreur lors de la réservation"
        assert service._check_booking_success() is False

    def test_select_carnet_payment_clicks_radio(self, service, mock_driver):
        """Test carnet selection clicks a radio input when present."""
        mock_radio = MagicMock()
        mock_radio.is_selected.return_value = False

        def find_elements_side_effect(by, value):
            if by == By.CSS_SELECTOR:
                return [mock_radio]
            return []

        mock_driver.find_elements.side_effect = find_elements_side_effect

        assert service._select_carnet_payment_if_present() is True
        mock_radio.click.assert_called_once()

    def test_select_carnet_payment_selects_option(self, service, mock_driver):
        """Test carnet selection falls back to select options."""
        mock_select = MagicMock()
        mock_option = MagicMock()
        mock_option.text = "Carnet 10"
        mock_option.get_attribute.return_value = "carnet-10"
        mock_select.find_elements.return_value = [mock_option]

        def find_elements_side_effect(by, value):
            if by == By.CSS_SELECTOR:
                return []
            if by == By.XPATH:
                return []
            if by == By.TAG_NAME and value == "select":
                return [mock_select]
            return []

        mock_driver.find_elements.side_effect = find_elements_side_effect

        assert service._select_carnet_payment_if_present() is True
        mock_option.click.assert_called_once()

    def test_book_court_not_logged_in(self, service, sample_court_slot):
        """Test booking fails when not logged in."""
        result = service.book_court(sample_court_slot)

        assert result.success is False
        assert result.error_message == "Not logged in"

    def test_search_available_courts_empty(self, service, mock_driver, sample_booking_request):
        """Test search returns empty list when no results."""
        with patch.object(service, "_ensure_search_results_page"), patch.object(
            service,
            "_resolve_facility_preferences",
            return_value=["Max Rousié"],
        ), patch.object(service, "_fetch_availability_html", return_value=""), patch.object(
            service, "_parse_available_slots_html", return_value=[]
        ), patch.object(
            service, "_parse_all_results", return_value=[]
        ):
            result = service.search_available_courts(sample_booking_request)

        assert result == []

    def test_search_available_courts_dom_fallback_on_ajax_empty(
        self,
        service,
        mock_driver,
        sample_booking_request,
        sample_court_slot,
    ):
        """Test DOM fallback is used when AJAX search returns no slots."""
        with patch.object(service, "_ensure_search_results_page"), patch.object(
            service,
            "_resolve_facility_preferences",
            return_value=["Max Rousié"],
        ), patch.object(service, "_fetch_availability_html", return_value=""), patch.object(
            service, "_parse_available_slots_html", return_value=[]
        ), patch.object(
            service, "_parse_all_results", return_value=[sample_court_slot]
        ):
            result = service.search_available_courts(sample_booking_request)

        assert result == [sample_court_slot]

    def test_search_available_courts_dom_fallback_when_no_facilities(
        self,
        service,
        mock_driver,
        sample_booking_request,
        sample_court_slot,
    ):
        """Test DOM fallback is used when facility preferences cannot be resolved."""
        with patch.object(service, "_ensure_search_results_page"), patch.object(
            service,
            "_resolve_facility_preferences",
            return_value=[],
        ), patch.object(service, "_parse_all_results", return_value=[sample_court_slot]):
            result = service.search_available_courts(sample_booking_request)

        assert result == [sample_court_slot]

    def test_search_available_courts_dom_fallback_filters_by_facility_preferences(
        self,
        service,
        mock_driver,
        sample_booking_request,
    ):
        """Test DOM fallback respects facility preferences when parsing all slots."""
        preferred_request = replace(sample_booking_request, facility_preferences=["Facility A"])
        preferred_slot = CourtSlot(
            facility_name="Facility A",
            facility_code="facility-a",
            court_number="1",
            date=now_paris(),
            time_start="18:00",
            time_end="19:00",
            court_type=CourtType.INDOOR,
        )
        other_slot = CourtSlot(
            facility_name="Facility B",
            facility_code="facility-b",
            court_number="2",
            date=now_paris(),
            time_start="18:00",
            time_end="19:00",
            court_type=CourtType.INDOOR,
        )

        with patch.object(service, "_ensure_search_results_page"), patch.object(
            service,
            "_resolve_facility_preferences",
            return_value=[],
        ), patch.object(service, "_parse_all_results", return_value=[other_slot, preferred_slot]):
            result = service.search_available_courts(preferred_request)

        assert result == [preferred_slot]

    def test_fetch_availability_html_uses_search_url_base(self, service, mock_driver):
        """Test availability fetch builds the AJAX URL from search_url."""
        mock_driver.execute_async_script.return_value = {"ok": True, "text": "<html></html>"}
        service.search_url = (
            "https://example.com/tennis/jsp/site/Portal.jsp?"
            "page=recherche&view=recherche_creneau"
        )

        html = service._fetch_availability_html(
            hour_range="8-10",
            when_value="01/01/2025",
            facility_name="Facility",
            sel_in_out=["V"],
            sel_coating=["X"],
        )

        assert html == "<html></html>"
        args = mock_driver.execute_async_script.call_args[0]
        script = args[0]
        assert "selInOut[]" in script
        assert "selCoating[]" in script
        assert args[-1] == (
            "https://example.com/tennis/jsp/site/Portal.jsp?"
            "page=recherche&action=ajax_rechercher_creneau"
        )

    def test_get_available_facility_names_from_js_favorites(self, service, mock_driver):
        """Test facility name discovery uses jsFav when available."""

        def execute_script_side_effect(script):
            if "mapMarkers" in script:
                return []
            if "jsFav" in script:
                return ["Jesse Owens", " ", "Max Rousié"]
            return []

        mock_driver.execute_script.side_effect = execute_script_side_effect
        mock_driver.find_elements.return_value = []

        names = service._get_available_facility_names()

        assert names == ["Jesse Owens", "Max Rousié"]
        assert any(
            "jsFav" in call_args.args[0] for call_args in mock_driver.execute_script.call_args_list
        )

    def test_get_available_facility_names_from_map_markers(self, service, mock_driver):
        """Test facility name discovery uses map markers when available."""

        def execute_script_side_effect(script):
            if "mapMarkers" in script:
                return ["Alain Mimoun", " ", "Amandiers"]
            if "jsFav" in script:
                return []
            return []

        mock_driver.execute_script.side_effect = execute_script_side_effect
        mock_driver.find_elements.return_value = []

        names = service._get_available_facility_names()

        assert names == ["Alain Mimoun", "Amandiers"]
        map_marker_calls = [
            call_args.args[0]
            for call_args in mock_driver.execute_script.call_args_list
            if "mapMarkers" in call_args.args[0]
        ]
        assert any("get('map')" in script for script in map_marker_calls)

    def test_get_available_facility_names_falls_back_to_dom(self, service, mock_driver):
        """Test facility name discovery falls back to DOM tokens."""
        from selenium.common.exceptions import WebDriverException

        mock_driver.execute_script.side_effect = WebDriverException("JS blocked")

        def find_elements_side_effect(by, selector):
            if selector == ".tennisName":
                return [MagicMock(text="Jesse Owens"), MagicMock(text="Max Rousié")]
            if selector == "#bookmarkList .tennis-label":
                return [MagicMock(text="Jesse Owens"), MagicMock(text="Bertrand Dauvin")]
            return []

        mock_driver.find_elements.side_effect = find_elements_side_effect

        names = service._get_available_facility_names()

        assert names == ["Jesse Owens", "Max Rousié", "Bertrand Dauvin"]

    def test_resolve_facility_preferences_matches_substring_code(self, service):
        """Test preference matching resolves codes embedded in facility names."""
        request = BookingRequest(
            id="req-1",
            user_id="user-1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="22:00",
            facility_preferences=["FAC001"],
            court_type=CourtType.ANY,
        )

        with patch.object(
            service,
            "_get_available_facility_names",
            return_value=["Tennis Center FAC001", "Other Center"],
        ):
            resolved = service._resolve_facility_preferences(request)

        assert resolved == ["Tennis Center FAC001"]

    def test_resolve_facility_preferences_ambiguous_substring_keeps_pref(self, service):
        """Test preference matching avoids ambiguous substring matches."""
        request = BookingRequest(
            id="req-1",
            user_id="user-1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="22:00",
            facility_preferences=["CENTER"],
            court_type=CourtType.ANY,
        )

        with patch.object(
            service,
            "_get_available_facility_names",
            return_value=["Center One", "Center Two"],
        ):
            resolved = service._resolve_facility_preferences(request)

        assert resolved == ["CENTER"]

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
