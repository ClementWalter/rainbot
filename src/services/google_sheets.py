"""Google Sheets service for reading/writing user and booking data."""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from src.config.settings import settings
from src.models.booking import Booking
from src.models.booking_request import BookingRequest
from src.models.user import User
from src.services.booking_history import (
    export_booking_history_csv as build_booking_history_csv,
)
from src.utils.timezone import now_paris, today_paris

logger = logging.getLogger(__name__)

# Google Sheets API scopes
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Users are stored in a separate spreadsheet
USERS_SPREADSHEET_ID = "1oXsssBH_1jj_1NiWralBEpvXTT2a21mGMZqSGMV2Shc"
USERS_SHEET = "Users"  # Source of truth for allowed users and credentials

# Expected worksheet names in the main spreadsheet
BOOKING_REQUESTS_SHEET = "Requests"  # Actual sheet name
BOOKINGS_SHEET = "Historique"  # For booking history
LOCKS_SHEET = "Locks"
NO_SLOTS_NOTIFICATIONS_SHEET = "NoSlotsNotifications"

# French day name mapping
FRENCH_DAYS = {
    "Lundi": 0,  # Monday
    "Mardi": 1,  # Tuesday
    "Mercredi": 2,  # Wednesday
    "Jeudi": 3,  # Thursday
    "Vendredi": 4,  # Friday
    "Samedi": 5,  # Saturday
    "Dimanche": 6,  # Sunday
}

# Lock configuration
LOCK_TIMEOUT_SECONDS = 300  # 5 minutes - locks expire after this time


