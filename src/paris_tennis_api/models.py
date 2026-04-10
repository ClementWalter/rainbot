"""Domain models used by the Paris Tennis API client."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from paris_tennis_api.exceptions import ValidationError


class ProfileTab(str, Enum):
    """Supported profile tabs exposed by the Paris Tennis website."""

    MA_RESERVATION = "jsp/site/Portal.jsp?page=profil&view=ma_reservation"
    MES_COORDONNEES = "jsp/site/Portal.jsp?page=tennis&view=profil_inscription"
    MON_TARIF = "jsp/site/Portal.jsp?page=tennis&view=profil_tarif"
    CARNET_RESERVATION = "jsp/site/Portal.jsp?page=profil&view=carnet_reservation"
    HISTORIQUE_FACTURES = "jsp/site/Portal.jsp?page=profil&view=historique_reservation"


@dataclass(frozen=True, slots=True)
class TennisCourt:
    """Court metadata scraped from the search catalog."""

    court_id: str
    name: str


@dataclass(frozen=True, slots=True)
class TennisVenue:
    """Venue metadata scraped from the search catalog."""

    venue_id: str
    name: str
    available_now: bool
    courts: tuple[TennisCourt, ...]


@dataclass(frozen=True, slots=True)
class SearchCatalog:
    """Search options used for strict local validation before search/booking calls."""

    venues: dict[str, TennisVenue]
    date_options: tuple[str, ...]
    surface_options: dict[str, str]
    in_out_options: dict[str, str]
    min_hour: int
    max_hour: int


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """User search request with local validation against scraped options."""

    venue_name: str
    date_iso: str
    hour_start: int
    hour_end: int
    surface_ids: tuple[str, ...]
    in_out_codes: tuple[str, ...]

    def validate(self, catalog: SearchCatalog) -> None:
        """Validate locally so invalid requests never hit booking endpoints."""

        if self.venue_name not in catalog.venues:
            raise ValidationError(f"Unknown venue '{self.venue_name}'.")
        if self.date_iso not in catalog.date_options:
            raise ValidationError(f"Unknown date '{self.date_iso}'.")
        if not catalog.min_hour <= self.hour_start < self.hour_end <= catalog.max_hour:
            raise ValidationError(
                f"Invalid hour range '{self.hour_start}-{self.hour_end}'."
            )
        for surface_id in self.surface_ids:
            if surface_id not in catalog.surface_options:
                raise ValidationError(f"Unknown surface '{surface_id}'.")
        for in_out_code in self.in_out_codes:
            if in_out_code not in catalog.in_out_options:
                raise ValidationError(f"Unknown covered/outdoor code '{in_out_code}'.")


@dataclass(frozen=True, slots=True)
class SlotOffer:
    """A single reservable slot extracted from search results."""

    equipment_id: str
    court_id: str
    date_deb: str
    date_fin: str
    price_eur: str
    price_label: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Parsed search result payload including slots and captcha request id."""

    slots: tuple[SlotOffer, ...]
    captcha_request_id: str


@dataclass(frozen=True, slots=True)
class ReservationSummary:
    """Current reservation summary parsed from the profile page."""

    has_active_reservation: bool
    cancellation_token: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class AntiBotConfig:
    """Captcha configuration extracted from LI_ANTIBOT initialization."""

    method: str
    fallback_method: str
    locale: str
    sp_key: str
    base_url: str
    container_id: str
    custom_css_url: str | None
    antibot_id: str | None
    request_id: str | None


@dataclass(frozen=True, slots=True)
class AntiBotToken:
    """Resolved token that must be posted back to reservation captcha form."""

    container_id: str
    token: str
    token_code: str


@dataclass(frozen=True, slots=True)
class BookedReservation:
    """Booked reservation details returned by high-level booking helpers."""

    venue_name: str
    slot: SlotOffer
