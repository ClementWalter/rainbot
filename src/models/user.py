"""User model representing a RainBot subscriber."""

from dataclasses import dataclass
from typing import Optional

from src.utils.parsing import is_truthy


def _string_or_empty(value: object) -> str:
    """Return a stripped string or empty string for None."""
    if value is None:
        return ""
    return str(value).strip()


@dataclass
class User:
    """
    A RainBot user with Paris Tennis credentials.

    Attributes:
        id: Unique identifier for the user
        name: User's display name (for personalized notifications)
        email: User's email address (used for notifications)
        paris_tennis_email: Email used for Paris Tennis account login
        paris_tennis_password: Password for Paris Tennis account
        subscription_active: Whether the user has an active RainBot subscription
        carnet_balance: Remaining tickets in the user's Paris Tennis carnet
        phone: Optional phone number for SMS notifications

    """

    id: str
    email: str
    paris_tennis_email: str
    paris_tennis_password: str
    name: Optional[str] = None
    subscription_active: bool = True
    carnet_balance: Optional[int] = None
    phone: Optional[str] = None

    def is_eligible(self) -> bool:
        """Check if user is eligible for automated booking."""
        if not (
            self.subscription_active
            and bool(self.paris_tennis_email)
            and bool(self.paris_tennis_password)
        ):
            return False

        if self.carnet_balance is not None and self.carnet_balance <= 0:
            return False

        return True

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """
        Create a User from a dictionary (e.g., from Google Sheets).

        Args:
            data: Dictionary with user fields

        Returns:
            User instance

        """
        # Parse subscription_active - handle common truthy representations (case-insensitive)
        subscription_value = data.get("subscription_active", True)
        if subscription_value is None:
            subscription_value = True
        elif isinstance(subscription_value, str) and not subscription_value.strip():
            subscription_value = True
        subscription_active = is_truthy(subscription_value)

        carnet_balance_value = data.get("carnet_balance")
        carnet_balance: Optional[int] = None
        if carnet_balance_value is not None and str(carnet_balance_value).strip() != "":
            try:
                if isinstance(carnet_balance_value, (int, float)):
                    carnet_balance = int(carnet_balance_value)
                else:
                    carnet_balance = int(float(str(carnet_balance_value).strip()))
            except (TypeError, ValueError):
                carnet_balance = None

        return cls(
            id=_string_or_empty(data.get("id", "")),
            email=_string_or_empty(data.get("email", "")),
            paris_tennis_email=_string_or_empty(data.get("paris_tennis_email", "")),
            paris_tennis_password=_string_or_empty(data.get("paris_tennis_password", "")),
            name=data.get("name") or None,
            subscription_active=subscription_active,
            carnet_balance=carnet_balance,
            phone=data.get("phone") or None,
        )
