"""Tests for the scheduled cron jobs."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models import Booking, BookingRequest, CourtType, DayOfWeek, User
from src.schedulers.cron_jobs import (
    _create_booking_from_result,
    _process_booking_request,
    booking_job,
    cleanup_old_notifications,
    send_reminder,
)
from src.services.notification import NotificationResult
from src.services.paris_tennis import BookingResult, CourtSlot
from src.utils.timezone import now_paris, today_weekday_paris


class TestBookingJob:
    """Tests for the booking_job function."""

    @pytest.fixture
    def mock_user(self):
        """Create a test user."""
        return User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            subscription_active=True,
        )

    @pytest.fixture
    def mock_booking_request(self):
        """Create a test booking request for today's day of week."""
        today_dow = today_weekday_paris()
        return BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek(today_dow),
            time_start="18:00",
            time_end="20:00",
            facility_preferences=["FAC001"],
            court_type=CourtType.ANY,
            partner_name="Partner Name",
            partner_email="partner@example.com",
            active=True,
        )

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_no_active_requests(self, mock_notification, mock_sheets):
        """Test booking job with no active requests."""
        mock_sheets.get_active_booking_requests.return_value = []

        booking_job()

        mock_sheets.get_active_booking_requests.assert_called_once()
        # Should not attempt to fetch eligible users
        mock_sheets.get_eligible_users.assert_not_called()

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_no_eligible_users(
        self, mock_notification, mock_sheets, mock_booking_request
    ):
        """Test booking job when no users are eligible."""
        mock_sheets.get_active_booking_requests.return_value = [mock_booking_request]
        mock_sheets.get_eligible_users.return_value = []

        booking_job()

        mock_sheets.get_active_booking_requests.assert_called_once()
        mock_sheets.get_eligible_users.assert_called_once()

    @patch("src.schedulers.cron_jobs._process_booking_request")
    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_skips_pending_booking(
        self,
        mock_notification,
        mock_sheets,
        mock_process,
        mock_user,
        mock_booking_request,
    ):
        """Test that booking job skips users with pending bookings."""
        mock_sheets.get_active_booking_requests.return_value = [mock_booking_request]
        mock_sheets.get_eligible_users.return_value = [mock_user]
        mock_sheets.acquire_user_lock.return_value = True  # Lock acquired
        mock_sheets.has_pending_booking.return_value = True

        booking_job()

        mock_sheets.has_pending_booking.assert_called_with(mock_user.id)
        mock_process.assert_not_called()
        mock_sheets.release_user_lock.assert_called()  # Lock should be released

    @patch("src.schedulers.cron_jobs._process_booking_request")
    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_processes_eligible_request(
        self,
        mock_notification,
        mock_sheets,
        mock_process,
        mock_user,
        mock_booking_request,
    ):
        """Test that booking job processes eligible requests."""
        mock_sheets.get_active_booking_requests.return_value = [mock_booking_request]
        mock_sheets.get_eligible_users.return_value = [mock_user]
        mock_sheets.acquire_user_lock.return_value = True  # Lock acquired
        mock_sheets.has_pending_booking.return_value = False

        booking_job()

        mock_process.assert_called_once()
        mock_sheets.release_user_lock.assert_called()  # Lock should be released

    @patch("src.schedulers.cron_jobs._process_booking_request")
    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_stops_after_success_for_user(
        self,
        mock_notification,
        mock_sheets,
        mock_process,
        mock_user,
    ):
        """Test booking job stops after a successful booking for a user."""
        request_one = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="18:00",
            time_end="20:00",
            active=True,
        )
        request_two = BookingRequest(
            id="req2",
            user_id="user1",
            day_of_week=DayOfWeek.TUESDAY,
            time_start="18:00",
            time_end="20:00",
            active=True,
        )
        mock_sheets.get_active_booking_requests.return_value = [request_one, request_two]
        mock_sheets.get_eligible_users.return_value = [mock_user]
        mock_sheets.acquire_user_lock.return_value = True
        mock_sheets.has_pending_booking.return_value = False
        mock_process.return_value = True

        booking_job()

        assert mock_process.call_count == 1
        assert mock_process.call_args_list[0].args[1].id == "req1"
        mock_sheets.release_user_lock.assert_called()

    @patch("src.schedulers.cron_jobs._process_booking_request")
    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_processes_requests_any_day(
        self,
        mock_notification,
        mock_sheets,
        mock_process,
        mock_user,
    ):
        """Test that booking job processes requests regardless of day of week."""
        # Create request for a different day
        today_dow = today_weekday_paris()
        other_dow = (today_dow + 1) % 7
        request = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek(other_dow),
            time_start="18:00",
            time_end="20:00",
            active=True,
        )
        mock_sheets.get_active_booking_requests.return_value = [request]
        mock_sheets.get_eligible_users.return_value = [mock_user]
        mock_sheets.acquire_user_lock.return_value = True
        mock_sheets.has_pending_booking.return_value = False

        booking_job()

        mock_process.assert_called_once()
        mock_sheets.release_user_lock.assert_called()

    @patch("src.schedulers.cron_jobs._process_booking_request")
    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_booking_job_skips_when_lock_not_acquired(
        self,
        mock_notification,
        mock_sheets,
        mock_process,
        mock_user,
        mock_booking_request,
    ):
        """Test that booking job skips processing when lock cannot be acquired."""
        mock_sheets.get_active_booking_requests.return_value = [mock_booking_request]
        mock_sheets.get_eligible_users.return_value = [mock_user]
        mock_sheets.acquire_user_lock.return_value = False  # Lock NOT acquired

        booking_job()

        mock_sheets.acquire_user_lock.assert_called()
        mock_process.assert_not_called()
        # Should not try to release lock we never acquired
        mock_sheets.release_user_lock.assert_not_called()


