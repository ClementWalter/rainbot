"""FastAPI Dependencies."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.auth import TokenData, decode_access_token
from src.services.google_sheets import GoogleSheetsService, sheets_service

security = HTTPBearer()


def get_sheets_service() -> GoogleSheetsService:
    """Get Google Sheets service instance."""
    return sheets_service


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TokenData:
    """Get current authenticated user from JWT token."""
    token = credentials.credentials
    return decode_access_token(token)


def get_current_user_id(
    current_user: TokenData = Depends(get_current_user),
) -> str:
    """Get current user ID."""
    return current_user.user_id
