"""SQLite-based service for no-slots notification tracking."""

import logging
from datetime import timedelta

from src.database.connection import get_connection, init_database
from src.utils.timezone import now_paris

logger = logging.getLogger(__name__)


class SQLiteNotificationsService:
    """
    Service for tracking no-slots notifications in SQLite.

    Prevents sending duplicate "no slots available" notifications
    for the same request/date combination.
    """

    def __init__(self) -> None:
        """Initialize the service and ensure database is ready."""
        init_database()

    def was_no_slots_notification_sent(self, request_id: str, target_date: str) -> bool:
        """
        Check if a no-slots notification was already sent.

        Args:
            request_id: The booking request ID.
            target_date: The target date (YYYY-MM-DD format).

        Returns:
            True if notification was already sent, False otherwise.

        """
        conn = get_connection()
        cursor = conn.execute(
            """
            SELECT id FROM no_slots_notifications
            WHERE request_id = ? AND target_date = ?
            """,
            (request_id, target_date),
        )
        return cursor.fetchone() is not None

    def mark_no_slots_notification_sent(self, request_id: str, target_date: str) -> bool:
        """
        Mark that a no-slots notification was sent.

        Args:
            request_id: The booking request ID.
            target_date: The target date (YYYY-MM-DD format).

        Returns:
            True if successful, False otherwise.

        """
        conn = get_connection()
        now_str = now_paris().isoformat()

        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO no_slots_notifications
                (request_id, target_date, sent_at)
                VALUES (?, ?, ?)
                """,
                (request_id, target_date, now_str),
            )
            conn.commit()
            logger.debug(
                f"Marked no-slots notification sent for request {request_id}, "
                f"date {target_date}"
            )
            return True

        except Exception as e:
            logger.error(f"Error marking notification for request {request_id}: {e}")
            conn.rollback()
            return False

    def cleanup_old_notifications(self, days_to_keep: int = 7) -> int:
        """
        Remove old notification records.

        Args:
            days_to_keep: Number of days to keep records (default 7).

        Returns:
            Number of records deleted.

        """
        conn = get_connection()
        cutoff = (now_paris() - timedelta(days=days_to_keep)).isoformat()

        try:
            cursor = conn.execute(
                """
                DELETE FROM no_slots_notifications
                WHERE sent_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Cleaned up {count} old notification records")
            return count

        except Exception as e:
            logger.error(f"Error cleaning up old notifications: {e}")
            conn.rollback()
            return 0


# Global instance for dependency injection
notifications_service = SQLiteNotificationsService()
