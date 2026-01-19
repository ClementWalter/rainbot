"""Google Sheets service for reading/writing user and booking data."""

import logging
from datetime import datetime
from typing import Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from src.config.settings import settings
from src.models.booking import Booking
from src.models.booking_request import BookingRequest
from src.models.user import User
from src.utils.timezone import now_paris, today_paris

logger = logging.getLogger(__name__)

# Google Sheets API scopes
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Expected worksheet names in the spreadsheet
USERS_SHEET = "Users"
BOOKING_REQUESTS_SHEET = "BookingRequests"
BOOKINGS_SHEET = "Bookings"
LOCKS_SHEET = "Locks"

# Lock configuration
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes - locks expire after this time


class GoogleSheetsService:
    """
    Service for interacting with Google Sheets data store.

    Expected spreadsheet structure:
    - Users sheet: id, name, email, paris_tennis_email, paris_tennis_password, subscription_active, phone
    - BookingRequests sheet: id, user_id, day_of_week, time_start, time_end,
                             facility_preferences, court_type, partner_name, partner_email, active
    - Bookings sheet: id, user_id, request_id, facility_name, facility_code, court_number,
                      date, time_start, time_end, partner_name, confirmation_id, created_at
    """

    def __init__(
        self,
        credentials_file: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        """
        Initialize the Google Sheets service.

        Args:
            credentials_file: Path to Google service account credentials JSON
            spreadsheet_id: ID of the Google Spreadsheet to use
        """
        self.credentials_file = credentials_file or settings.google_sheets.credentials_file
        self.spreadsheet_id = spreadsheet_id or settings.google_sheets.spreadsheet_id
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None

    def _get_client(self) -> gspread.Client:
        """Get or create the gspread client."""
        if self._client is None:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(
                self.credentials_file, SCOPES
            )
            self._client = gspread.authorize(credentials)
        return self._client

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        """Get the spreadsheet instance."""
        if self._spreadsheet is None:
            client = self._get_client()
            self._spreadsheet = client.open_by_key(self.spreadsheet_id)
        return self._spreadsheet

    def _get_worksheet(self, name: str) -> gspread.Worksheet:
        """Get a worksheet by name."""
        spreadsheet = self._get_spreadsheet()
        return spreadsheet.worksheet(name)

    def get_all_users(self) -> list[User]:
        """
        Fetch all users from the Users sheet.

        Returns:
            List of User objects
        """
        try:
            worksheet = self._get_worksheet(USERS_SHEET)
            records = worksheet.get_all_records()
            users = []
            for record in records:
                try:
                    user = User(
                        id=str(record.get("id", "")),
                        email=str(record.get("email", "")),
                        paris_tennis_email=str(record.get("paris_tennis_email", "")),
                        paris_tennis_password=str(record.get("paris_tennis_password", "")),
                        name=record.get("name") or None,
                        subscription_active=record.get("subscription_active", True)
                        in (True, "true", "True", "1", 1),
                        phone=record.get("phone") or None,
                    )
                    users.append(user)
                except Exception as e:
                    logger.warning(f"Failed to parse user record: {record}, error: {e}")
            return users
        except Exception as e:
            logger.error(f"Failed to fetch users: {e}")
            return []

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Fetch a specific user by ID.

        Args:
            user_id: The user's unique identifier

        Returns:
            User object or None if not found
        """
        users = self.get_all_users()
        for user in users:
            if user.id == user_id:
                return user
        return None

    def get_eligible_users(self) -> list[User]:
        """
        Fetch all users who are eligible for booking.

        Returns:
            List of eligible User objects (active subscription, valid credentials)
        """
        return [user for user in self.get_all_users() if user.is_eligible()]

    def get_all_booking_requests(self) -> list[BookingRequest]:
        """
        Fetch all booking requests from the BookingRequests sheet.

        Returns:
            List of BookingRequest objects
        """
        try:
            worksheet = self._get_worksheet(BOOKING_REQUESTS_SHEET)
            records = worksheet.get_all_records()
            requests = []
            for record in records:
                try:
                    request = BookingRequest.from_dict(record)
                    requests.append(request)
                except Exception as e:
                    logger.warning(f"Failed to parse booking request: {record}, error: {e}")
            return requests
        except Exception as e:
            logger.error(f"Failed to fetch booking requests: {e}")
            return []

    def get_active_booking_requests(self) -> list[BookingRequest]:
        """
        Fetch all active booking requests.

        Returns:
            List of active BookingRequest objects
        """
        return [req for req in self.get_all_booking_requests() if req.active]

    def get_booking_requests_for_user(self, user_id: str) -> list[BookingRequest]:
        """
        Fetch booking requests for a specific user.

        Args:
            user_id: The user's unique identifier

        Returns:
            List of BookingRequest objects for the user
        """
        return [req for req in self.get_all_booking_requests() if req.user_id == user_id]

    def get_all_bookings(self) -> list[Booking]:
        """
        Fetch all completed bookings from the Bookings sheet.

        Returns:
            List of Booking objects
        """
        try:
            worksheet = self._get_worksheet(BOOKINGS_SHEET)
            records = worksheet.get_all_records()
            bookings = []
            for record in records:
                try:
                    booking = Booking.from_dict(record)
                    bookings.append(booking)
                except Exception as e:
                    logger.warning(f"Failed to parse booking: {record}, error: {e}")
            return bookings
        except Exception as e:
            logger.error(f"Failed to fetch bookings: {e}")
            return []

    def get_bookings_for_user(self, user_id: str) -> list[Booking]:
        """
        Fetch bookings for a specific user.

        Args:
            user_id: The user's unique identifier

        Returns:
            List of Booking objects for the user
        """
        return [b for b in self.get_all_bookings() if b.user_id == user_id]

    def get_todays_bookings(self) -> list[Booking]:
        """
        Fetch all bookings scheduled for today.

        Returns:
            List of Booking objects for today
        """
        return [b for b in self.get_all_bookings() if b.is_today()]

    def add_booking(self, booking: Booking) -> bool:
        """
        Add a new booking to the Bookings sheet.

        Args:
            booking: The Booking object to add

        Returns:
            True if successful, False otherwise
        """
        try:
            worksheet = self._get_worksheet(BOOKINGS_SHEET)
            row = [
                booking.id,
                booking.user_id,
                booking.request_id,
                booking.facility_name,
                booking.facility_code,
                booking.court_number,
                booking.date.isoformat() if isinstance(booking.date, datetime) else booking.date,
                booking.time_start,
                booking.time_end,
                booking.partner_name or "",
                booking.confirmation_id or "",
                booking.facility_address or "",
                booking.created_at.isoformat()
                if isinstance(booking.created_at, datetime)
                else str(booking.created_at),
            ]
            worksheet.append_row(row)
            logger.info(f"Added booking {booking.id} to spreadsheet")
            return True
        except Exception as e:
            logger.error(f"Failed to add booking: {e}")
            return False

    def has_pending_booking(self, user_id: str) -> bool:
        """
        Check if a user has a pending booking (future booking).

        A booking is considered "pending" if:
        - The booking date is in the future (date > today), OR
        - The booking is today AND the end time hasn't passed yet

        Args:
            user_id: The user's unique identifier

        Returns:
            True if user has a pending booking, False otherwise
        """
        today = today_paris()
        now = now_paris()
        current_time = now.strftime("%H:%M")
        user_bookings = self.get_bookings_for_user(user_id)

        for booking in user_bookings:
            booking_date = booking.date.date()
            if booking_date > today:
                # Future date - definitely pending
                return True
            if booking_date == today:
                # Today's booking - check if end time has passed
                # Normalize time_end for comparison (handle both "9:00" and "09:00")
                from src.models.booking_request import normalize_time

                booking_end = normalize_time(booking.time_end)
                if booking_end and booking_end > current_time:
                    return True

        return False

    def _ensure_locks_sheet(self) -> gspread.Worksheet:
        """
        Ensure the Locks worksheet exists, creating it if necessary.

        Returns:
            The Locks worksheet
        """
        spreadsheet = self._get_spreadsheet()
        try:
            return spreadsheet.worksheet(LOCKS_SHEET)
        except gspread.WorksheetNotFound:
            # Create the Locks sheet with headers
            worksheet = spreadsheet.add_worksheet(title=LOCKS_SHEET, rows=100, cols=3)
            worksheet.append_row(["user_id", "locked_at", "locked_by"])
            logger.info("Created Locks worksheet")
            return worksheet

    def acquire_user_lock(self, user_id: str, job_id: str) -> bool:
        """
        Attempt to acquire a lock for processing a user's booking request.

        This prevents multiple concurrent booking jobs from processing the same user,
        which could result in duplicate bookings.

        Args:
            user_id: The user's unique identifier
            job_id: Unique identifier for this job instance

        Returns:
            True if lock was acquired, False if user is already locked
        """
        try:
            worksheet = self._ensure_locks_sheet()
            records = worksheet.get_all_records()
            now = now_paris()

            # Check for existing lock
            for idx, record in enumerate(records):
                if str(record.get("user_id", "")) == user_id:
                    # Check if lock has expired
                    locked_at_str = record.get("locked_at", "")
                    if locked_at_str:
                        try:
                            locked_at = datetime.fromisoformat(locked_at_str)
                            # Handle naive datetime from old lock records by assuming Paris TZ
                            if locked_at.tzinfo is None:
                                from src.utils.timezone import PARIS_TZ

                                locked_at = PARIS_TZ.localize(locked_at)
                            age_seconds = (now - locked_at).total_seconds()
                            if age_seconds < LOCK_TIMEOUT_SECONDS:
                                # Lock is still valid
                                logger.debug(
                                    f"User {user_id} is locked by {record.get('locked_by')}, "
                                    f"age: {age_seconds:.0f}s"
                                )
                                return False
                            # Lock has expired, update it
                            logger.info(
                                f"Expired lock for user {user_id} found, acquiring new lock"
                            )
                            row_num = idx + 2  # +2 for header and 0-based index
                            worksheet.update_cell(row_num, 2, now.isoformat())
                            worksheet.update_cell(row_num, 3, job_id)
                            return True
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Invalid locked_at value: {locked_at_str}, error: {e}")
                            # Treat invalid lock as expired
                            row_num = idx + 2
                            worksheet.update_cell(row_num, 2, now.isoformat())
                            worksheet.update_cell(row_num, 3, job_id)
                            return True

            # No existing lock, create new one
            worksheet.append_row([user_id, now.isoformat(), job_id])
            logger.debug(f"Acquired lock for user {user_id}, job {job_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to acquire lock for user {user_id}: {e}")
            # On error, don't proceed with booking to avoid duplicates
            return False

    def release_user_lock(self, user_id: str, job_id: str) -> bool:
        """
        Release a lock for a user.

        Only the job that acquired the lock can release it.

        Args:
            user_id: The user's unique identifier
            job_id: Unique identifier for this job instance

        Returns:
            True if lock was released, False otherwise
        """
        try:
            worksheet = self._ensure_locks_sheet()
            records = worksheet.get_all_records()

            for idx, record in enumerate(records):
                if str(record.get("user_id", "")) == user_id:
                    if record.get("locked_by") == job_id:
                        # Delete the row (idx + 2 for header and 0-based index)
                        worksheet.delete_rows(idx + 2)
                        logger.debug(f"Released lock for user {user_id}, job {job_id}")
                        return True
                    else:
                        logger.warning(
                            f"Lock for user {user_id} owned by {record.get('locked_by')}, "
                            f"not {job_id}"
                        )
                        return False

            # No lock found - this is fine, might have been released already
            logger.debug(f"No lock found for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to release lock for user {user_id}: {e}")
            return False


# Global service instance
sheets_service = GoogleSheetsService()
