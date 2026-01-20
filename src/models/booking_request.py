"""BookingRequest model representing a user's booking preferences."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.utils.parsing import is_truthy

# Time boundaries per PRD section 5.1: Courts available from 8:00 to 22:00
MIN_BOOKING_TIME = "08:00"
MAX_BOOKING_TIME = "22:00"


def normalize_time(time_str: str) -> str:
    """
    Normalize a time string to HH:MM format.

    This ensures consistent string comparison by padding single-digit hours
    with a leading zero. For example, "9:00" becomes "09:00".
    Accepts "H:MM", "HH:MM", or "HH:MM:SS" formats (seconds are ignored).

    Args:
        time_str: Time string in H:MM or HH:MM format

    Returns:
        Time string in HH:MM format, or empty string if invalid
    """
    if not time_str or ":" not in time_str:
        return ""

    time_str = str(time_str).strip()
    parts = time_str.split(":")

    if len(parts) not in (2, 3):
        return ""

    hour, minute = parts[0].strip(), parts[1].strip()
    second = parts[2].strip() if len(parts) == 3 else None

    # Validate hour and minute are numeric
    if not hour.isdigit() or not minute.isdigit():
        return ""
    if second is not None and not second.isdigit():
        return ""

    # Pad single-digit hour with leading zero
    hour = hour.zfill(2)

    # Ensure minute is two digits
    minute = minute.zfill(2)

    return f"{hour}:{minute}"


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


DAY_OF_WEEK_ALIASES = {
    "lundi": DayOfWeek.MONDAY,
    "mardi": DayOfWeek.TUESDAY,
    "mercredi": DayOfWeek.WEDNESDAY,
    "jeudi": DayOfWeek.THURSDAY,
    "vendredi": DayOfWeek.FRIDAY,
    "samedi": DayOfWeek.SATURDAY,
    "dimanche": DayOfWeek.SUNDAY,
}


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
            time_str: Time in "H:MM" or "HH:MM" format

        Returns:
            True if time is within [time_start, time_end], False otherwise.
            Returns False if time_str is invalid or cannot be normalized.
        """
        normalized = normalize_time(time_str)
        if not normalized:
            return False
        return self.time_start <= normalized <= self.time_end

    @staticmethod
    def _validate_time(time_str: str, default: str) -> str:
        """
        Validate and normalize a time string to be within booking boundaries.

        Args:
            time_str: Time in "H:MM" or "HH:MM" format
            default: Default time to use if invalid

        Returns:
            Validated time string in HH:MM format, clamped to valid booking hours
        """
        if not time_str:
            return default

        # Normalize to HH:MM format (handles "9:00" -> "09:00")
        normalized = normalize_time(str(time_str))
        if not normalized:
            return default

        # Clamp to valid booking hours
        if normalized < MIN_BOOKING_TIME:
            return MIN_BOOKING_TIME
        if normalized > MAX_BOOKING_TIME:
            return MAX_BOOKING_TIME

        return normalized

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
        if isinstance(day_value, DayOfWeek):
            day_of_week = day_value
        elif isinstance(day_value, str):
            day_str = day_value.strip().lower()
            # Try to parse as integer first (e.g., "0", "1", "2")
            try:
                day_value = int(day_str)
                day_of_week = DayOfWeek(day_value)
            except ValueError:
                # Fall back to alias or enum name lookup (e.g., "monday", "lundi")
                alias = DAY_OF_WEEK_ALIASES.get(day_str)
                if alias is not None:
                    day_of_week = alias
                else:
                    day_of_week = DayOfWeek[day_str.upper()]
        else:
            day_of_week = DayOfWeek(day_value)

        # Parse court type (default to ANY for missing/invalid values)
        court_type_value = data.get("court_type", "any")
        if isinstance(court_type_value, CourtType):
            court_type = court_type_value
        else:
            if court_type_value is None:
                court_type_str = "any"
            else:
                court_type_str = str(court_type_value).strip().lower()
            if not court_type_str:
                court_type_str = "any"
            try:
                court_type = CourtType(court_type_str)
            except ValueError:
                court_type = CourtType.ANY

        # Parse facility preferences (comma-separated string or list)
        facilities = data.get("facility_preferences", [])
        if isinstance(facilities, str):
            facilities = [f.strip() for f in facilities.split(",") if f.strip()]

        # Parse and validate time boundaries (PRD section 5.1: 8:00-22:00)
        time_start = cls._validate_time(str(data.get("time_start", "")), MIN_BOOKING_TIME)
        time_end = cls._validate_time(str(data.get("time_end", "")), MAX_BOOKING_TIME)

        # Ensure time_start is before time_end
        if time_start > time_end:
            time_start, time_end = time_end, time_start

        active_value = data.get("active", True)
        if active_value is None:
            active_value = True
        elif isinstance(active_value, str) and not active_value.strip():
            active_value = True

        return cls(
            id=str(data.get("id", "")),
            user_id=str(data.get("user_id", "")),
            day_of_week=day_of_week,
            time_start=time_start,
            time_end=time_end,
            facility_preferences=facilities,
            court_type=court_type,
            partner_name=data.get("partner_name"),
            partner_email=data.get("partner_email"),
            active=is_truthy(active_value),
        )
