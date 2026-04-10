"""Public package exports for the Paris Tennis unofficial API."""

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.config import ParisTennisSettings
from paris_tennis_api.models import (
    ProfileTab,
    ReservationSummary,
    SearchRequest,
    SlotOffer,
    TicketAvailability,
    TicketAvailabilitySummary,
)

__all__ = [
    "ParisTennisClient",
    "ParisTennisSettings",
    "ProfileTab",
    "ReservationSummary",
    "SearchRequest",
    "SlotOffer",
    "TicketAvailability",
    "TicketAvailabilitySummary",
]
