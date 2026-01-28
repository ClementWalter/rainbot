"""FastAPI Dependencies."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.auth import TokenData, decode_access_token
from src.services.requests_db import SQLiteRequestsService, requests_service

security = HTTPBearer()


def get_requests_service() -> SQLiteRequestsService:
    """Get SQLite requests service instance."""
    return requests_service


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),  # noqa: B008
) -> TokenData:
    """Get current authenticated user from JWT token."""
    token = credentials.credentials
    return decode_access_token(token)


def get_current_user_id(
    current_user: TokenData = Depends(get_current_user),  # noqa: B008
) -> str:
    """Get current user ID."""
    return current_user.user_id
