"""Tests for the notification service."""

from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from src.models import Booking, User
from src.services.notification import (
    NotificationResult,
    NotificationService,
    get_notification_service,
)


class TestNotificationResult:
    """Tests for the NotificationResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful notification result."""
        result = NotificationResult(success=True)

        assert result.success is True
        assert result.error_message is None

    def test_failed_result(self):
        """Test creating a failed notification result."""
        result = NotificationResult(success=False, error_message="SMTP error")

        assert result.success is False
        assert result.error_message == "SMTP error"

    def test_result_default_values(self):
        """Test that error_message defaults to None."""
        result = NotificationResult(success=True)

        assert result.error_message is None


class TestNotificationService:
    """Tests for the NotificationService class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock the settings object."""
        with patch("src.services.notification.settings") as mock:
            mock.notification.smtp_host = "smtp.example.com"
            mock.notification.smtp_port = 587
            mock.notification.smtp_user = "user@example.com"
            mock.notification.smtp_password = "password"
            mock.notification.from_email = "noreply@example.com"
            yield mock

    @pytest.fixture
    def notification_service(self, mock_settings):
        """Create a notification service with mock settings."""
        return NotificationService()

    @pytest.fixture
    def configured_service(self):
        """Create a fully configured notification service."""
        return NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

    @pytest.fixture
    def unconfigured_service(self):
        """Create an unconfigured notification service."""
        return NotificationService(
            smtp_host=None,
            smtp_port=587,
            smtp_user=None,
            smtp_password=None,
            from_email=None,
        )

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
    def mock_booking(self):
        """Create a test booking."""
        return Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TC001",
            court_number="3",
            date=datetime(2025, 1, 20),
            time_start="18:00",
            time_end="19:00",
            partner_name="Jean Dupont",
            confirmation_id="CONF123456",
        )

    def test_service_initialization_with_explicit_params(self):
        """Test initializing service with explicit parameters."""
        service = NotificationService(
            smtp_host="smtp.test.com",
            smtp_port=465,
            smtp_user="test@test.com",
            smtp_password="secret",
            from_email="from@test.com",
        )

        assert service.smtp_host == "smtp.test.com"
        assert service.smtp_port == 465
        assert service.smtp_user == "test@test.com"
        assert service.smtp_password == "secret"
        assert service.from_email == "from@test.com"

    def test_service_initialization_from_settings(self, mock_settings):
        """Test initializing service from settings."""
        service = NotificationService()

        assert service.smtp_host == "smtp.example.com"
        assert service.smtp_port == 587
        assert service.smtp_user == "user@example.com"
        assert service.smtp_password == "password"
        assert service.from_email == "noreply@example.com"

    def test_is_configured_returns_true_when_all_set(self, configured_service):
        """Test is_configured returns True when all settings are present."""
        assert configured_service.is_configured() is True

    def test_is_configured_returns_false_when_missing_host(self):
        """Test is_configured returns False when host is missing."""
        service = NotificationService(
            smtp_host=None,
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

        assert service.is_configured() is False

    def test_is_configured_returns_false_when_missing_user(self):
        """Test is_configured returns False when user is missing."""
        service = NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user=None,
            smtp_password="password",
            from_email="noreply@example.com",
        )

        assert service.is_configured() is False

    def test_is_configured_returns_false_when_missing_password(self):
        """Test is_configured returns False when password is missing."""
        service = NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password=None,
            from_email="noreply@example.com",
        )

        assert service.is_configured() is False

    def test_is_configured_returns_false_when_missing_from_email(self):
        """Test is_configured returns False when from_email is missing."""
        service = NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email=None,
        )

        assert service.is_configured() is False


