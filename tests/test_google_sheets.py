"""Tests for Google Sheets service."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models import Booking, BookingRequest, DayOfWeek, User
from src.services.google_sheets import GoogleSheetsService


class TestGoogleSheetsService:
    """Tests for GoogleSheetsService."""

    @pytest.fixture
    def mock_service(self):
        """Create a GoogleSheetsService with mocked gspread client."""
        with patch("src.services.google_sheets.ServiceAccountCredentials") as mock_creds:
            with patch("src.services.google_sheets.gspread") as mock_gspread:
                service = GoogleSheetsService(
                    credentials_file="test_creds.json",
                    spreadsheet_id="test_spreadsheet_id",
                )
                # Setup mock client
                mock_client = MagicMock()
                mock_gspread.authorize.return_value = mock_client
                mock_spreadsheet = MagicMock()
                mock_client.open_by_key.return_value = mock_spreadsheet
                service._mock_spreadsheet = mock_spreadsheet
                yield service

    def test_get_all_users(self, mock_service):
        """Test fetching all users."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "user1",
                "email": "user1@example.com",
                "paris_tennis_email": "tennis1@example.com",
                "paris_tennis_password": "pass1",
                "subscription_active": True,
                "phone": "+33123456789",
            },
            {
                "id": "user2",
                "email": "user2@example.com",
                "paris_tennis_email": "tennis2@example.com",
                "paris_tennis_password": "pass2",
                "subscription_active": False,
                "phone": "",
            },
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        users = mock_service.get_all_users()

        assert len(users) == 2
        assert users[0].id == "user1"
        assert users[0].subscription_active is True
        assert users[1].subscription_active is False

    def test_get_eligible_users(self, mock_service):
        """Test fetching eligible users only."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "user1",
                "email": "user1@example.com",
                "paris_tennis_email": "tennis1@example.com",
                "paris_tennis_password": "pass1",
                "subscription_active": True,
            },
            {
                "id": "user2",
                "email": "user2@example.com",
                "paris_tennis_email": "tennis2@example.com",
                "paris_tennis_password": "pass2",
                "subscription_active": False,
            },
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        eligible = mock_service.get_eligible_users()

        assert len(eligible) == 1
        assert eligible[0].id == "user1"

    def test_get_all_booking_requests(self, mock_service):
        """Test fetching all booking requests."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "req1",
                "user_id": "user1",
                "day_of_week": "monday",
                "time_start": "18:00",
                "time_end": "20:00",
                "facility_preferences": "FAC001,FAC002",
                "court_type": "indoor",
                "partner_name": "Partner",
                "partner_email": "partner@example.com",
                "active": True,
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        requests = mock_service.get_all_booking_requests()

        assert len(requests) == 1
        assert requests[0].id == "req1"
        assert requests[0].day_of_week == DayOfWeek.MONDAY

    def test_get_active_booking_requests(self, mock_service):
        """Test fetching active booking requests only."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "req1",
                "user_id": "user1",
                "day_of_week": 0,
                "time_start": "18:00",
                "time_end": "20:00",
                "active": True,
            },
            {
                "id": "req2",
                "user_id": "user1",
                "day_of_week": 2,
                "time_start": "10:00",
                "time_end": "12:00",
                "active": False,
            },
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        active_requests = mock_service.get_active_booking_requests()

        assert len(active_requests) == 1
        assert active_requests[0].id == "req1"

    def test_get_all_bookings(self, mock_service):
        """Test fetching all bookings."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "book1",
                "user_id": "user1",
                "request_id": "req1",
                "facility_name": "Tennis Club",
                "facility_code": "TC001",
                "court_number": "1",
                "date": "2025-01-15T18:00:00",
                "time_start": "18:00",
                "time_end": "19:00",
                "partner_name": "Partner",
                "confirmation_id": "CONF123",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        bookings = mock_service.get_all_bookings()

        assert len(bookings) == 1
        assert bookings[0].id == "book1"
        assert bookings[0].confirmation_id == "CONF123"

    def test_add_booking(self, mock_service):
        """Test adding a new booking."""
        mock_worksheet = MagicMock()
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club",
            facility_code="TC001",
            court_number="1",
            date=datetime(2025, 1, 15, 18, 0),
            time_start="18:00",
            time_end="19:00",
            partner_name="Partner",
            confirmation_id="CONF123",
        )

        result = mock_service.add_booking(booking)

        assert result is True
        mock_worksheet.append_row.assert_called_once()
        # Verify the row content
        row = mock_worksheet.append_row.call_args[0][0]
        assert row[0] == "book1"  # id
        assert row[10] == "CONF123"  # confirmation_id
        assert row[11] == ""  # facility_address (empty string when None)

    def test_add_booking_with_facility_address(self, mock_service):
        """Test adding a booking with facility_address."""
        mock_worksheet = MagicMock()
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        booking = Booking(
            id="book1",
            user_id="user1",
            request_id="req1",
            facility_name="Tennis Club",
            facility_code="TC001",
            court_number="1",
            date=datetime(2025, 1, 15, 18, 0),
            time_start="18:00",
            time_end="19:00",
            partner_name="Partner",
            confirmation_id="CONF123",
            facility_address="123 Rue de Tennis, 75001 Paris",
        )

        result = mock_service.add_booking(booking)

        assert result is True
        mock_worksheet.append_row.assert_called_once()
        # Verify facility_address is saved in the row
        row = mock_worksheet.append_row.call_args[0][0]
        assert row[11] == "123 Rue de Tennis, 75001 Paris"

    def test_get_bookings_for_user(self, mock_service):
        """Test fetching bookings for specific user."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "book1",
                "user_id": "user1",
                "request_id": "req1",
                "facility_name": "Tennis Club",
                "facility_code": "TC001",
                "court_number": "1",
                "date": "2025-01-15T18:00:00",
                "time_start": "18:00",
                "time_end": "19:00",
            },
            {
                "id": "book2",
                "user_id": "user2",
                "request_id": "req2",
                "facility_name": "Tennis Club",
                "facility_code": "TC001",
                "court_number": "2",
                "date": "2025-01-16T18:00:00",
                "time_start": "18:00",
                "time_end": "19:00",
            },
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        user1_bookings = mock_service.get_bookings_for_user("user1")

        assert len(user1_bookings) == 1
        assert user1_bookings[0].id == "book1"

    def test_has_pending_booking(self, mock_service):
        """Test checking for pending bookings."""
        mock_worksheet = MagicMock()
        # Future booking
        future_date = datetime(2099, 12, 31, 18, 0)
        mock_worksheet.get_all_records.return_value = [
            {
                "id": "book1",
                "user_id": "user1",
                "request_id": "req1",
                "facility_name": "Tennis Club",
                "facility_code": "TC001",
                "court_number": "1",
                "date": future_date.isoformat(),
                "time_start": "18:00",
                "time_end": "19:00",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        assert mock_service.has_pending_booking("user1") is True
        assert mock_service.has_pending_booking("user2") is False


class TestUserLocking:
    """Tests for user locking functionality to prevent race conditions."""

    @pytest.fixture
    def mock_service(self):
        """Create a GoogleSheetsService with mocked gspread client."""
        with patch("src.services.google_sheets.ServiceAccountCredentials") as mock_creds:
            with patch("src.services.google_sheets.gspread") as mock_gspread:
                service = GoogleSheetsService(
                    credentials_file="test_creds.json",
                    spreadsheet_id="test_spreadsheet_id",
                )
                # Setup mock client
                mock_client = MagicMock()
                mock_gspread.authorize.return_value = mock_client
                mock_spreadsheet = MagicMock()
                mock_client.open_by_key.return_value = mock_spreadsheet
                service._mock_spreadsheet = mock_spreadsheet
                yield service

    def test_acquire_lock_success_no_existing_lock(self, mock_service):
        """Test acquiring a lock when no lock exists."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = []
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.acquire_user_lock("user1", "job-123")

        assert result is True
        mock_worksheet.append_row.assert_called_once()
        call_args = mock_worksheet.append_row.call_args[0][0]
        assert call_args[0] == "user1"
        assert call_args[2] == "job-123"

    def test_acquire_lock_fails_when_user_already_locked(self, mock_service):
        """Test acquiring a lock fails when user is already locked."""
        mock_worksheet = MagicMock()
        # Lock acquired 1 minute ago (still valid)
        locked_at = datetime.now().isoformat()
        mock_worksheet.get_all_records.return_value = [
            {
                "user_id": "user1",
                "locked_at": locked_at,
                "locked_by": "other-job-456",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.acquire_user_lock("user1", "job-123")

        assert result is False
        mock_worksheet.append_row.assert_not_called()

    def test_acquire_lock_success_for_different_user(self, mock_service):
        """Test acquiring a lock for a different user succeeds."""
        mock_worksheet = MagicMock()
        # User2 is locked, but we're trying to lock user1
        locked_at = datetime.now().isoformat()
        mock_worksheet.get_all_records.return_value = [
            {
                "user_id": "user2",
                "locked_at": locked_at,
                "locked_by": "other-job-456",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.acquire_user_lock("user1", "job-123")

        assert result is True
        mock_worksheet.append_row.assert_called_once()

    def test_acquire_lock_success_when_existing_lock_expired(self, mock_service):
        """Test acquiring a lock succeeds when existing lock has expired."""
        mock_worksheet = MagicMock()
        # Lock acquired 10 minutes ago (expired - timeout is 5 minutes)
        from datetime import timedelta
        expired_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        mock_worksheet.get_all_records.return_value = [
            {
                "user_id": "user1",
                "locked_at": expired_time,
                "locked_by": "old-job-456",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.acquire_user_lock("user1", "job-123")

        assert result is True
        # Should update the existing row, not append
        mock_worksheet.update_cell.assert_called()

    def test_release_lock_success(self, mock_service):
        """Test releasing a lock owned by the job."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "user_id": "user1",
                "locked_at": datetime.now().isoformat(),
                "locked_by": "job-123",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.release_user_lock("user1", "job-123")

        assert result is True
        mock_worksheet.delete_rows.assert_called_once_with(2)  # Row 2 (header is row 1)

    def test_release_lock_fails_when_owned_by_other_job(self, mock_service):
        """Test releasing a lock fails when owned by different job."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = [
            {
                "user_id": "user1",
                "locked_at": datetime.now().isoformat(),
                "locked_by": "other-job-456",
            }
        ]
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.release_user_lock("user1", "job-123")

        assert result is False
        mock_worksheet.delete_rows.assert_not_called()

    def test_release_lock_success_when_no_lock_exists(self, mock_service):
        """Test releasing a non-existent lock succeeds (idempotent)."""
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_records.return_value = []
        mock_service._mock_spreadsheet.worksheet.return_value = mock_worksheet

        result = mock_service.release_user_lock("user1", "job-123")

        assert result is True
        mock_worksheet.delete_rows.assert_not_called()

    def test_ensure_locks_sheet_creates_sheet_if_not_found(self):
        """Test that _ensure_locks_sheet creates the sheet if it doesn't exist."""
        import gspread
        from gspread.exceptions import WorksheetNotFound

        # Create a fresh service without patching gspread module completely
        with patch("src.services.google_sheets.ServiceAccountCredentials"):
            with patch("src.services.google_sheets.gspread.authorize") as mock_authorize:
                service = GoogleSheetsService(
                    credentials_file="test_creds.json",
                    spreadsheet_id="test_spreadsheet_id",
                )
                mock_client = MagicMock()
                mock_authorize.return_value = mock_client
                mock_spreadsheet = MagicMock()
                mock_client.open_by_key.return_value = mock_spreadsheet

                mock_new_worksheet = MagicMock()
                mock_spreadsheet.worksheet.side_effect = WorksheetNotFound("Locks")
                mock_spreadsheet.add_worksheet.return_value = mock_new_worksheet

                result = service._ensure_locks_sheet()

                assert result == mock_new_worksheet
                mock_spreadsheet.add_worksheet.assert_called_once_with(
                    title="Locks", rows=100, cols=3
                )
                mock_new_worksheet.append_row.assert_called_once_with(
                    ["user_id", "locked_at", "locked_by"]
                )