class TestProcessBookingRequest:
    """Tests for the _process_booking_request function."""

    @pytest.fixture
    def mock_user(self):
        """Create a test user."""
        return User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            subscription_active=True,
        )

    @pytest.fixture
    def mock_booking_request(self):
        """Create a test booking request."""
        return BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="18:00",
            time_end="20:00",
            facility_preferences=["FAC001"],
            partner_name="Partner Name",
            active=True,
        )

    @pytest.fixture
    def mock_slot(self):
        """Create a test court slot."""
        return CourtSlot(
            facility_name="Tennis Club",
            facility_code="FAC001",
            court_number="1",
            date=datetime(2025, 1, 20, 18, 0),
            time_start="18:00",
            time_end="19:00",
            court_type=CourtType.ANY,
        )

    @patch("src.schedulers.cron_jobs.create_paris_tennis_session")
    def test_process_booking_login_failure(
        self,
        mock_tennis_session,
        mock_user,
        mock_booking_request,
    ):
        """Test processing when login fails."""
        mock_sheets = MagicMock()
        mock_notification = MagicMock()

        mock_service = MagicMock()
        mock_service.login.return_value = False
        mock_tennis_session.return_value.__enter__.return_value = mock_service

        result = _process_booking_request(
            mock_user, mock_booking_request, mock_sheets, mock_notification
        )

        mock_service.login.assert_called_once()
        mock_notification.send_booking_failure_notification.assert_called_once()
        assert result is False

    @patch("src.schedulers.cron_jobs.create_paris_tennis_session")
    def test_process_booking_no_slots_available(
        self,
        mock_tennis_session,
        mock_user,
        mock_booking_request,
    ):
        """Test processing when no slots are available sends notification."""
        mock_sheets = MagicMock()
        # Mock that no notification has been sent yet for this request/date
        mock_sheets.was_no_slots_notification_sent.return_value = False
        mock_notification = MagicMock()
        mock_notification.send_no_slots_notification.return_value = NotificationResult(success=True)

        mock_service = MagicMock()
        mock_service.login.return_value = True
        mock_service.search_available_courts.return_value = []
        mock_tennis_session.return_value.__enter__.return_value = mock_service

        result = _process_booking_request(
            mock_user, mock_booking_request, mock_sheets, mock_notification
        )

        mock_service.search_available_courts.assert_called_once()
        # Should send "no slots available" notification to user
        mock_notification.send_no_slots_notification.assert_called_once()
        # Should mark that notification was sent
        mock_sheets.mark_no_slots_notification_sent.assert_called_once()
        # The failure notification should NOT be called (no slots is informational, not error)
        mock_notification.send_booking_failure_notification.assert_not_called()
        assert result is False

    @patch("src.schedulers.cron_jobs.create_paris_tennis_session")
    def test_process_booking_no_slots_already_notified(
        self,
        mock_tennis_session,
        mock_user,
        mock_booking_request,
    ):
        """Test that no duplicate notification is sent when already notified."""
        mock_sheets = MagicMock()
        # Mock that notification was already sent for this request/date
        mock_sheets.was_no_slots_notification_sent.return_value = True
        mock_notification = MagicMock()

        mock_service = MagicMock()
        mock_service.login.return_value = True
        mock_service.search_available_courts.return_value = []
        mock_tennis_session.return_value.__enter__.return_value = mock_service

        result = _process_booking_request(
            mock_user, mock_booking_request, mock_sheets, mock_notification
        )

        mock_service.search_available_courts.assert_called_once()
        # Should NOT send notification (already sent)
        mock_notification.send_no_slots_notification.assert_not_called()
        # Should NOT mark notification sent (already marked)
        mock_sheets.mark_no_slots_notification_sent.assert_not_called()
        assert result is False

    @patch("src.schedulers.cron_jobs.create_paris_tennis_session")
    def test_process_booking_no_slots_notification_failed(
        self,
        mock_tennis_session,
        mock_user,
        mock_booking_request,
    ):
        """Test that no-slots notifications are not marked when sending fails."""
        mock_sheets = MagicMock()
        mock_sheets.was_no_slots_notification_sent.return_value = False
        mock_notification = MagicMock()
        mock_notification.send_no_slots_notification.return_value = NotificationResult(
            success=False, error_message="SMTP settings not configured"
        )

        mock_service = MagicMock()
        mock_service.login.return_value = True
        mock_service.search_available_courts.return_value = []
        mock_tennis_session.return_value.__enter__.return_value = mock_service

        result = _process_booking_request(
            mock_user, mock_booking_request, mock_sheets, mock_notification
        )

        mock_notification.send_no_slots_notification.assert_called_once()
        mock_sheets.mark_no_slots_notification_sent.assert_not_called()
        assert result is False

    @patch("src.schedulers.cron_jobs.create_paris_tennis_session")
    def test_process_booking_success(
        self,
        mock_tennis_session,
        mock_user,
        mock_booking_request,
        mock_slot,
    ):
        """Test successful booking flow."""
        mock_sheets = MagicMock()
        mock_sheets.add_booking.return_value = True
        mock_notification = MagicMock()

        mock_service = MagicMock()
        mock_service.login.return_value = True
        mock_service.search_available_courts.return_value = [mock_slot]
        mock_service.book_court.return_value = BookingResult(
            success=True,
            confirmation_id="CONF123",
            slot=mock_slot,
        )
        mock_tennis_session.return_value.__enter__.return_value = mock_service

        result = _process_booking_request(
            mock_user, mock_booking_request, mock_sheets, mock_notification
        )

        mock_service.book_court.assert_called_once_with(
            mock_slot, mock_booking_request.partner_name
        )
        mock_sheets.add_booking.assert_called_once()
        mock_notification.send_booking_confirmation.assert_called_once()
        assert result is True

    @patch("src.schedulers.cron_jobs.create_paris_tennis_session")
    def test_process_booking_all_slots_fail(
        self,
        mock_tennis_session,
        mock_user,
        mock_booking_request,
        mock_slot,
    ):
        """Test when all booking attempts fail."""
        mock_sheets = MagicMock()
        mock_notification = MagicMock()

        mock_service = MagicMock()
        mock_service.login.return_value = True
        mock_service.search_available_courts.return_value = [mock_slot]
        mock_service.book_court.return_value = BookingResult(
            success=False,
            error_message="Slot already taken",
            slot=mock_slot,
        )
        mock_tennis_session.return_value.__enter__.return_value = mock_service

        result = _process_booking_request(
            mock_user, mock_booking_request, mock_sheets, mock_notification
        )

        mock_notification.send_booking_failure_notification.assert_called_once()
        assert result is False


