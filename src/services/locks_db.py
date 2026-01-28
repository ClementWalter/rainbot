"""SQLite-based service for user locks (concurrency control)."""

import logging
from datetime import timedelta

from src.database.connection import get_connection, init_database
from src.utils.timezone import now_paris

logger = logging.getLogger(__name__)

# Lock timeout in seconds
LOCK_TIMEOUT = 300  # 5 minutes


class SQLiteLocksService:
    """
    Service for managing user locks in SQLite.

    Replaces the Google Sheets backend for concurrency control.
    """

    def __init__(self) -> None:
        """Initialize the service and ensure database is ready."""
        init_database()

    def acquire_user_lock(self, user_id: str, job_id: str) -> bool:
        """
        Try to acquire a lock for a user.

        Args:
            user_id: The user's unique identifier.
            job_id: The job ID requesting the lock.

        Returns:
            True if lock acquired, False if user is already locked.

        """
        conn = get_connection()
        now = now_paris()
        now_str = now.isoformat()
        expires_at = (now + timedelta(seconds=LOCK_TIMEOUT)).isoformat()

        try:
            # First, check if there's an existing non-expired lock
            cursor = conn.execute(
                """
                SELECT user_id, locked_by, expires_at FROM user_locks
                WHERE user_id = ?
                """,
                (user_id,),
            )
            existing = cursor.fetchone()

            if existing:
                existing_expires = existing["expires_at"]
                if existing_expires > now_str:
                    # Lock is still valid
                    logger.debug(
                        f"Lock for user {user_id} held by {existing['locked_by']}, "
                        f"expires at {existing_expires}"
                    )
                    return False
                else:
                    # Lock expired, we can take it
                    logger.info(f"Expired lock for user {user_id} found, acquiring new lock")

            # Insert or replace the lock
            conn.execute(
                """
                INSERT OR REPLACE INTO user_locks (user_id, locked_at, locked_by, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, now_str, job_id, expires_at),
            )
            conn.commit()
            logger.debug(f"Acquired lock for user {user_id} by job {job_id}")
            return True

        except Exception as e:
            logger.error(f"Error acquiring lock for user {user_id}: {e}")
            conn.rollback()
            return False

    def release_user_lock(self, user_id: str, job_id: str) -> bool:
        """
        Release a lock held by a specific job.

        Args:
            user_id: The user's unique identifier.
            job_id: The job ID that holds the lock.

        Returns:
            True if lock released, False otherwise.

        """
        conn = get_connection()

        try:
            cursor = conn.execute(
                """
                DELETE FROM user_locks
                WHERE user_id = ? AND locked_by = ?
                """,
                (user_id, job_id),
            )
            conn.commit()

            if cursor.rowcount > 0:
                logger.debug(f"Released lock for user {user_id} by job {job_id}")
                return True
            else:
                logger.debug(f"No lock to release for user {user_id} by job {job_id}")
                return False

        except Exception as e:
            logger.error(f"Error releasing lock for user {user_id}: {e}")
            conn.rollback()
            return False

    def cleanup_expired_locks(self) -> int:
        """
        Remove all expired locks.

        Returns:
            Number of locks cleaned up.

        """
        conn = get_connection()
        now_str = now_paris().isoformat()

        try:
            cursor = conn.execute(
                """
                DELETE FROM user_locks
                WHERE expires_at < ?
                """,
                (now_str,),
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(f"Cleaned up {count} expired locks")
            return count

        except Exception as e:
            logger.error(f"Error cleaning up expired locks: {e}")
            conn.rollback()
            return 0


# Global instance for dependency injection
locks_service = SQLiteLocksService()
