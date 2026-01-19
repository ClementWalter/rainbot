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

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_with_facility_address(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test that booking confirmation includes facility address when available."""
        booking_with_address = Booking(
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
            facility_address="15 Rue du Tennis, 75001 Paris",
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(mock_user, booking_with_address)

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Check that the address is included in the email
        assert "15 Rue du Tennis, 75001 Paris" in body_html
        assert "Adresse" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_booking_confirmation_without_facility_address(
        self, mock_send_email, configured_service, mock_user, mock_booking
    ):
        """Test that booking confirmation works when facility address is not available."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_booking_confirmation(mock_user, mock_booking)

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Address row should not be present when no address is set
        assert "Adresse :" not in body_html


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

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_with_facility_address(
        self, mock_send_email, configured_service
    ):
        """Test that reminder includes facility address when available."""
        booking_with_address = Booking(
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
            facility_address="15 Rue du Tennis, 75001 Paris",
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="user@example.com",
            recipient_name="Pierre Martin",
            booking=booking_with_address,
            is_partner=False,
        )

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Check that the address is included in the email
        assert "15 Rue du Tennis, 75001 Paris" in body_html
        assert "Adresse" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_without_facility_address(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test that reminder works when facility address is not available."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="user@example.com",
            recipient_name="Pierre Martin",
            booking=mock_booking,
            is_partner=False,
        )

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Address row should not be present when no address is set
        assert "Adresse" not in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_to_partner_shows_player_name(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test that partner reminder shows the user's name, not the partner's own name."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="partner@example.com",
            recipient_name="Jean Dupont",  # Partner's name (recipient)
            booking=mock_booking,  # booking.partner_name is also "Jean Dupont"
            is_partner=True,
            player_name="Pierre Martin",  # The user who made the booking
        )

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # The email should say "match with Pierre Martin" (the user), not the partner's own name
        assert "avec Pierre Martin" in body_html
        # The greeting should use the partner's name (recipient)
        assert "Bonjour Jean Dupont" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_reminder_to_partner_without_player_name_uses_fallback(
        self, mock_send_email, configured_service, mock_booking
    ):
        """Test that partner reminder uses fallback when player_name is not provided."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_match_day_reminder(
            recipient_email="partner@example.com",
            recipient_name="Jean Dupont",
            booking=mock_booking,
            is_partner=True,
            player_name=None,  # No player name provided
        )

        assert result.success is True
        call_args = mock_send_email.call_args
        body_html = call_args[0][2]

        # Should use the fallback text
        assert "avec votre partenaire" in body_html


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


class TestSendNoSlotsNotification:
    """Tests for the send_no_slots_notification method."""

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
    def test_send_no_slots_notification_basic(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test sending basic no slots notification."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_no_slots_notification(
            user=mock_user,
            day_of_week="lundi",
            time_range="18:00 - 20:00",
        )

        assert result.success is True
        call_args = mock_send_email.call_args

        to_email = call_args[0][0]
        subject = call_args[0][1]
        body_html = call_args[0][2]

        assert to_email == mock_user.email
        assert "Aucun créneau" in subject
        assert "lundi" in body_html
        assert "18:00 - 20:00" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_no_slots_notification_with_facilities(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test no slots notification with facility names."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_no_slots_notification(
            user=mock_user,
            day_of_week="mercredi",
            time_range="10:00 - 12:00",
            facility_names=["Tennis Club Paris", "Centre Suzanne Lenglen"],
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        assert "Tennis Club Paris" in body_html
        assert "Centre Suzanne Lenglen" in body_html
        assert "Centres recherchés" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_no_slots_notification_without_facilities(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test no slots notification without facility names."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_no_slots_notification(
            user=mock_user,
            day_of_week="vendredi",
            time_range="14:00 - 16:00",
            facility_names=None,
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        # Should not contain the facilities section
        assert "Centres recherchés" not in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_no_slots_notification_with_user_name(
        self, mock_send_email, configured_service
    ):
        """Test that no slots notification uses personalized greeting."""
        user_with_name = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            name="Sophie Germain",
            subscription_active=True,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_no_slots_notification(
            user=user_with_name,
            day_of_week="samedi",
            time_range="09:00 - 11:00",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        assert "Bonjour Sophie Germain" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_send_no_slots_notification_contains_retry_message(
        self, mock_send_email, configured_service, mock_user
    ):
        """Test that no slots notification contains reassuring retry message."""
        mock_send_email.return_value = NotificationResult(success=True)

        result = configured_service.send_no_slots_notification(
            user=mock_user,
            day_of_week="dimanche",
            time_range="16:00 - 18:00",
        )

        assert result.success is True
        body_html = mock_send_email.call_args[0][2]
        # Should contain reassuring message about automatic retries
        assert "continuera à chercher" in body_html or "automatiquement" in body_html


class TestHtmlEscaping:
    """Tests for HTML injection prevention in notification emails."""

    @pytest.fixture
    def configured_service(self):
        """Create a configured notification service."""
        return NotificationService(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user@example.com",
            smtp_password="password",
            from_email="noreply@example.com",
        )

    @patch.object(NotificationService, "_send_email")
    def test_booking_confirmation_escapes_user_name(
        self, mock_send_email, configured_service
    ):
        """Test that user name is escaped in booking confirmation."""
        malicious_user = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            name="<script>alert('XSS')</script>",
            subscription_active=True,
        )
        booking = Booking(
            id="booking1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Center",
            facility_code="TC01",
            court_number="1",
            date=datetime(2024, 3, 15, 14, 0),
            time_start="14:00",
            time_end="15:00",
        )
        mock_send_email.return_value = NotificationResult(success=True)

        configured_service.send_booking_confirmation(malicious_user, booking)

        body_html = mock_send_email.call_args[0][2]
        # The script tag should be escaped, not rendered
        assert "<script>" not in body_html
        assert "&lt;script&gt;" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_booking_confirmation_escapes_facility_name(
        self, mock_send_email, configured_service
    ):
        """Test that facility name is escaped in booking confirmation."""
        user = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            subscription_active=True,
        )
        booking = Booking(
            id="booking1",
            user_id="user1",
            request_id="req1",
            facility_name="<img src=x onerror=alert('XSS')>",
            facility_code="TC01",
            court_number="1",
            date=datetime(2024, 3, 15, 14, 0),
            time_start="14:00",
            time_end="15:00",
        )
        mock_send_email.return_value = NotificationResult(success=True)

        configured_service.send_booking_confirmation(user, booking)

        body_html = mock_send_email.call_args[0][2]
        # The img tag should be escaped
        assert "<img" not in body_html
        assert "&lt;img" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_match_day_reminder_escapes_partner_name(
        self, mock_send_email, configured_service
    ):
        """Test that partner name is escaped in match day reminder."""
        booking = Booking(
            id="booking1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Center",
            facility_code="TC01",
            court_number="1",
            date=datetime(2024, 3, 15, 14, 0),
            time_start="14:00",
            time_end="15:00",
            partner_name="<b onmouseover=alert('XSS')>Malicious</b>",
        )
        mock_send_email.return_value = NotificationResult(success=True)

        configured_service.send_match_day_reminder(
            recipient_email="user@example.com",
            recipient_name="Test User",
            booking=booking,
            is_partner=False,
        )

        body_html = mock_send_email.call_args[0][2]
        # The opening tag should be escaped (< becomes &lt;)
        # This prevents the browser from interpreting it as an HTML tag
        assert "<b onmouseover" not in body_html
        assert "&lt;b" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_failure_notification_escapes_error_message(
        self, mock_send_email, configured_service
    ):
        """Test that error message is escaped in failure notification."""
        user = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            subscription_active=True,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        configured_service.send_booking_failure_notification(
            user=user,
            error_message="<div style='position:fixed;top:0;left:0;width:100%'>Phishing</div>",
        )

        body_html = mock_send_email.call_args[0][2]
        # The div tag should be escaped
        assert "position:fixed" not in body_html or "&lt;div" in body_html

    @patch.object(NotificationService, "_send_email")
    def test_no_slots_notification_escapes_facility_names(
        self, mock_send_email, configured_service
    ):
        """Test that facility names list is escaped in no slots notification."""
        user = User(
            id="user1",
            email="user@example.com",
            paris_tennis_email="tennis@example.com",
            paris_tennis_password="password123",
            subscription_active=True,
        )
        mock_send_email.return_value = NotificationResult(success=True)

        configured_service.send_no_slots_notification(
            user=user,
            day_of_week="lundi",
            time_range="18:00 - 20:00",
            facility_names=["Safe Facility", "<script>evil()</script>"],
        )

        body_html = mock_send_email.call_args[0][2]
        # The script tag in facility names should be escaped
        assert "<script>evil()</script>" not in body_html
        assert "&lt;script&gt;" in body_html


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
