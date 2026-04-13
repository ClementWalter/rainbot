"""Unit tests for CLI command wiring and argument handling."""

from __future__ import annotations

from dataclasses import dataclass

from paris_tennis_api.cli import build_parser, main
from paris_tennis_api.models import (
    ReservationSummary,
    SearchCatalog,
    SearchRequest,
    SearchResult,
    SlotOffer,
    TennisCourt,
    TennisVenue,
    TicketAvailability,
    TicketAvailabilitySummary,
)


@dataclass
class FakeClient:
    """Stub client used to test CLI command flow without browser interactions."""

    login_calls: int = 0
    catalog_calls: int = 0
    cancel_calls: int = 0
    tickets_calls: int = 0
    last_search_request: SearchRequest | None = None
    booked_slot: SlotOffer | None = None
    booked_captcha_request_id: str = ""

    def __post_init__(self) -> None:
        self.catalog = SearchCatalog(
            venues={
                "Alain Mimoun": TennisVenue(
                    venue_id="327",
                    name="Alain Mimoun",
                    available_now=True,
                    courts=(TennisCourt(court_id="3096", name="Court 6"),),
                )
            },
            date_options=("12/04/2026",),
            surface_options={"1324": "Beton"},
            in_out_options={"V": "Couvert"},
            min_hour=8,
            max_hour=22,
        )
        self.search_result = SearchResult(
            slots=(
                SlotOffer(
                    equipment_id="eq-1",
                    court_id="court-1",
                    date_deb="2026/04/12 08:00:00",
                    date_fin="2026/04/12 09:00:00",
                    price_eur="12",
                    price_label="Tarif plein",
                ),
            ),
            captcha_request_id="captcha-request-id",
        )
        self.reservation_summary = ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="Reservation active",
        )
        self.ticket_summary = TicketAvailabilitySummary(
            tickets=(TicketAvailability(label="Heures pleines", remaining="5h"),),
            raw_text="Heures pleines: 5h",
        )

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def login(self) -> None:
        self.login_calls += 1

    def get_search_catalog(self) -> SearchCatalog:
        self.catalog_calls += 1
        return self.catalog

    def search_slots(self, request: SearchRequest) -> SearchResult:
        self.last_search_request = request
        return self.search_result

    def book_slot(self, slot: SlotOffer, captcha_request_id: str) -> str:
        self.booked_slot = slot
        self.booked_captcha_request_id = captcha_request_id
        return "ok"

    def get_current_reservation(self) -> ReservationSummary:
        return self.reservation_summary

    def cancel_current_reservation(self) -> bool:
        self.cancel_calls += 1
        return True

    def get_available_tickets(self) -> TicketAvailabilitySummary:
        self.tickets_calls += 1
        return self.ticket_summary


@dataclass
class FakeClientFactory:
    """Callable adapter to inject fake client instances into CLI main()."""

    client: FakeClient

    def __call__(
        self,
        *,
        email: str,
        password: str,
        captcha_api_key: str,
        headless: bool,
    ) -> FakeClient:
        _ = (email, password, captcha_api_key, headless)
        return self.client


def test_build_parser_reads_username_and_password_from_env() -> None:
    """CLI credential defaults should come from expected environment variables."""

    args = build_parser(
        env={
            "PARIS_TENNIS_EMAIL": "user@example.com",
            "PARIS_TENNIS_PASSWORD": "secret",
        }
    ).parse_args(["list-courts"])
    assert (args.username, args.password) == ("user@example.com", "secret")


def test_main_list_courts_logs_in_and_loads_catalog() -> None:
    """Listing courts should authenticate once and hit the catalog endpoint once."""

    fake_client = FakeClient()
    exit_code = main(
        argv=["--username", "u", "--password", "p", "list-courts"],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert (exit_code, fake_client.login_calls, fake_client.catalog_calls) == (0, 1, 1)


def test_main_search_slots_uses_catalog_defaults_when_filters_are_missing() -> None:
    """Search command should fill optional filters from live catalog defaults."""

    fake_client = FakeClient()
    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "search-slots",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
        ],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert (
        exit_code,
        fake_client.last_search_request.hour_start,
        fake_client.last_search_request.hour_end,
        fake_client.last_search_request.surface_ids,
        fake_client.last_search_request.in_out_codes,
    ) == (0, 8, 22, ("1324",), ("V",))


