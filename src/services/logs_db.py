"""SQLite-based logging service for bot activity."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.database.connection import get_connection


@dataclass
class BotLog:
    """Bot activity log entry."""

    id: int
    user_id: str
    timestamp: datetime
    level: str  # INFO, WARNING, ERROR, SUCCESS
    message: str
    request_id: Optional[str] = None
    facility_name: Optional[str] = None
    details: Optional[dict] = None


class LogsService:
    """Service for managing bot activity logs in SQLite."""

    def add_log(
        self,
        user_id: str,
        message: str,
        level: str = "INFO",
        request_id: Optional[str] = None,
        facility_name: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> int:
        """Add a log entry."""
        conn = get_connection()
        cursor = conn.cursor()

        details_json = json.dumps(details) if details else None

        cursor.execute(
            """
            INSERT INTO bot_logs (user_id, level, message, request_id, facility_name, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, level, message, request_id, facility_name, details_json),
        )
        conn.commit()
        return cursor.lastrowid

    def get_logs(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        level: Optional[str] = None,
    ) -> list[BotLog]:
        """Get logs for a user, most recent first."""
        conn = get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM bot_logs WHERE user_id = ?"
        params: list = [user_id]

        if level:
            query += " AND level = ?"
            params.append(level)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        logs = []
        for row in rows:
            details = None
            if row["details"]:
                try:
                    details = json.loads(row["details"])
                except json.JSONDecodeError:
                    details = None

            logs.append(
                BotLog(
                    id=row["id"],
                    user_id=row["user_id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    level=row["level"],
                    message=row["message"],
                    request_id=row["request_id"],
                    facility_name=row["facility_name"],
                    details=details,
                )
            )

        return logs

    def log_info(
        self,
        user_id: str,
        message: str,
        **kwargs,
    ) -> int:
        """Add an INFO log."""
        return self.add_log(user_id, message, level="INFO", **kwargs)

    def log_success(
        self,
        user_id: str,
        message: str,
        **kwargs,
    ) -> int:
        """Add a SUCCESS log."""
        return self.add_log(user_id, message, level="SUCCESS", **kwargs)

    def log_warning(
        self,
        user_id: str,
        message: str,
        **kwargs,
    ) -> int:
        """Add a WARNING log."""
        return self.add_log(user_id, message, level="WARNING", **kwargs)

    def log_error(
        self,
        user_id: str,
        message: str,
        **kwargs,
    ) -> int:
        """Add an ERROR log."""
        return self.add_log(user_id, message, level="ERROR", **kwargs)


# Global instance
logs_service = LogsService()