class TestSendReminder:
    """Tests for the send_reminder function."""

    @pytest.fixture
    def mock_user(self):
        """Create a test user with name."""
        return User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            name="Jean Dupont",
            subscription_active=True,
        )

    @pytest.fixture
    def mock_booking_today(self):
        """Create a test booking for today."""
        return Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club",
            facility_code="TC001",
            court_number="1",
            date=now_paris(),
            time_start="18:00",
            time_end="19:00",
            partner_name="Partner Name",
            partner_email="partner@example.com",
            confirmation_id="CONF123",
        )

    @pytest.fixture
    def mock_booking_request(self):
        """Create a test booking request with partner email."""
        return BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="18:00",
            time_end="20:00",
            partner_name="Partner Name",
            partner_email="partner@example.com",
            active=True,
        )

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_send_reminder_not_configured(self, mock_notification_func, mock_sheets):
        """Test send_reminder when notification service not configured."""
        mock_notification = MagicMock()
        mock_notification.is_configured.return_value = False
        mock_notification_func.return_value = mock_notification

        send_reminder()

        mock_sheets.get_todays_bookings.assert_not_called()

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_send_reminder_no_bookings(self, mock_notification_func, mock_sheets):
        """Test send_reminder with no bookings today."""
        mock_notification = MagicMock()
        mock_notification.is_configured.return_value = True
        mock_notification_func.return_value = mock_notification
        mock_sheets.get_todays_bookings.return_value = []

        send_reminder()

        mock_sheets.get_todays_bookings.assert_called_once()
        mock_notification.send_match_day_reminder.assert_not_called()

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_send_reminder_sends_to_user(
        self,
        mock_notification_func,
        mock_sheets,
        mock_user,
        mock_booking_today,
    ):
        """Test send_reminder sends reminder to user."""
        mock_notification = MagicMock()
        mock_notification.is_configured.return_value = True
        mock_notification.send_match_day_reminder.return_value = MagicMock(success=True)
        mock_notification_func.return_value = mock_notification

        mock_sheets.get_todays_bookings.return_value = [mock_booking_today]
        mock_sheets.get_all_users.return_value = [mock_user]

        send_reminder()

        # Should be called twice: once for user, once for partner
        # partner_email is now stored on the booking itself
        assert mock_notification.send_match_day_reminder.call_count == 2

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_send_reminder_uses_user_name(
        self,
        mock_notification_func,
        mock_sheets,
        mock_user,
        mock_booking_today,
    ):
        """Test send_reminder uses user's name for personalized greeting."""
        mock_notification = MagicMock()
        mock_notification.is_configured.return_value = True
        mock_notification.send_match_day_reminder.return_value = MagicMock(success=True)
        mock_notification_func.return_value = mock_notification

        mock_sheets.get_todays_bookings.return_value = [mock_booking_today]
        mock_sheets.get_all_users.return_value = [mock_user]

        send_reminder()

        # First call should be for the user with their name
        user_call = mock_notification.send_match_day_reminder.call_args_list[0]
        assert user_call.kwargs["recipient_email"] == mock_user.email
        assert user_call.kwargs["recipient_name"] == mock_user.name
        assert user_call.kwargs["is_partner"] is False

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_send_reminder_passes_player_name_to_partner(
        self,
        mock_notification_func,
        mock_sheets,
        mock_user,
        mock_booking_today,
    ):
        """Test send_reminder passes user's name as player_name when sending to partner."""
        mock_notification = MagicMock()
        mock_notification.is_configured.return_value = True
        mock_notification.send_match_day_reminder.return_value = MagicMock(success=True)
        mock_notification_func.return_value = mock_notification

        mock_sheets.get_todays_bookings.return_value = [mock_booking_today]
        mock_sheets.get_all_users.return_value = [mock_user]

        send_reminder()

        # Second call should be for the partner, with user's name as player_name
        # partner_email is now stored on the booking itself
        partner_call = mock_notification.send_match_day_reminder.call_args_list[1]
        assert partner_call.kwargs["recipient_email"] == mock_booking_today.partner_email
        assert partner_call.kwargs["is_partner"] is True
        assert partner_call.kwargs["player_name"] == mock_user.name

    @patch("src.schedulers.cron_jobs.sheets_service")
    @patch("src.schedulers.cron_jobs.get_notification_service")
    def test_send_reminder_skips_partner_without_email(
        self,
        mock_notification_func,
        mock_sheets,
        mock_user,
    ):
        """Test send_reminder skips partner when no email available."""
        mock_notification = MagicMock()
        mock_notification.is_configured.return_value = True
        mock_notification.send_match_day_reminder.return_value = MagicMock(success=True)
        mock_notification_func.return_value = mock_notification

        # Booking without partner email
        booking_no_partner_email = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club",
            facility_code="TC001",
            court_number="1",
            date=now_paris(),
            time_start="18:00",
            time_end="19:00",
            partner_name="Partner Name",
            partner_email=None,  # No email stored on booking
            confirmation_id="CONF123",
        )

        mock_sheets.get_todays_bookings.return_value = [booking_no_partner_email]
        mock_sheets.get_all_users.return_value = [mock_user]

        send_reminder()

        # Should only be called once for the user
        mock_notification.send_match_day_reminder.assert_called_once()


