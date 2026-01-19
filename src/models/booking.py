"""Booking model representing a completed court reservation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.utils.timezone import now_paris, today_paris


@dataclass
class Booking:
    """
    A completed tennis court booking.

    Attributes:
        id: Unique identifier for this booking
        user_id: Reference to the user who made the booking
        request_id: Reference to the booking request that triggered this
        facility_name: Name of the tennis facility
        facility_code: Code/ID of the facility
        court_number: Court number at the facility
        date: Date of the booking
        time_start: Start time of the reservation
        time_end: End time of the reservation
        partner_name: Name of the playing partner
        confirmation_id: Confirmation ID from Paris Tennis
        facility_address: Address of the tennis facility
        created_at: When this booking was made
    """

    id: str
    user_id: str
    request_id: str
    facility_name: str
    facility_code: str
    court_number: str
    date: datetime
    time_start: str
    time_end: str
    partner_name: Optional[str] = None
    confirmation_id: Optional[str] = None
    facility_address: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = now_paris()

    @classmethod
    def from_dict(cls, data: dict) -> "Booking":
        """
        Create a Booking from a dictionary (e.g., from Google Sheets).

        Args:
            data: Dictionary with booking fields

        Returns:
            Booking instance
        """
        # Parse date
        date_value = data.get("date")
        if isinstance(date_value, str):
            date_value = datetime.fromisoformat(date_value)
        elif not isinstance(date_value, datetime):
            date_value = now_paris()

        # Parse created_at
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return cls(
            id=str(data.get("id", "")),
            user_id=str(data.get("user_id", "")),
            request_id=str(data.get("request_id", "")),
            facility_name=str(data.get("facility_name", "")),
            facility_code=str(data.get("facility_code", "")),
            court_number=str(data.get("court_number", "")),
            date=date_value,
            time_start=str(data.get("time_start", "")),
            time_end=str(data.get("time_end", "")),
            partner_name=data.get("partner_name"),
            confirmation_id=data.get("confirmation_id"),
            facility_address=data.get("facility_address"),
            created_at=created_at,
        )

    def is_today(self) -> bool:
        """Check if this booking is for today (in Paris timezone)."""
        return self.date.date() == today_paris()
