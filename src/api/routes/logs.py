"""Logs API routes."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.deps import get_current_user_id
from src.services.logs_db import BotLog, logs_service

router = APIRouter(prefix="/logs", tags=["logs"])


class LogResponse(BaseModel):
    """Log entry response."""

    id: int
    user_id: str
    timestamp: str
    level: str
    message: str
    request_id: Optional[str]
    facility_name: Optional[str]
    details: Optional[dict]

    @classmethod
    def from_model(cls, log: BotLog) -> "LogResponse":
        """Convert BotLog to response."""
        return cls(
            id=log.id,
            user_id=log.user_id,
            timestamp=log.timestamp.isoformat(),
            level=log.level,
            message=log.message,
            request_id=log.request_id,
            facility_name=log.facility_name,
            details=log.details,
        )


@router.get("", response_model=list[LogResponse])
def list_logs(
    user_id: str = Depends(get_current_user_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    level: Optional[str] = Query(default=None),
) -> list[LogResponse]:
    """List logs for the current user, most recent first."""
    logs = logs_service.get_logs(user_id, limit=limit, offset=offset, level=level)
    return [LogResponse.from_model(log) for log in logs]