class TestCreateBookingFromResult:
    """Tests for the _create_booking_from_result function."""

    def test_create_booking_from_result(self):
        """Test creating a booking from a successful result."""
        user = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            subscription_active=True,
        )
        request = BookingRequest(
            id="req1",
            user_id="user1",
            day_of_week=DayOfWeek.MONDAY,
            time_start="18:00",
            time_end="20:00",
            partner_name="Partner Name",
            partner_email="partner@example.com",
            active=True,
        )
        slot = CourtSlot(
            facility_name="Tennis Club",
            facility_code="FAC001",
            court_number="1",
            date=datetime(2025, 1, 20, 18, 0),
            time_start="18:00",
            time_end="19:00",
            court_type=CourtType.ANY,
        )
        result = BookingResult(
            success=True,
            confirmation_id="CONF123",
            slot=slot,
        )

        booking = _create_booking_from_result(user, request, slot, result)

        assert booking.user_id == user.id
        assert booking.request_id == request.id
        assert booking.facility_name == slot.facility_name
        assert booking.facility_code == slot.facility_code
        assert booking.court_number == slot.court_number
        assert booking.time_start == slot.time_start
        assert booking.time_end == slot.time_end
        assert booking.partner_name == request.partner_name
        assert booking.partner_email == request.partner_email
        assert booking.confirmation_id == result.confirmation_id
        assert booking.id is not None  # UUID generated