class TestSendEmail:
    """Tests for the _send_email method."""

    @pytest.fixture
    def configured_service(self):
        """Create a fully configured notification service."""
        return NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

    def test_send_email_returns_error_when_not_configured(self):
        """Test that _send_email returns error when service not configured."""
        service = NotificationService(
            smtp_host=None,
            smtp_port=587,
            smtp_user=None,
            smtp_password=None,
            from_email=None,
        )

        result = service._send_email(
            to_email="test@example.com",
            subject="Test",
            body_html="<p>Test</p>",
        )

        assert result.success is False
        assert "not configured" in result.error_message

    @patch("src.services.notification.smtplib.SMTP")
    def test_send_email_success(self, mock_smtp_class, configured_service):
        """Test successful email sending."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)

        result = configured_service._send_email(
            to_email="recipient@example.com",
            subject="Test Subject",
            body_html="<p>Test Body</p>",
        )

        assert result.success is True
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@example.com", "password")
        mock_smtp.send_message.assert_called_once()

    @patch("src.services.notification.smtplib.SMTP")
    def test_send_email_with_plain_text(self, mock_smtp_class, configured_service):
        """Test email sending with explicit plain text."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)

        result = configured_service._send_email(
            to_email="recipient@example.com",
            subject="Test Subject",
            body_html="<p>Test Body</p>",
            body_text="Test Body",
        )

        assert result.success is True

    @patch("src.services.notification.smtplib.SMTP")
    def test_send_email_auth_error(self, mock_smtp_class, configured_service):
        """Test handling of SMTP authentication error."""
        import smtplib

        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp
        mock_smtp.starttls.return_value = None
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, "Auth failed")

        result = configured_service._send_email(
            to_email="recipient@example.com",
            subject="Test",
            body_html="<p>Test</p>",
        )

        assert result.success is False
        assert "authentication failed" in result.error_message.lower()

    @patch("src.services.notification.smtplib.SMTP")
    def test_send_email_smtp_error(self, mock_smtp_class, configured_service):
        """Test handling of general SMTP error."""
        import smtplib

        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp
        mock_smtp.starttls.return_value = None
        mock_smtp.login.return_value = None
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mock_smtp.send_message.side_effect = smtplib.SMTPException("Connection lost")

        result = configured_service._send_email(
            to_email="recipient@example.com",
            subject="Test",
            body_html="<p>Test</p>",
        )

        assert result.success is False
        assert "SMTP error" in result.error_message

    @patch("src.services.notification.smtplib.SMTP")
    def test_send_email_generic_error(self, mock_smtp_class, configured_service):
        """Test handling of generic exceptions."""
        mock_smtp_class.side_effect = Exception("Network error")

        result = configured_service._send_email(
            to_email="recipient@example.com",
            subject="Test",
            body_html="<p>Test</p>",
        )

        assert result.success is False
        assert "Network error" in result.error_message


