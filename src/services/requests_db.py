"""SQLite-based service for booking requests."""

import json
import logging
from datetime import datetime
from typing import Optional

from src.database.connection import get_connection, init_database
from src.models.booking_request import BookingRequest, CourtType, DayOfWeek

logger = logging.getLogger(__name__)


class SQLiteRequestsService:
    """
    Service for managing booking requests in SQLite.

    Provides the same interface as GoogleSheetsService for booking requests,
    enabling a drop-in replacement with better performance.
    """

    def __init__(self) -> None:
        """Initialize the service and ensure database is ready."""
        init_database()

    def get_all_booking_requests(self) -> list[BookingRequest]:
        """
        Get all booking requests from the database.

        Returns:
            List of all BookingRequest objects, regardless of active status.
        """
        conn = get_connection()
        cursor = conn.execute("""
            SELECT id, user_id, day_of_week, time_start, time_end,
                   court_type, facility_preferences, partner_name,
                   partner_email, active
            FROM booking_requests
            ORDER BY user_id, day_of_week
            """)

        requests = []
        for row in cursor.fetchall():
            try:
                request = self._row_to_request(row)
                requests.append(request)
            except Exception as e:
                logger.error(f"Error parsing booking request {row['id']}: {e}")

        logger.debug(f"Retrieved {len(requests)} booking requests from database")
        return requests

    def get_active_booking_requests(self) -> list[BookingRequest]:
        """
        Get only active booking requests.

        Returns:
            List of BookingRequest objects where active=True.
        """
        conn = get_connection()
        cursor = conn.execute("""
            SELECT id, user_id, day_of_week, time_start, time_end,
                   court_type, facility_preferences, partner_name,
                   partner_email, active
            FROM booking_requests
            WHERE active = 1
            ORDER BY user_id, day_of_week
            """)

        requests = []
        for row in cursor.fetchall():
            try:
                request = self._row_to_request(row)
                requests.append(request)
            except Exception as e:
                logger.error(f"Error parsing booking request {row['id']}: {e}")

        logger.debug(f"Retrieved {len(requests)} active booking requests from database")
        return requests

    def add_booking_request(self, request: BookingRequest) -> bool:
        """
        Add a new booking request to the database.

        Args:
            request: The BookingRequest to add.

        Returns:
            True if successful, False otherwise.
        """
        conn = get_connection()
        try:
            facility_prefs_json = json.dumps(request.facility_preferences)
            now = datetime.utcnow().isoformat()

            conn.execute(
                """
                INSERT INTO booking_requests
                (id, user_id, day_of_week, time_start, time_end,
                 court_type, facility_preferences, partner_name,
                 partner_email, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.id,
                    request.user_id,
                    request.day_of_week.value,
                    request.time_start,
                    request.time_end,
                    request.court_type.value,
                    facility_prefs_json,
                    request.partner_name,
                    request.partner_email,
                    1 if request.active else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
            logger.info(f"Added booking request {request.id} for user {request.user_id}")
            return True
        except Exception as e:
            logger.error(f"Error adding booking request {request.id}: {e}")
            conn.rollback()
            return False

    def update_booking_request(self, request: BookingRequest) -> bool:
        """
        Update an existing booking request.

        Args:
            request: The BookingRequest with updated values.

        Returns:
            True if successful, False otherwise.
        """
        conn = get_connection()
        try:
            facility_prefs_json = json.dumps(request.facility_preferences)
            now = datetime.utcnow().isoformat()

            cursor = conn.execute(
                """
                UPDATE booking_requests
                SET user_id = ?,
                    day_of_week = ?,
                    time_start = ?,
                    time_end = ?,
                    court_type = ?,
                    facility_preferences = ?,
                    partner_name = ?,
                    partner_email = ?,
                    active = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    request.user_id,
                    request.day_of_week.value,
                    request.time_start,
                    request.time_end,
                    request.court_type.value,
                    facility_prefs_json,
                    request.partner_name,
                    request.partner_email,
                    1 if request.active else 0,
                    now,
                    request.id,
                ),
            )
            conn.commit()

            if cursor.rowcount == 0:
                logger.warning(f"No booking request found with id {request.id}")
                return False

            logger.info(f"Updated booking request {request.id}")
            return True
        except Exception as e:
            logger.error(f"Error updating booking request {request.id}: {e}")
            conn.rollback()
            return False

    def delete_booking_request(self, request_id: str) -> bool:
        """
        Delete a booking request by ID.

        Args:
            request_id: The ID of the request to delete.

        Returns:
            True if successful, False otherwise.
        """
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM booking_requests WHERE id = ?",
                (request_id,),
            )
            conn.commit()

            if cursor.rowcount == 0:
                logger.warning(f"No booking request found with id {request_id}")
                return False

            logger.info(f"Deleted booking request {request_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting booking request {request_id}: {e}")
            conn.rollback()
            return False

    def get_booking_request_by_id(self, request_id: str) -> Optional[BookingRequest]:
        """
        Get a single booking request by ID.

        Args:
            request_id: The ID of the request to retrieve.

        Returns:
            The BookingRequest if found, None otherwise.
        """
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT id, user_id, day_of_week, time_start, time_end,
                   court_type, facility_preferences, partner_name,
                   partner_email, active
            FROM booking_requests
            WHERE id = ?
            """,
            (request_id,),
        )

        row = cursor.fetchone()
        if row is None:
            return None

        try:
            return self._row_to_request(row)
        except Exception as e:
            logger.error(f"Error parsing booking request {request_id}: {e}")
            return None

    def _row_to_request(self, row) -> BookingRequest:
        """
        Convert a database row to a BookingRequest object.

        Args:
            row: SQLite Row object with booking request data.

        Returns:
            BookingRequest object.
        """
        # Parse facility preferences from JSON
        facility_prefs = []
        if row["facility_preferences"]:
            try:
                facility_prefs = json.loads(row["facility_preferences"])
            except json.JSONDecodeError:
                logger.warning(f"Invalid facility_preferences JSON for request {row['id']}")

        # Map court type string to enum
        court_type_map = {
            "indoor": CourtType.INDOOR,
            "outdoor": CourtType.OUTDOOR,
            "any": CourtType.ANY,
        }
        court_type = court_type_map.get(row["court_type"], CourtType.ANY)

        return BookingRequest(
            id=row["id"],
            user_id=row["user_id"],
            day_of_week=DayOfWeek(row["day_of_week"]),
            time_start=row["time_start"],
            time_end=row["time_end"],
            court_type=court_type,
            facility_preferences=facility_prefs,
            partner_name=row["partner_name"],
            partner_email=row["partner_email"],
            active=bool(row["active"]),
        )


# Global instance for dependency injection
requests_service = SQLiteRequestsService()
