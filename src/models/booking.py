"""Booking model representing a completed court reservation."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from src.utils.timezone import PARIS_TZ, now_paris, today_paris


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse an ISO datetime string, including UTC "Z" suffix variants."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        if value.endswith("Z"):
            try:
                return datetime.fromisoformat(value[:-1] + "+00:00")
            except ValueError:
                return None
        return None


def _normalize_paris_datetime(value: datetime) -> datetime:
    """Normalize a datetime to Paris timezone."""
    if value.tzinfo is None:
        return PARIS_TZ.localize(value)
    return value.astimezone(PARIS_TZ)


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
        partner_email: Email of the playing partner (for reminders)
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
    partner_email: Optional[str] = None
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
            date_str = date_value.strip()
            parsed_date = _parse_iso_datetime(date_str) if date_str else None
            date_value = parsed_date if parsed_date else now_paris()
        elif isinstance(date_value, date) and not isinstance(date_value, datetime):
            date_value = PARIS_TZ.localize(datetime.combine(date_value, datetime.min.time()))
        elif not isinstance(date_value, datetime):
            date_value = now_paris()
        if isinstance(date_value, datetime):
            date_value = _normalize_paris_datetime(date_value)

        # Parse created_at
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_str = created_at.strip()
            created_at = _parse_iso_datetime(created_str) if created_str else None
        elif isinstance(created_at, date) and not isinstance(created_at, datetime):
            created_at = PARIS_TZ.localize(datetime.combine(created_at, datetime.min.time()))
        elif not isinstance(created_at, datetime):
            created_at = None  # Invalid type - will be set in __post_init__
        if isinstance(created_at, datetime):
            created_at = _normalize_paris_datetime(created_at)

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
            partner_email=data.get("partner_email"),
            confirmation_id=data.get("confirmation_id"),
            facility_address=data.get("facility_address"),
            created_at=created_at,
        )

    def is_today(self) -> bool:
        """Check if this booking is for today (in Paris timezone)."""
        if isinstance(self.date, datetime):
            if self.date.tzinfo is not None:
                booking_date = self.date.astimezone(PARIS_TZ).date()
            else:
                booking_date = self.date.date()
        elif isinstance(self.date, date):
            booking_date = self.date
        else:
            return False
        return booking_date == today_paris()
