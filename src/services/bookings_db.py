"""SQLite-based service for bookings."""

import logging
from datetime import datetime

from src.database.connection import get_connection, init_database
from src.models.booking import Booking
from src.models.booking_request import normalize_time
from src.utils.timezone import PARIS_TZ, now_paris, today_paris

logger = logging.getLogger(__name__)


class SQLiteBookingsService:
    """
    Service for managing bookings in SQLite.

    Replaces the Google Sheets backend for booking history.
    """

    def __init__(self) -> None:
        """Initialize the service and ensure database is ready."""
        init_database()

    def get_all_bookings(self) -> list[Booking]:
        """
        Get all bookings from the database.

        Returns:
            List of all Booking objects.

        """
        conn = get_connection()
        cursor = conn.execute("""
            SELECT id, user_id, request_id, facility_name, facility_code,
                   court_number, date, time_start, time_end, partner_name,
                   partner_email, confirmation_id, facility_address, created_at
            FROM bookings
            ORDER BY date DESC, time_start DESC
            """)

        bookings = []
        for row in cursor.fetchall():
            try:
                booking = self._row_to_booking(row)
                bookings.append(booking)
            except Exception as e:
                logger.error(f"Error parsing booking {row['id']}: {e}")

        logger.debug(f"Retrieved {len(bookings)} bookings from database")
        return bookings

    def get_bookings_for_user(self, user_id: str) -> list[Booking]:
        """
        Get all bookings for a specific user.

        Args:
            user_id: The user's unique identifier.

        Returns:
            List of Booking objects for the user.

        """
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT id, user_id, request_id, facility_name, facility_code,
                   court_number, date, time_start, time_end, partner_name,
                   partner_email, confirmation_id, facility_address, created_at
            FROM bookings
            WHERE user_id = ?
            ORDER BY date DESC, time_start DESC
            """,
            (user_id,),
        )

        bookings = []
        for row in cursor.fetchall():
            try:
                booking = self._row_to_booking(row)
                bookings.append(booking)
            except Exception as e:
                logger.error(f"Error parsing booking {row['id']}: {e}")

        logger.debug(f"Retrieved {len(bookings)} bookings for user {user_id}")
        return bookings

    def get_todays_bookings(self) -> list[Booking]:
        """
        Get all bookings scheduled for today.

        Returns:
            List of Booking objects for today.

        """
        today = today_paris().isoformat()
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT id, user_id, request_id, facility_name, facility_code,
                   court_number, date, time_start, time_end, partner_name,
                   partner_email, confirmation_id, facility_address, created_at
            FROM bookings
            WHERE date = ?
            ORDER BY time_start ASC
            """,
            (today,),
        )

        bookings = []
        for row in cursor.fetchall():
            try:
                booking = self._row_to_booking(row)
                bookings.append(booking)
            except Exception as e:
                logger.error(f"Error parsing booking {row['id']}: {e}")

        logger.debug(f"Retrieved {len(bookings)} bookings for today ({today})")
        return bookings

    def get_upcoming_bookings_for_user(self, user_id: str) -> list[Booking]:
        """
        Get upcoming bookings for a specific user.

        Args:
            user_id: The user's unique identifier.

        Returns:
            List of Booking objects from today onwards.

        """
        today = today_paris().isoformat()
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT id, user_id, request_id, facility_name, facility_code,
                   court_number, date, time_start, time_end, partner_name,
                   partner_email, confirmation_id, facility_address, created_at
            FROM bookings
            WHERE user_id = ? AND date >= ?
            ORDER BY date ASC, time_start ASC
            """,
            (user_id, today),
        )

        bookings = []
        for row in cursor.fetchall():
            try:
                booking = self._row_to_booking(row)
                bookings.append(booking)
            except Exception as e:
                logger.error(f"Error parsing booking {row['id']}: {e}")

        logger.debug(f"Retrieved {len(bookings)} upcoming bookings for user {user_id}")
        return bookings

    def add_booking(self, booking: Booking) -> bool:
        """
        Add a new booking to the database.

        Args:
            booking: The Booking to add.

        Returns:
            True if successful, False otherwise.

        """
        conn = get_connection()
        try:
            # Format date as ISO string
            if isinstance(booking.date, datetime):
                date_str = booking.date.date().isoformat()
            else:
                date_str = booking.date.isoformat()

            created_at_str = (
                booking.created_at.isoformat() if booking.created_at else now_paris().isoformat()
            )

            conn.execute(
                """
                INSERT INTO bookings
                (id, user_id, request_id, facility_name, facility_code,
                 court_number, date, time_start, time_end, partner_name,
                 partner_email, confirmation_id, facility_address, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking.id,
                    booking.user_id,
                    booking.request_id,
                    booking.facility_name,
                    booking.facility_code,
                    booking.court_number,
                    date_str,
                    booking.time_start,
                    booking.time_end,
                    booking.partner_name,
                    booking.partner_email,
                    booking.confirmation_id,
                    booking.facility_address,
                    created_at_str,
                ),
            )
            conn.commit()
            logger.info(f"Added booking {booking.id} for user {booking.user_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding booking {booking.id}: {e}")
            conn.rollback()
            return False

    def has_pending_booking(self, user_id: str) -> bool:
        """
        Check if a user has a pending booking (future booking).

        A booking is considered "pending" if:
        - The booking date is in the future (date > today), OR
        - The booking is today AND the end time hasn't passed yet

        Args:
            user_id: The user's unique identifier.

        Returns:
            True if user has a pending booking, False otherwise.

        """
        today = today_paris()
        today_str = today.isoformat()
        now = now_paris()
        current_time = now.strftime("%H:%M")

        conn = get_connection()

        # Check for future bookings
        cursor = conn.execute(
            """
            SELECT id, date, time_end FROM bookings
            WHERE user_id = ? AND date >= ?
            """,
            (user_id, today_str),
        )

        for row in cursor.fetchall():
            booking_date = row["date"]
            if booking_date > today_str:
                # Future date - definitely pending
                return True
            if booking_date == today_str:
                # Today's booking - check if end time has passed
                booking_end = normalize_time(row["time_end"])
                if booking_end and booking_end > current_time:
                    return True

        return False

    def _row_to_booking(self, row) -> Booking:
        """
        Convert a database row to a Booking object.

        Args:
            row: SQLite Row object with booking data.

        Returns:
            Booking object.

        """
        # Parse date
        date_str = row["date"]
        if date_str:
            try:
                # Try parsing as datetime first
                date_value = datetime.fromisoformat(date_str)
                if date_value.tzinfo is None:
                    date_value = PARIS_TZ.localize(date_value)
            except ValueError:
                # Fallback to date-only parsing
                from datetime import date as date_type

                date_value = datetime.combine(
                    date_type.fromisoformat(date_str), datetime.min.time()
                )
                date_value = PARIS_TZ.localize(date_value)
        else:
            date_value = now_paris()

        # Parse created_at
        created_at_str = row["created_at"]
        created_at = None
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                if created_at.tzinfo is None:
                    created_at = PARIS_TZ.localize(created_at)
            except ValueError:
                created_at = None

        return Booking(
            id=row["id"],
            user_id=row["user_id"],
            request_id=row["request_id"],
            facility_name=row["facility_name"],
            facility_code=row["facility_code"],
            court_number=row["court_number"],
            date=date_value,
            time_start=row["time_start"],
            time_end=row["time_end"],
            partner_name=row["partner_name"],
            partner_email=row["partner_email"],
            confirmation_id=row["confirmation_id"],
            facility_address=row["facility_address"],
            created_at=created_at,
        )


# Global instance for dependency injection
bookings_service = SQLiteBookingsService()
