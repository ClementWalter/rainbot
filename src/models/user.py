"""User model representing a RainBot subscriber."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """
    A RainBot user with Paris Tennis credentials.

    Attributes:
        id: Unique identifier for the user
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
    subscription_active: bool = True
    phone: Optional[str] = None

    def is_eligible(self) -> bool:
        """Check if user is eligible for automated booking."""
        return (
            self.subscription_active
            and bool(self.paris_tennis_email)
            and bool(self.paris_tennis_password)
        )