class TestCleanupOldNotifications:
    """Tests for the cleanup_old_notifications function."""

    @patch("src.schedulers.cron_jobs.sheets_service")
    def test_cleanup_old_notifications_success(self, mock_sheets):
        """Test cleanup job successfully removes old records."""
        mock_sheets.cleanup_old_no_slots_notifications.return_value = 5

        cleanup_old_notifications()

        mock_sheets.cleanup_old_no_slots_notifications.assert_called_once_with(days_to_keep=7)

    @patch("src.schedulers.cron_jobs.sheets_service")
    def test_cleanup_old_notifications_no_records(self, mock_sheets):
        """Test cleanup job when no old records exist."""
        mock_sheets.cleanup_old_no_slots_notifications.return_value = 0

        cleanup_old_notifications()

        mock_sheets.cleanup_old_no_slots_notifications.assert_called_once()

    @patch("src.schedulers.cron_jobs.sheets_service")
    def test_cleanup_old_notifications_handles_error(self, mock_sheets):
        """Test cleanup job handles errors gracefully."""
        mock_sheets.cleanup_old_no_slots_notifications.side_effect = Exception("Google API error")

        # Should not raise exception
        cleanup_old_notifications()

        mock_sheets.cleanup_old_no_slots_notifications.assert_called_once()