def test_main_book_uses_selected_slot_index() -> None:
    """Book command should pass the chosen slot and captcha id to the client."""

    fake_client = FakeClient()
    fake_client.search_result = SearchResult(
        slots=(
            SlotOffer(
                equipment_id="eq-1",
                court_id="court-1",
                date_deb="2026/04/12 08:00:00",
                date_fin="2026/04/12 09:00:00",
                price_eur="12",
                price_label="Tarif plein",
            ),
            SlotOffer(
                equipment_id="eq-2",
                court_id="court-2",
                date_deb="2026/04/12 09:00:00",
                date_fin="2026/04/12 10:00:00",
                price_eur="15",
                price_label="Tarif plein",
            ),
        ),
        captcha_request_id="request-2",
    )

    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "--captcha-api-key",
            "captcha-key",
            "book",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
            "--slot-index",
            "2",
        ],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert (
        exit_code,
        fake_client.booked_slot.equipment_id,
        fake_client.booked_captcha_request_id,
    ) == (0, "eq-2", "request-2")


def test_main_cancel_calls_client_cancel() -> None:
    """Cancel command should call client cancellation exactly once."""

    fake_client = FakeClient()
    exit_code = main(
        argv=["--username", "u", "--password", "p", "cancel"],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert (exit_code, fake_client.cancel_calls) == (0, 1)


def test_main_tickets_calls_ticket_summary() -> None:
    """Tickets command should fetch profile ticket balances once."""

    fake_client = FakeClient()
    exit_code = main(
        argv=["--username", "u", "--password", "p", "tickets"],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert (exit_code, fake_client.tickets_calls) == (0, 1)


def test_main_book_requires_captcha_api_key() -> None:
    """Book command should fail before client creation when captcha key is missing."""

    def _unreachable_factory(**_: object) -> FakeClient:
        raise AssertionError("Client factory should not be called")

    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "book",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
        ],
        env={},
        client_factory=_unreachable_factory,
    )
    assert exit_code == 1


def test_main_list_courts_handles_venues_without_courts() -> None:
    """Listing courts should succeed even when one venue has no courts in catalog."""

    fake_client = FakeClient()
    fake_client.catalog = SearchCatalog(
        venues={
            "No Court Venue": TennisVenue(
                venue_id="1",
                name="No Court Venue",
                available_now=False,
                courts=(),
            )
        },
        date_options=("12/04/2026",),
        surface_options={"1324": "Beton"},
        in_out_options={"V": "Couvert"},
        min_hour=8,
        max_hour=22,
    )
    exit_code = main(
        argv=["--username", "u", "--password", "p", "list-courts"],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 0


def test_main_book_fails_when_no_slots_found() -> None:
    """Book command should fail clearly when search results have no slots."""

    fake_client = FakeClient()
    fake_client.search_result = SearchResult(slots=(), captcha_request_id="req")
    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "--captcha-api-key",
            "captcha-key",
            "book",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
        ],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 1


def test_main_book_fails_when_captcha_request_id_is_missing() -> None:
    """Book command should fail when result payload cannot be used for booking."""

    fake_client = FakeClient()
    fake_client.search_result = SearchResult(
        slots=(
            SlotOffer(
                equipment_id="eq-1",
                court_id="court-1",
                date_deb="2026/04/12 08:00:00",
                date_fin="2026/04/12 09:00:00",
                price_eur="12",
                price_label="Tarif plein",
            ),
        ),
        captcha_request_id="",
    )
    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "--captcha-api-key",
            "captcha-key",
            "book",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
        ],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 1


def test_main_book_fails_when_slot_index_is_out_of_range() -> None:
    """Book command should validate slot index before invoking booking flow."""

    fake_client = FakeClient()
    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "--captcha-api-key",
            "captcha-key",
            "book",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
            "--slot-index",
            "9",
        ],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 1


def test_main_book_fails_when_reservation_is_not_visible_after_booking() -> None:
    """Book command should fail if profile does not show reservation after booking."""

    fake_client = FakeClient()
    fake_client.reservation_summary = ReservationSummary(
        has_active_reservation=False,
        cancellation_token="",
        raw_text="none",
    )
    exit_code = main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "--captcha-api-key",
            "captcha-key",
            "book",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
        ],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 1


def test_main_cancel_succeeds_when_no_active_reservation_exists() -> None:
    """Cancel command should still return success when no reservation was active."""

    fake_client = FakeClient()
    fake_client.cancel_current_reservation = lambda: False
    exit_code = main(
        argv=["--username", "u", "--password", "p", "cancel"],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 0


def test_main_tickets_succeeds_when_no_ticket_rows_are_available() -> None:
    """Tickets command should handle empty ticket summaries without failing."""

    fake_client = FakeClient()
    fake_client.ticket_summary = TicketAvailabilitySummary(tickets=(), raw_text="")
    exit_code = main(
        argv=["--username", "u", "--password", "p", "tickets"],
        client_factory=FakeClientFactory(client=fake_client),
    )
    assert exit_code == 0
