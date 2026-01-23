"""Bookings API routes."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import get_current_user_id, get_sheets_service
from src.models.booking import Booking
from src.services.google_sheets import GoogleSheetsService

router = APIRouter(prefix="/bookings", tags=["bookings"])


class BookingResponse(BaseModel):
    """Booking response."""

    id: str
    user_id: str
    request_id: str
    facility_name: str
    facility_code: str
    court_number: str
    date: str
    time_start: str
    time_end: str
    partner_name: Optional[str]
    partner_email: Optional[str]
    confirmation_id: Optional[str]
    facility_address: Optional[str]
    created_at: Optional[str]

    @classmethod
    def from_model(cls, booking: Booking) -> "BookingResponse":
        """Convert Booking model to response."""
        return cls(
            id=booking.id,
            user_id=booking.user_id,
            request_id=booking.request_id,
            facility_name=booking.facility_name,
            facility_code=booking.facility_code,
            court_number=booking.court_number,
            date=booking.date.strftime("%Y-%m-%d") if booking.date else "",
            time_start=booking.time_start,
            time_end=booking.time_end,
            partner_name=booking.partner_name,
            partner_email=booking.partner_email,
            confirmation_id=booking.confirmation_id,
            facility_address=booking.facility_address,
            created_at=booking.created_at.isoformat() if booking.created_at else None,
        )


@router.get("", response_model=list[BookingResponse])
def list_bookings(
    user_id: str = Depends(get_current_user_id),
    sheets: GoogleSheetsService = Depends(get_sheets_service),
) -> list[BookingResponse]:
    """List all bookings for the current user (upcoming and past)."""
    all_bookings = sheets.get_all_bookings()
    user_bookings = [b for b in all_bookings if b.user_id == user_id]
    # Sort by date descending (most recent first)
    user_bookings.sort(key=lambda b: b.date if b.date else datetime.min, reverse=True)
    return [BookingResponse.from_model(b) for b in user_bookings]


@router.get("/upcoming", response_model=list[BookingResponse])
def list_upcoming_bookings(
    user_id: str = Depends(get_current_user_id),
    sheets: GoogleSheetsService = Depends(get_sheets_service),
) -> list[BookingResponse]:
    """List upcoming bookings for the current user."""
    from src.utils.timezone import today_paris

    today = today_paris()
    all_bookings = sheets.get_all_bookings()
    upcoming = [
        b for b in all_bookings if b.user_id == user_id and b.date and b.date.date() >= today
    ]
    # Sort by date ascending (soonest first)
    upcoming.sort(key=lambda b: b.date if b.date else datetime.max)
    return [BookingResponse.from_model(b) for b in upcoming]
