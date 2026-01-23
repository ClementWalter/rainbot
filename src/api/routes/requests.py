"""Booking Requests API routes."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.deps import get_current_user_id, get_requests_service
from src.models.booking_request import BookingRequest, CourtType, DayOfWeek
from src.services.requests_db import SQLiteRequestsService

router = APIRouter(prefix="/requests", tags=["requests"])


class RequestCreate(BaseModel):
    """Create booking request payload."""

    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    time_start: str = Field(..., pattern=r"^\d{1,2}:\d{2}$", description="HH:MM format")
    time_end: str = Field(..., pattern=r"^\d{1,2}:\d{2}$", description="HH:MM format")
    court_type: str = Field(default="any", description="indoor, outdoor, or any")
    facility_preferences: list[str] = Field(default_factory=list)
    partner_name: Optional[str] = None
    partner_email: Optional[str] = None
    active: bool = True


class RequestUpdate(BaseModel):
    """Update booking request payload."""

    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    time_start: Optional[str] = Field(None, pattern=r"^\d{1,2}:\d{2}$")
    time_end: Optional[str] = Field(None, pattern=r"^\d{1,2}:\d{2}$")
    court_type: Optional[str] = None
    facility_preferences: Optional[list[str]] = None
    partner_name: Optional[str] = None
    partner_email: Optional[str] = None
    active: Optional[bool] = None


class RequestResponse(BaseModel):
    """Booking request response."""

    id: str
    user_id: str
    day_of_week: int
    day_of_week_name: str
    time_start: str
    time_end: str
    court_type: str
    facility_preferences: list[str]
    partner_name: Optional[str]
    partner_email: Optional[str]
    active: bool

    @classmethod
    def from_model(cls, req: BookingRequest) -> "RequestResponse":
        """Convert BookingRequest model to response."""
        day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        return cls(
            id=req.id,
            user_id=req.user_id,
            day_of_week=req.day_of_week.value,
            day_of_week_name=day_names[req.day_of_week.value],
            time_start=req.time_start,
            time_end=req.time_end,
            court_type=req.court_type.value,
            facility_preferences=req.facility_preferences,
            partner_name=req.partner_name,
            partner_email=req.partner_email,
            active=req.active,
        )


@router.get("", response_model=list[RequestResponse])
def list_requests(
    user_id: str = Depends(get_current_user_id),
    requests_svc: SQLiteRequestsService = Depends(get_requests_service),
) -> list[RequestResponse]:
    """List all booking requests for the current user."""
    all_requests = requests_svc.get_all_booking_requests()
    user_requests = [r for r in all_requests if r.user_id == user_id]
    return [RequestResponse.from_model(r) for r in user_requests]


@router.post("", response_model=RequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(
    data: RequestCreate,
    user_id: str = Depends(get_current_user_id),
    requests_svc: SQLiteRequestsService = Depends(get_requests_service),
) -> RequestResponse:
    """Create a new booking request."""
    # Map court type
    court_type_map = {
        "indoor": CourtType.INDOOR,
        "outdoor": CourtType.OUTDOOR,
        "any": CourtType.ANY,
    }
    court_type = court_type_map.get(data.court_type.lower(), CourtType.ANY)

    request = BookingRequest(
        id=f"req_{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        day_of_week=DayOfWeek(data.day_of_week),
        time_start=data.time_start,
        time_end=data.time_end,
        court_type=court_type,
        facility_preferences=data.facility_preferences,
        partner_name=data.partner_name,
        partner_email=data.partner_email,
        active=data.active,
    )

    if not requests_svc.add_booking_request(request):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create booking request",
        )

    return RequestResponse.from_model(request)


@router.patch("/{request_id}", response_model=RequestResponse)
def update_request(
    request_id: str,
    data: RequestUpdate,
    user_id: str = Depends(get_current_user_id),
    requests_svc: SQLiteRequestsService = Depends(get_requests_service),
) -> RequestResponse:
    """Update a booking request."""
    # Find the request
    request = requests_svc.get_booking_request_by_id(request_id)

    if not request or request.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    # Update fields
    if data.day_of_week is not None:
        request.day_of_week = DayOfWeek(data.day_of_week)
    if data.time_start is not None:
        request.time_start = data.time_start
    if data.time_end is not None:
        request.time_end = data.time_end
    if data.court_type is not None:
        court_type_map = {
            "indoor": CourtType.INDOOR,
            "outdoor": CourtType.OUTDOOR,
            "any": CourtType.ANY,
        }
        request.court_type = court_type_map.get(data.court_type.lower(), CourtType.ANY)
    if data.facility_preferences is not None:
        request.facility_preferences = data.facility_preferences
    if data.partner_name is not None:
        request.partner_name = data.partner_name
    if data.partner_email is not None:
        request.partner_email = data.partner_email
    if data.active is not None:
        request.active = data.active

    if not requests_svc.update_booking_request(request):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update booking request",
        )

    return RequestResponse.from_model(request)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_request(
    request_id: str,
    user_id: str = Depends(get_current_user_id),
    requests_svc: SQLiteRequestsService = Depends(get_requests_service),
) -> None:
    """Delete a booking request."""
    request = requests_svc.get_booking_request_by_id(request_id)

    if not request or request.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    if not requests_svc.delete_booking_request(request_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete booking request",
        )
