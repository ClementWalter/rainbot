"""User model representing a RainBot subscriber."""

from dataclasses import dataclass
from typing import Optional


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
        phone: Optional phone number for SMS notifications
    """

    id: str
    email: str
    paris_tennis_email: str
    paris_tennis_password: str
    name: Optional[str] = None
    subscription_active: bool = True
    phone: Optional[str] = None

    def is_eligible(self) -> bool:
        """Check if user is eligible for automated booking."""
        return (
            self.subscription_active
            and bool(self.paris_tennis_email)
            and bool(self.paris_tennis_password)
        )

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """
        Create a User from a dictionary (e.g., from Google Sheets).

        Args:
            data: Dictionary with user fields

        Returns:
            User instance
        """
        # Parse subscription_active - handle various truthy representations
        subscription_value = data.get("subscription_active", True)
        subscription_active = subscription_value in (True, "true", "True", "1", 1)

        return cls(
            id=str(data.get("id", "")),
            email=str(data.get("email", "")),
            paris_tennis_email=str(data.get("paris_tennis_email", "")),
            paris_tennis_password=str(data.get("paris_tennis_password", "")),
            name=data.get("name") or None,
            subscription_active=subscription_active,
            phone=data.get("phone") or None,
        )
