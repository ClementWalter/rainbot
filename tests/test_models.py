"""Tests for data models."""

from datetime import datetime

import pytest

from src.models import Booking, BookingRequest, CourtType, DayOfWeek, User, normalize_time


class TestUser:
    """Tests for User model."""

    def test_user_creation(self):
        """Test basic user creation."""
        user = User(
            id="user1",
            email="test@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="secret123",
        )
        assert user.id == "user1"
        assert user.email == "test@example.com"
        assert user.name is None  # default
        assert user.subscription_active is True  # default

    def test_user_creation_with_name(self):
        """Test user creation with name field."""
        user = User(
            id="user1",
            email="test@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="secret123",
            name="Jean Dupont",
        )
        assert user.id == "user1"
        assert user.name == "Jean Dupont"
        assert user.email == "test@example.com"

    def test_user_is_eligible_with_active_subscription(self):
        """Test user eligibility with active subscription."""
        user = User(
            id="user1",
            email="test@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="secret123",
            subscription_active=True,
        )
        assert user.is_eligible() is True

    def test_user_not_eligible_without_subscription(self):
        """Test user not eligible without active subscription."""
        user = User(
            id="user1",
            email="test@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="secret123",
            subscription_active=False,
        )
        assert user.is_eligible() is False

    def test_user_not_eligible_without_credentials(self):
        """Test user not eligible without Paris Tennis credentials."""
        user = User(
            id="user1",
            email="test@example.com",
            paris_tennis_email="",
            paris_tennis_password="",
            subscription_active=True,
        )
        assert user.is_eligible() is False


class TestBookingRequest:
    """Tests for BookingRequest model."""

    def test_booking_request_creation(self):
        """Test basic booking request creation."""
        request = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="18:00",
            time_end="20:00",
            facility_preferences=["FAC001", "FAC002"],
        )
        assert request.id == "req1"
        assert request.day_of_week == DayOfWeek.MONDAY
        assert request.court_type == CourtType.ANY  # default

    def test_time_in_range(self):
        """Test time range checking."""
        request = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="18:00",
            time_end="20:00",
        )
        assert request.is_time_in_range("18:00") is True
        assert request.is_time_in_range("19:00") is True
        assert request.is_time_in_range("20:00") is True
        assert request.is_time_in_range("17:59") is False
        assert request.is_time_in_range("20:01") is False

    def test_from_dict(self):
        """Test creating BookingRequest from dictionary."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": "monday",
            "time_start": "18:00",
            "time_end": "20:00",
            "facility_preferences": "FAC001, FAC002",
            "court_type": "indoor",
            "partner_name": "John Doe",
            "partner_email": "john@example.com",
            "active": True,
        }
        request = BookingRequest.from_dict(data)
        assert request.id == "req1"
        assert request.day_of_week == DayOfWeek.MONDAY
        assert request.court_type == CourtType.INDOOR
        assert request.facility_preferences == ["FAC001", "FAC002"]
        assert request.partner_name == "John Doe"

    def test_from_dict_with_integer_day(self):
        """Test creating BookingRequest with integer day_of_week."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 2,  # Wednesday
            "time_start": "10:00",
            "time_end": "12:00",
        }
        request = BookingRequest.from_dict(data)
        assert request.day_of_week == DayOfWeek.WEDNESDAY

    def test_from_dict_with_numeric_string_day(self):
        """Test creating BookingRequest with numeric string day_of_week (e.g., from Google Sheets)."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": "4",  # Friday as string
            "time_start": "10:00",
            "time_end": "12:00",
        }
        request = BookingRequest.from_dict(data)
        assert request.day_of_week == DayOfWeek.FRIDAY

    def test_from_dict_clamps_time_before_minimum(self):
        """Test that times before 08:00 are clamped to 08:00 (PRD section 5.1)."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "07:00",  # Before minimum
            "time_end": "10:00",
        }
        request = BookingRequest.from_dict(data)
        assert request.time_start == "08:00"  # Clamped to minimum
        assert request.time_end == "10:00"

    def test_from_dict_clamps_time_after_maximum(self):
        """Test that times after 22:00 are clamped to 22:00 (PRD section 5.1)."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "18:00",
            "time_end": "23:00",  # After maximum
        }
        request = BookingRequest.from_dict(data)
        assert request.time_start == "18:00"
        assert request.time_end == "22:00"  # Clamped to maximum

    def test_from_dict_swaps_inverted_times(self):
        """Test that time_start > time_end are swapped."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "20:00",
            "time_end": "18:00",  # Inverted
        }
        request = BookingRequest.from_dict(data)
        assert request.time_start == "18:00"  # Swapped
        assert request.time_end == "20:00"  # Swapped

    def test_from_dict_uses_defaults_for_empty_times(self):
        """Test that empty times default to boundary values."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "",
            "time_end": "",
        }
        request = BookingRequest.from_dict(data)
        assert request.time_start == "08:00"  # Default minimum
        assert request.time_end == "22:00"  # Default maximum

    def test_from_dict_uses_defaults_for_invalid_format(self):
        """Test that invalid time formats fall back to defaults."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "invalid",
            "time_end": "abc",
        }
        request = BookingRequest.from_dict(data)
        assert request.time_start == "08:00"  # Default minimum
        assert request.time_end == "22:00"  # Default maximum


