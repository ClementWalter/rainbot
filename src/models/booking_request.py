"""BookingRequest model representing a user's booking preferences."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CourtType(Enum):
    """Court surface/cover type preference."""

    INDOOR = "indoor"  # Covered courts
    OUTDOOR = "outdoor"  # Uncovered courts
    ANY = "any"  # No preference


class DayOfWeek(Enum):
    """Days of the week."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass
class BookingRequest:
    """
    A user's booking request defining their preferences.

    Attributes:
        id: Unique identifier for this request
        user_id: Reference to the user who created this request
        day_of_week: Which day to book (0=Monday, 6=Sunday)
        time_start: Earliest acceptable time (e.g., "18:00")
        time_end: Latest acceptable time (e.g., "20:00")
        facility_preferences: Ordered list of preferred facility codes
        court_type: Preferred court type (indoor/outdoor/any)
        partner_name: Name of the playing partner
        partner_email: Email of the partner for notifications
        active: Whether this request is currently active
    """

    id: str
    user_id: str
    day_of_week: DayOfWeek
    time_start: str
    time_end: str
    facility_preferences: list[str] = field(default_factory=list)
    court_type: CourtType = CourtType.ANY
    partner_name: Optional[str] = None
    partner_email: Optional[str] = None
    active: bool = True

    def is_time_in_range(self, time_str: str) -> bool:
        """
        Check if a given time falls within the preferred range.

        Args:
            time_str: Time in "HH:MM" format

        Returns:
            True if time is within [time_start, time_end]
        """
        return self.time_start <= time_str <= self.time_end

    @classmethod
    def from_dict(cls, data: dict) -> "BookingRequest":
        """
        Create a BookingRequest from a dictionary (e.g., from Google Sheets).

        Args:
            data: Dictionary with booking request fields

        Returns:
            BookingRequest instance
        """
        # Parse day of week
        day_value = data.get("day_of_week", 0)
        if isinstance(day_value, str):
            # Try to parse as integer first (e.g., "0", "1", "2")
            try:
                day_value = int(day_value)
            except ValueError:
                # Fall back to enum name lookup (e.g., "monday", "MONDAY")
                day_value = DayOfWeek[day_value.upper()].value
        day_of_week = DayOfWeek(day_value)

        # Parse court type
        court_type_str = data.get("court_type", "any").lower()
        court_type = CourtType(court_type_str)

        # Parse facility preferences (comma-separated string or list)
        facilities = data.get("facility_preferences", [])
        if isinstance(facilities, str):
            facilities = [f.strip() for f in facilities.split(",") if f.strip()]

        return cls(
            id=str(data.get("id", "")),
            user_id=str(data.get("user_id", "")),
            day_of_week=day_of_week,
            time_start=str(data.get("time_start", "08:00")),
            time_end=str(data.get("time_end", "22:00")),
            facility_preferences=facilities,
            court_type=court_type,
            partner_name=data.get("partner_name"),
            partner_email=data.get("partner_email"),
            active=data.get("active", True) in (True, "true", "True", "1", 1),
        )