class TestSendBookingConfirmation:
    """Tests for the send_booking_confirmation method."""

    @pytest.fixture
    def configured_service(self):
        """Create a fully configured notification service."""
        return NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

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
    def mock_booking(self):
        """Create a test booking."""
        return Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TC001",
            court_number="3",
            date=datetime(2025, 1, 20),
            time_start="18:00",
            time_end="19:00",
            partner_name="Jean Dupont",
            confirmation_id="CONF123456",
        )

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_calls_send_email(
        self, mock_send_email, configured_service, mock_user, mock_booking
    ):
        """Test that send_booking_confirmation calls _send_email with correct params."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(mock_user, mock_booking)

        assert result.success is True
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args

        # _send_email is called with positional args: (to_email, subject, body_html)
        to_email = call_args[0][0]
        subject = call_args[0][1]
        body_html = call_args[0][2]

        # Check email recipient
        assert to_email == mock_user.email
        # Check subject contains date
        assert "20/01/2025" in subject
        # Check body contains booking details
        assert mock_booking.facility_name in body_html
        assert mock_booking.time_start in body_html
        assert mock_booking.court_number in body_html
        assert mock_booking.partner_name in body_html
        assert mock_booking.confirmation_id in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_without_partner(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test booking confirmation without partner name."""
        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TC001",
            court_number="3",
            date=datetime(2025, 1, 20),
            time_start="18:00",
            time_end="19:00",
            partner_name=None,
            confirmation_id="CONF123456",
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(mock_user, booking)

        assert result.success is True

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_without_confirmation_id(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test booking confirmation without confirmation ID."""
        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TC001",
            court_number="3",
            date=datetime(2025, 1, 20),
            time_start="18:00",
            time_end="19:00",
            partner_name="Jean Dupont",
            confirmation_id=None,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(mock_user, booking)

        assert result.success is True

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_with_user_name(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test that booking confirmation uses personalized greeting with user name."""
        user_with_name = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            name="Pierre Martin",
            subscription_active=True,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(user_with_name, mock_booking)

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Check that the greeting includes the user's name
        assert "Bonjour Pierre Martin" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_without_user_name(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test that booking confirmation uses generic greeting when user has no name."""
        user_without_name = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            name=None,
            subscription_active=True,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(user_without_name, mock_booking)

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Check that the greeting is generic (just "Bonjour" without a name)
        assert "Bonjour," in body_html or ">Bonjour<" in body_html


class TestSendMatchDayReminder:
    """Tests for the send_match_day_reminder method."""

    @pytest.fixture
    def configured_service(self):
        """Create a fully configured notification service."""
        return NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

    @pytest.fixture
    def mock_booking(self):
        """Create a test booking."""
        return Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club Paris",
            facility_code="TC001",
            court_number="3",
            date=datetime(2025, 1, 20),
            time_start="18:00",
            time_end="19:00",
            partner_name="Jean Dupont",
            confirmation_id="CONF123456",
        )

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_to_user(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test sending reminder to user (not partner)."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="user@example.com",
            recipient_name="Pierre Martin",
            booking=mock_booking,
            is_partner=False,
        )

        assert result.success is True
        call_args = mock_send_email.call_args

        # _send_email is called with positional args: (to_email, subject, body_html)
        to_email = call_args[0][0]
        subject = call_args[0][1]
        body_html = call_args[0][2]

        assert to_email == "user@example.com"
        assert mock_booking.time_start in subject
        assert "Pierre Martin" in body_html
        assert mock_booking.partner_name in body_html
        assert mock_booking.facility_name in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_to_partner(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test sending reminder to partner."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="partner@example.com",
            recipient_name="Jean Dupont",
            booking=mock_booking,
            is_partner=True,
        )

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Partner message should mention playing with the user
        assert "Jean Dupont" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_without_recipient_name(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test sending reminder without recipient name."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="user@example.com",
            recipient_name=None,
            booking=mock_booking,
            is_partner=False,
        )

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Should use default greeting
        assert "Bonjour," in body_html or "Bonjour</p>" in body_html


class TestSendBookingFailureNotification:
    """Tests for the send_booking_failure_notification method."""

    @pytest.fixture
    def configured_service(self):
        """Create a fully configured notification service."""
        return NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

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

    @patch.object(NotificationService, "_send_email")
    def test_send_failure_notification_basic(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test sending basic failure notification."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_failure_notification(
            user=mock_user,
            error_message="No courts available",
        )

        assert result.success is True
        call_args = mock_send_email.call_args

        # _send_email is called with positional args: (to_email, subject, body_html)
        to_email = call_args[0][0]
        subject = call_args[0][1]
        body_html = call_args[0][2]

        assert to_email == mock_user.email
        assert "Échec" in subject
        assert "No courts available" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_failure_notification_with_facility(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test failure notification with facility name."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_failure_notification(
            user=mock_user,
            error_message="No courts available",
            facility_name="Tennis Club Paris",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        assert "Tennis Club Paris" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_failure_notification_with_date(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test failure notification with requested date."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_failure_notification(
            user=mock_user,
            error_message="No courts available",
            requested_date="2025-01-20",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        assert "2025-01-20" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_failure_notification_with_all_details(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test failure notification with all optional details."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_failure_notification(
            user=mock_user,
            error_message="CAPTCHA solving failed",
            facility_name="Tennis Club Paris",
            requested_date="2025-01-20",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        assert "CAPTCHA solving failed" in body_html
        assert "Tennis Club Paris" in body_html
        assert "2025-01-20" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_failure_notification_with_user_name(
        self, mock_send_email, configured_service
    ):
        """Test that failure notification uses personalized greeting with user name."""
        user_with_name = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            name="Marie Curie",
            subscription_active=True,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_failure_notification(
            user=user_with_name,
            error_message="No courts available",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]

        # Check that the greeting includes the user's name
        assert "Bonjour Marie Curie" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_failure_notification_without_user_name(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test that failure notification uses generic greeting when user has no name."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_failure_notification(
            user=mock_user,
            error_message="No courts available",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]

        # Check that the greeting is generic (just "Bonjour" without a name)
        assert "Bonjour," in body_html or ">Bonjour<" in body_html


class TestGetNotificationService:
    """Tests for the get_notification_service function."""

    def test_get_notification_service_returns_singleton(self):
        """Test that get_notification_service returns the same instance."""
        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.notification.smtp_host = "smtp.example.com"
            mock_settings.notification.smtp_port = 587
            mock_settings.notification.smtp_user = "user@example.com"
            mock_settings.notification.smtp_password = "password"
            mock_settings.notification.from_email = "noreply@example.com"

            # Reset the global instance
            import src.services.notification as notification_module
            notification_module._notification_service = None

            service1 = get_notification_service()
            service2 = get_notification_service()

            assert service1 is service2

    def test_get_notification_service_creates_instance(self):
        """Test that get_notification_service creates an instance when none exists."""
        with patch("src.services.notification.settings") as mock_settings:
            mock_settings.notification.smtp_host = "smtp.test.com"
            mock_settings.notification.smtp_port = 465
            mock_settings.notification.smtp_user = "test@test.com"
            mock_settings.notification.smtp_password = "secret"
            mock_settings.notification.from_email = "from@test.com"

            # Reset the global instance
            import src.services.notification as notification_module
            notification_module._notification_service = None

            service = get_notification_service()

            assert service is not None
            assert isinstance(service, NotificationService)