class TestBooking:
    """Tests for Booking model."""

    def test_booking_creation(self):
        """Test basic booking creation."""
        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TCP001",
            court_number="3",
            date=datetime(2025, 1, 15, 18, 0),
            time_start="18:00",
            time_end="19:00",
        )
        assert booking.id == "book1"
        assert booking.facility_name == "Tennis Club Paris"
        assert booking.created_at is not None  # auto-set

    def test_from_dict(self):
        """Test creating Booking from dictionary."""
        data = {
            "id": "book1",
            "user_id": "user1",
            "request_id": "req1",
            "facility_name": "Tennis Club Paris",
            "facility_code": "TCP001",
            "court_number": "3",
            "date": "2025-01-15T18:00:00",
            "time_start": "18:00",
            "time_end": "19:00",
            "partner_name": "Jane Doe",
            "confirmation_id": "CONF123",
        }
        booking = Booking.from_dict(data)
        assert booking.id == "book1"
        assert booking.facility_name == "Tennis Club Paris"
        assert booking.partner_name == "Jane Doe"
        assert booking.confirmation_id == "CONF123"

    def test_from_dict_with_facility_address(self):
        """Test creating Booking with facility_address from dictionary."""
        data = {
            "id": "book1",
            "user_id": "user1",
            "request_id": "req1",
            "facility_name": "Tennis Club Paris",
            "facility_code": "TCP001",
            "court_number": "3",
            "date": "2025-01-15T18:00:00",
            "time_start": "18:00",
            "time_end": "19:00",
            "facility_address": "15 Rue du Tennis, 75001 Paris",
        }
        booking = Booking.from_dict(data)
        assert booking.facility_address == "15 Rue du Tennis, 75001 Paris"

    def test_booking_creation_with_facility_address(self):
        """Test booking creation with facility_address."""
        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TCP001",
            court_number="3",
            date=datetime(2025, 1, 15, 18, 0),
            time_start="18:00",
            time_end="19:00",
            facility_address="15 Rue du Tennis, 75001 Paris",
        )
        assert booking.facility_address == "15 Rue du Tennis, 75001 Paris"

    def test_booking_facility_address_optional(self):
        """Test that facility_address is optional and defaults to None."""
        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TCP001",
            court_number="3",
            date=datetime(2025, 1, 15, 18, 0),
            time_start="18:00",
            time_end="19:00",
        )
        assert booking.facility_address is None

    def test_from_dict_with_partner_email(self):
        """Test creating Booking with partner_email from dictionary."""
        data = {
            "id": "book1",
            "user_id": "user1",
            "request_id": "req1",
            "facility_name": "Tennis Club Paris",
            "facility_code": "TCP001",
            "court_number": "3",
            "date": "2025-01-15T18:00:00",
            "time_start": "18:00",
            "time_end": "19:00",
            "partner_name": "Jane Doe",
            "partner_email": "jane@example.com",
        }
        booking = Booking.from_dict(data)
        assert booking.partner_name == "Jane Doe"
        assert booking.partner_email == "jane@example.com"

    def test_booking_partner_email_optional(self):
        """Test that partner_email is optional and defaults to None."""
        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TCP001",
            court_number="3",
            date=datetime(2025, 1, 15, 18, 0),
            time_start="18:00",
            time_end="19:00",
            partner_name="Jane Doe",
        )
        assert booking.partner_email is None

    def test_is_today(self):
        """Test checking if booking is for today."""
        today_booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club",
            facility_code="TC001",
            court_number="1",
            date=datetime.now(),
            time_start="18:00",
            time_end="19:00",
        )
        assert today_booking.is_today() is True

        past_booking = Booking(
            id="book2",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club",
            facility_code="TC001",
            court_number="1",
            date=datetime(2020, 1, 1),
            time_start="18:00",
            time_end="19:00",
        )
        assert past_booking.is_today() is False