class GoogleSheetsService:
    """
    Service for interacting with Google Sheets data store.

    Expected spreadsheet structure:
    - Users sheet: id, name, email, paris_tennis_email, paris_tennis_password, subscription_active,
                   carnet_balance, phone
    - BookingRequests sheet: id, user_id, day_of_week, time_start, time_end,
                             facility_preferences, court_type, partner_name, partner_email, active
    - Bookings sheet: id, user_id, request_id, facility_name, facility_code, court_number,
                      date, time_start, time_end, partner_name, partner_email, confirmation_id,
                      facility_address, created_at
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
            # Try loading credentials from CLIENT_SECRET env var (JSON string) first
            client_secret = os.getenv("CLIENT_SECRET")
            if client_secret:
                try:
                    creds_dict = json.loads(client_secret)
                    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
                        creds_dict, SCOPES
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse CLIENT_SECRET: {e}, falling back to file")
                    credentials = ServiceAccountCredentials.from_json_keyfile_name(
                        self.credentials_file, SCOPES
                    )
            else:
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

    def _get_users_spreadsheet(self) -> gspread.Spreadsheet:
        """Get the separate users spreadsheet."""
        client = self._get_client()
        return client.open_by_key(USERS_SPREADSHEET_ID)

    def get_all_users(self) -> list[User]:
        """
        Fetch all users from the Users spreadsheet (separate from main data).

        Users spreadsheet columns: Username, Password, Photo, Prénom, Nom, Phone

        Returns:
            List of User objects with per-user credentials

        """
        try:
            # Users are in a separate spreadsheet
            users_spreadsheet = self._get_users_spreadsheet()
            worksheet = users_spreadsheet.worksheet(USERS_SHEET)
            all_rows = worksheet.get_all_values()
            if len(all_rows) < 2:
                return []

            # Get header row to map column names
            headers = [h.strip().lower().replace(" ", "_") for h in all_rows[0]]

            users = []
            for row in all_rows[1:]:
                if not row or not any(cell.strip() for cell in row):
                    continue  # Skip empty rows

                # Create dict from row using headers
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        row_dict[header] = row[i].strip() if row[i] else ""

                # Map columns: Username, Password, Photo, Prénom, Nom, Phone
                email = row_dict.get("username", "")
                prenom = row_dict.get("prénom", "")
                nom = row_dict.get("nom", "")
                name = f"{prenom} {nom}".strip() if prenom or nom else email.split("@")[0]

                user_data = {
                    "id": email,
                    "name": name,
                    "email": email,
                    "paris_tennis_email": email,
                    "paris_tennis_password": row_dict.get("password", ""),
                    "subscription_active": "true",  # All users in sheet are active
                    "carnet_balance": "",
                    "phone": row_dict.get("phone", ""),
                }

                # Only include users with valid email and password
                if user_data["email"] and user_data["paris_tennis_password"]:
                    user = User.from_dict(user_data)
                    users.append(user)

            logger.info(f"Loaded {len(users)} users from Users spreadsheet")
            return users
        except Exception as e:
            logger.error(f"Failed to fetch users from Users spreadsheet: {e}")
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

    def update_user_carnet_balance(self, user_id: str, new_balance: int) -> bool:
        """
        Update a user's carnet balance in the Users sheet.

        Args:
            user_id: The user's unique identifier
            new_balance: New carnet balance value to store

        Returns:
            True if the balance was updated, False otherwise

        """
        try:
            worksheet = self._get_worksheet(USERS_SHEET)
            headers = worksheet.row_values(1)
            if not headers:
                logger.error("Users sheet missing header row; cannot update carnet balance")
                return False

            try:
                balance_col = headers.index("carnet_balance") + 1
            except ValueError:
                logger.error("Users sheet missing 'carnet_balance' column")
                return False

            records = worksheet.get_all_records()
            for idx, record in enumerate(records):
                if str(record.get("id", "")) == user_id:
                    row_num = idx + 2  # +2 for header row and 0-based index
                    worksheet.update_cell(row_num, balance_col, new_balance)
                    logger.info(
                        "Updated carnet balance for user %s to %s",
                        user_id,
                        new_balance,
                    )
                    return True

            logger.warning("User %s not found in Users sheet", user_id)
            return False

        except Exception as e:
            logger.error(f"Failed to update carnet balance for user {user_id}: {e}")
            return False

    def get_eligible_users(self) -> list[User]:
        """
        Fetch all users who are eligible for booking.

        Returns:
            List of eligible User objects (active subscription, valid credentials)

        """
        return [user for user in self.get_all_users() if user.is_eligible()]

    def get_all_booking_requests(self) -> list[BookingRequest]:
        """
        Fetch all booking requests from the Requests sheet.

        Maps actual sheet columns to BookingRequest fields:
        - Username -> user_id
        - MatchDay -> day_of_week (French day names supported)
        - HourFrom -> time_start (converted to HH:00)
        - HourTo -> time_end (converted to HH:00)
        - InOut -> court_type (Couvert=indoor, Découvert=outdoor)
        - Active -> active
        - RowID -> id
        - Court_0..Court_4 -> facility_preferences
        - Partenaire/full name -> partner_name

        Returns:
            List of BookingRequest objects

        """
        try:
            worksheet = self._get_worksheet(BOOKING_REQUESTS_SHEET)
            records = worksheet.get_all_records()
            requests = []
            for record in records:
                try:
                    # Map actual column names to expected BookingRequest fields
                    hour_from = record.get("HourFrom", "8")
                    hour_to = record.get("HourTo", "22")

                    # Convert hour numbers to HH:00 format
                    time_start = f"{int(hour_from):02d}:00" if hour_from else "08:00"
                    time_end = f"{int(hour_to):02d}:00" if hour_to else "22:00"

                    # Map InOut to court_type
                    in_out = str(record.get("InOut", "")).strip().lower()
                    if "couvert" in in_out and "découvert" not in in_out:
                        court_type = "indoor"
                    elif "découvert" in in_out or "decouvert" in in_out:
                        court_type = "outdoor"
                    else:
                        court_type = "any"

                    # Collect facility preferences from Court_0 to Court_4
                    facilities = []
                    for i in range(5):
                        facility = record.get(f"Court_{i}", "")
                        if facility and str(facility).strip():
                            facilities.append(str(facility).strip())

                    mapped_record = {
                        "id": record.get("RowID", ""),
                        "user_id": record.get("Username", ""),
                        "day_of_week": record.get("MatchDay", ""),
                        "time_start": time_start,
                        "time_end": time_end,
                        "court_type": court_type,
                        "facility_preferences": facilities,
                        "partner_name": record.get("Partenaire/full name", ""),
                        "active": record.get("Active", False),
                    }

                    request = BookingRequest.from_dict(mapped_record)
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

    def export_booking_history_csv(
        self,
        user_id: Optional[str] = None,
        sort_desc: bool = True,
    ) -> str:
        """
        Export booking history as CSV for a user or all users.

        Args:
            user_id: Optional user ID to filter bookings. When None, exports all bookings.
            sort_desc: Sort by most recent date/time first when True.

        Returns:
            CSV string with headers and rows.

        """
        if user_id:
            bookings = self.get_bookings_for_user(user_id)
        else:
            bookings = self.get_all_bookings()
        return build_booking_history_csv(bookings, sort_desc=sort_desc)

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
                booking.partner_email or "",
                booking.confirmation_id or "",
                booking.facility_address or "",
                (
                    booking.created_at.isoformat()
                    if isinstance(booking.created_at, datetime)
                    else str(booking.created_at)
                ),
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
                if booking_end:
                    if booking_end > current_time:
                        return True
                else:
                    # Missing/invalid end time: treat as pending to avoid duplicates
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

    def _ensure_no_slots_notifications_sheet(self) -> gspread.Worksheet:
        """
        Ensure the NoSlotsNotifications worksheet exists, creating it if necessary.

        This sheet tracks when "no slots available" notifications were sent to avoid
        spamming users with repeated notifications.

        Returns:
            The NoSlotsNotifications worksheet

        """
        spreadsheet = self._get_spreadsheet()
        try:
            return spreadsheet.worksheet(NO_SLOTS_NOTIFICATIONS_SHEET)
        except gspread.WorksheetNotFound:
            # Create the sheet with headers
            worksheet = spreadsheet.add_worksheet(
                title=NO_SLOTS_NOTIFICATIONS_SHEET, rows=100, cols=3
            )
            worksheet.append_row(["request_id", "target_date", "sent_at"])
            logger.info("Created NoSlotsNotifications worksheet")
            return worksheet

    def was_no_slots_notification_sent(self, request_id: str, target_date: str) -> bool:
        """
        Check if a "no slots" notification was already sent for a request and date.

        This prevents spamming users with repeated "no slots available" notifications
        when the booking job runs frequently.

        Args:
            request_id: The booking request ID
            target_date: The target booking date (YYYY-MM-DD format)

        Returns:
            True if notification was already sent, False otherwise

        """
        try:
            worksheet = self._ensure_no_slots_notifications_sheet()
            records = worksheet.get_all_records()

            for record in records:
                if (
                    str(record.get("request_id", "")) == request_id
                    and str(record.get("target_date", "")) == target_date
                ):
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to check no slots notification status: {e}")
            # On error, err on the side of not sending (assume it was sent)
            return True

    def mark_no_slots_notification_sent(self, request_id: str, target_date: str) -> bool:
        """
        Record that a "no slots" notification was sent for a request and date.

        Args:
            request_id: The booking request ID
            target_date: The target booking date (YYYY-MM-DD format)

        Returns:
            True if successfully recorded, False otherwise

        """
        try:
            worksheet = self._ensure_no_slots_notifications_sheet()
            now = now_paris()
            worksheet.append_row([request_id, target_date, now.isoformat()])
            logger.debug(
                f"Marked no slots notification sent for request {request_id}, "
                f"date {target_date}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to mark no slots notification sent: {e}")
            return False

    def cleanup_old_no_slots_notifications(self, days_to_keep: int = 7) -> int:
        """
        Remove old "no slots" notification records to keep the sheet manageable.

        Args:
            days_to_keep: Number of days of records to keep

        Returns:
            Number of records deleted

        """
        try:
            worksheet = self._ensure_no_slots_notifications_sheet()
            records = worksheet.get_all_records()
            now = now_paris()
            cutoff = now - timedelta(days=days_to_keep)
            deleted = 0

            # Iterate in reverse to avoid index shifting issues when deleting
            for idx in range(len(records) - 1, -1, -1):
                record = records[idx]
                sent_at_str = record.get("sent_at", "")
                if sent_at_str:
                    try:
                        sent_at = datetime.fromisoformat(sent_at_str)
                        if sent_at.tzinfo is None:
                            from src.utils.timezone import PARIS_TZ

                            sent_at = PARIS_TZ.localize(sent_at)
                        if sent_at < cutoff:
                            worksheet.delete_rows(idx + 2)  # +2 for header and 0-index
                            deleted += 1
                    except (ValueError, TypeError):
                        # Invalid date, delete it
                        worksheet.delete_rows(idx + 2)
                        deleted += 1

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old no slots notification records")
            return deleted

        except Exception as e:
            logger.error(f"Failed to cleanup old no slots notifications: {e}")
            return 0

    def add_booking_request(self, request: BookingRequest) -> bool:
        """
        Add a new booking request to the Requests sheet.

        Args:
            request: The BookingRequest to add

        Returns:
            True if successfully added, False otherwise

        """
        try:
            worksheet = self._get_worksheet(BOOKING_REQUESTS_SHEET)

            # Map day_of_week value to French name
            day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            day_name = day_names[request.day_of_week.value]

            # Extract hour from time string (e.g., "18:00" -> 18)
            hour_from = int(request.time_start.split(":")[0])
            hour_to = int(request.time_end.split(":")[0])

            # Map court_type to French
            court_type_map = {"indoor": "Couvert", "outdoor": "Découvert", "any": ""}
            in_out = court_type_map.get(request.court_type.value, "")

            # Build row with all columns in the expected order
            # Columns: Username, MatchDay, HourFrom, HourTo, InOut, Court_0-4, Partenaire/full name, Active, RowID
            facilities = request.facility_preferences + [""] * (
                5 - len(request.facility_preferences)
            )
            row = [
                request.user_id,  # Username
                day_name,  # MatchDay
                hour_from,  # HourFrom
                hour_to,  # HourTo
                in_out,  # InOut
                facilities[0],  # Court_0
                facilities[1],  # Court_1
                facilities[2],  # Court_2
                facilities[3],  # Court_3
                facilities[4],  # Court_4
                request.partner_name or "",  # Partenaire/full name
                request.active,  # Active
                request.id,  # RowID
            ]

            worksheet.append_row(row)
            logger.info(f"Added booking request {request.id} for user {request.user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add booking request: {e}")
            return False

    def update_booking_request(self, request: BookingRequest) -> bool:
        """
        Update an existing booking request in the Requests sheet.

        Args:
            request: The BookingRequest with updated values

        Returns:
            True if successfully updated, False otherwise

        """
        try:
            worksheet = self._get_worksheet(BOOKING_REQUESTS_SHEET)
            records = worksheet.get_all_records()

            # Find the row with matching RowID
            for idx, record in enumerate(records):
                if str(record.get("RowID", "")) == request.id:
                    row_num = idx + 2  # +2 for header row and 0-based index

                    # Map day_of_week value to French name
                    day_names = [
                        "Lundi",
                        "Mardi",
                        "Mercredi",
                        "Jeudi",
                        "Vendredi",
                        "Samedi",
                        "Dimanche",
                    ]
                    day_name = day_names[request.day_of_week.value]

                    # Extract hour from time string
                    hour_from = int(request.time_start.split(":")[0])
                    hour_to = int(request.time_end.split(":")[0])

                    # Map court_type to French
                    court_type_map = {"indoor": "Couvert", "outdoor": "Découvert", "any": ""}
                    in_out = court_type_map.get(request.court_type.value, "")

                    # Build row
                    facilities = request.facility_preferences + [""] * (
                        5 - len(request.facility_preferences)
                    )
                    row = [
                        request.user_id,
                        day_name,
                        hour_from,
                        hour_to,
                        in_out,
                        facilities[0],
                        facilities[1],
                        facilities[2],
                        facilities[3],
                        facilities[4],
                        request.partner_name or "",
                        request.active,
                        request.id,
                    ]

                    # Update the entire row
                    worksheet.update(f"A{row_num}:M{row_num}", [row])
                    logger.info(f"Updated booking request {request.id}")
                    return True

            logger.warning(f"Booking request {request.id} not found for update")
            return False

        except Exception as e:
            logger.error(f"Failed to update booking request: {e}")
            return False

    def delete_booking_request(self, request_id: str) -> bool:
        """
        Delete a booking request from the Requests sheet.

        Args:
            request_id: The ID of the request to delete

        Returns:
            True if successfully deleted, False otherwise

        """
        try:
            worksheet = self._get_worksheet(BOOKING_REQUESTS_SHEET)
            records = worksheet.get_all_records()

            # Find the row with matching RowID
            for idx, record in enumerate(records):
                if str(record.get("RowID", "")) == request_id:
                    row_num = idx + 2  # +2 for header row and 0-based index
                    worksheet.delete_rows(row_num)
                    logger.info(f"Deleted booking request {request_id}")
                    return True

            logger.warning(f"Booking request {request_id} not found for deletion")
            return False

        except Exception as e:
            logger.error(f"Failed to delete booking request: {e}")
            return False


# Global service instance
sheets_service = GoogleSheetsService()
