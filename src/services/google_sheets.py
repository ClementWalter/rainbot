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

        Args:
            user_id: The user's unique identifier

        Returns:
            True if user has a future booking, False otherwise
        """
        today = datetime.now().date()
        user_bookings = self.get_bookings_for_user(user_id)
        return any(b.date.date() >= today for b in user_bookings)


# Global service instance
sheets_service = GoogleSheetsService()