class TestEnums:
    """Tests for enum types."""

    def test_court_type_values(self):
        """Test CourtType enum values."""
        assert CourtType.INDOOR.value == "indoor"
        assert CourtType.OUTDOOR.value == "outdoor"
        assert CourtType.ANY.value == "any"

    def test_day_of_week_values(self):
        """Test DayOfWeek enum values."""
        assert DayOfWeek.MONDAY.value == 0
        assert DayOfWeek.SUNDAY.value == 6


class TestNormalizeTime:
    """Tests for normalize_time function."""

    def test_normalize_time_already_normalized(self):
        """Test that already normalized times are unchanged."""
        assert normalize_time("08:00") == "08:00"
        assert normalize_time("09:30") == "09:30"
        assert normalize_time("18:00") == "18:00"
        assert normalize_time("22:00") == "22:00"

    def test_normalize_time_single_digit_hour(self):
        """Test normalization of single-digit hours."""
        assert normalize_time("8:00") == "08:00"
        assert normalize_time("9:00") == "09:00"
        assert normalize_time("9:30") == "09:30"

    def test_normalize_time_single_digit_minute(self):
        """Test normalization of single-digit minutes."""
        assert normalize_time("08:5") == "08:05"
        assert normalize_time("9:5") == "09:05"

    def test_normalize_time_with_whitespace(self):
        """Test that whitespace is stripped."""
        assert normalize_time(" 09:00 ") == "09:00"
        assert normalize_time("9:00 ") == "09:00"

    def test_normalize_time_invalid_returns_empty(self):
        """Test that invalid times return empty string."""
        assert normalize_time("") == ""
        assert normalize_time("invalid") == ""
        assert normalize_time("12") == ""
        assert normalize_time(":30") == ""
        assert normalize_time("12:") == ""
        assert normalize_time("abc:def") == ""
        assert normalize_time(None) == ""

    def test_normalize_time_edge_cases(self):
        """Test edge cases for time normalization."""
        assert normalize_time("00:00") == "00:00"
        assert normalize_time("0:0") == "00:00"
        assert normalize_time("23:59") == "23:59"


class TestTimeNormalizationInRange:
    """Tests for time normalization in is_time_in_range."""

    def test_is_time_in_range_with_single_digit_hour(self):
        """Test that single-digit hours are correctly checked in range.

        This is a critical bug fix: "9:00" should be considered within
        the range [08:00, 20:00], but without normalization, string
        comparison fails because "9" > "2" (comparing "9:00" > "20:00").
        """
        request = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="20:00",
        )
        # These should all be True with proper normalization
        assert request.is_time_in_range("9:00") is True
        assert request.is_time_in_range("8:00") is True
        assert request.is_time_in_range("8:30") is True

        # Out of range
        assert request.is_time_in_range("7:59") is False
        assert request.is_time_in_range("21:00") is False

    def test_is_time_in_range_invalid_time_returns_false(self):
        """Test that invalid time strings return False."""
        request = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="08:00",
            time_end="20:00",
        )
        assert request.is_time_in_range("invalid") is False
        assert request.is_time_in_range("") is False
        assert request.is_time_in_range("12") is False


class TestTimeValidationInFromDict:
    """Tests for time validation/normalization in from_dict."""

    def test_from_dict_normalizes_single_digit_hours(self):
        """Test that single-digit hours are normalized to HH:MM format."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "9:00",  # Single digit
            "time_end": "20:00",
        }
        request = BookingRequest.from_dict(data)
        assert request.time_start == "09:00"  # Normalized
        assert request.time_end == "20:00"

    def test_from_dict_normalizes_both_times(self):
        """Test that both time_start and time_end are normalized."""
        data = {
            "id": "req1",
            "user_id": "user1",
            "day_of_week": 0,
            "time_start": "9:00",  # Single digit
            "time_end": "8:30",  # Single digit, will be swapped
        }
        request = BookingRequest.from_dict(data)
        # After normalization: 09:00 and 08:30
        # After swap: time_start=08:30, time_end=09:00
        assert request.time_start == "08:30"
        assert request.time_end == "09:00"
