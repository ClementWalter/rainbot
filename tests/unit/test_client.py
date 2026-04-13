"""Unit tests for `ParisTennisClient` control-flow and error guardrails."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.exceptions import BookingError
from paris_tennis_api.models import (
    ReservationSummary,
    SearchCatalog,
    SearchRequest,
    SearchResult,
    SlotOffer,
    TennisCourt,
    TennisVenue,
)


@dataclass
class _FakePostResponse:
    """Minimal request response object used by cancellation tests."""

    ok: bool
    status: int


class _FakeRequestContext:
    """Stub request context that records posted cancellation payloads."""

    def __init__(self, response: _FakePostResponse) -> None:
        self._response = response
        self.last_form: dict[str, str] | None = None

    def post(self, _url: str, *, form: dict[str, str], timeout: int) -> _FakePostResponse:
        """Return a deterministic response and keep the submitted form for assertions."""

        _ = timeout
        self.last_form = form
        return self._response


class _FakePage:
    """Page test-double that captures interactions used by search operations."""

    def __init__(self, *, urls_after_goto: tuple[str, ...], html: str = "<html></html>") -> None:
        self._urls_after_goto = iter(urls_after_goto)
        self._html = html
        self.url = "about:blank"
        self.goto_calls = 0
        self.last_evaluate_payload: dict[str, object] | None = None

    def goto(self, _url: str, **_kwargs: object) -> None:
        """Advance through configured URL states so tests can simulate redirects."""

        self.goto_calls += 1
        self.url = next(self._urls_after_goto)

    def evaluate(self, _script: str, payload: dict[str, object]) -> None:
        """Capture payload so tests can verify generated booking/search parameters."""

        self.last_evaluate_payload = payload

    def wait_for_url(self, _pattern: str, timeout: int) -> None:
        """No-op wait used to mirror Playwright control flow without browser startup."""

        _ = timeout

    def content(self) -> str:
        """Return deterministic HTML content for parser monkeypatches."""

        return self._html


def _catalog() -> SearchCatalog:
    """Create a reusable catalog fixture with two venues and one available slot option."""

    return SearchCatalog(
        venues={
            "Unavailable Venue": TennisVenue(
                venue_id="10",
                name="Unavailable Venue",
                available_now=False,
                courts=(TennisCourt(court_id="c-10", name="Court A"),),
            ),
            "Alain Mimoun": TennisVenue(
                venue_id="327",
                name="Alain Mimoun",
                available_now=True,
                courts=(TennisCourt(court_id="3096", name="Court 6"),),
            ),
        },
        date_options=("12/04/2026",),
        surface_options={"1324": "Beton"},
        in_out_options={"V": "Couvert"},
        min_hour=8,
        max_hour=22,
    )


def _slot(*, equipment_id: str = "eq-1") -> SlotOffer:
    """Create a deterministic slot payload used by booking and search tests."""

    return SlotOffer(
        equipment_id=equipment_id,
        court_id="court-1",
        date_deb="2026/04/12 08:00:00",
        date_fin="2026/04/12 09:00:00",
        price_eur="12",
        price_label="Tarif plein",
    )


def _authenticated_client() -> ParisTennisClient:
    """Build a client in authenticated state without opening a real browser."""

    client = ParisTennisClient(email="user@example.com", password="pwd", captcha_api_key="captcha")
    client._is_authenticated = True
    return client


def test_get_search_catalog_uses_cache_without_second_navigation(monkeypatch) -> None:
    """Catalog cache should avoid duplicate page navigation for repeated callers."""

    fake_page = _FakePage(
        urls_after_goto=(
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche",
        )
    )
    client = _authenticated_client()
    monkeypatch.setattr(client, "_require_page", lambda: fake_page)
    monkeypatch.setattr("paris_tennis_api.client.parse_search_catalog", lambda _html: _catalog())
    first = client.get_search_catalog()
    second = client.get_search_catalog()
    assert (first is second, fake_page.goto_calls) == (True, 1)


def test_get_search_catalog_clears_pending_booking_then_retries(monkeypatch) -> None:
    """When redirected into stale booking flow, client should clear it and reload search."""

    fake_page = _FakePage(
        urls_after_goto=(
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=reservation_captcha",
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche",
        )
    )
    client = _authenticated_client()
    called = {"clear": 0}

    monkeypatch.setattr(client, "_require_page", lambda: fake_page)
    monkeypatch.setattr(
        client,
        "_clear_pending_booking",
        lambda: called.__setitem__("clear", called["clear"] + 1),
    )
    monkeypatch.setattr("paris_tennis_api.client.parse_search_catalog", lambda _html: _catalog())

    client.get_search_catalog(force_refresh=True)
    assert (called["clear"], fake_page.goto_calls) == (1, 2)


def test_search_slots_submits_expected_payload(monkeypatch) -> None:
    """Search should transform request data into the browser payload expected by page JS."""

    fake_page = _FakePage(
        urls_after_goto=("https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche",)
    )
    client = _authenticated_client()
    request = SearchRequest(
        venue_name="Alain Mimoun",
        date_iso="12/04/2026",
        hour_start=8,
        hour_end=9,
        surface_ids=("1324",),
        in_out_codes=("V",),
    )
    expected_result = SearchResult(slots=(_slot(),), captcha_request_id="captcha-request")

    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())
    monkeypatch.setattr(client, "_require_page", lambda: fake_page)
    monkeypatch.setattr("paris_tennis_api.client.parse_search_result", lambda _html: expected_result)

    result = client.search_slots(request)
    assert (
        result,
        fake_page.last_evaluate_payload,
    ) == (
        expected_result,
        {
            "venueName": "Alain Mimoun",
            "dateIso": "12/04/2026",
            "hourRange": "8-9",
            "surfaceIds": ["1324"],
            "inOutCodes": ["V"],
        },
    )


def test_book_slot_requires_captcha_request_id() -> None:
    """Booking must fail fast when search results do not provide request correlation id."""

    client = _authenticated_client()
    with pytest.raises(BookingError):
        client.book_slot(slot=_slot(), captcha_request_id="   ")


def test_cancel_current_reservation_returns_false_when_nothing_active(monkeypatch) -> None:
    """Cancellation should be a no-op when profile already has no active reservation."""

    client = _authenticated_client()
    monkeypatch.setattr(
        client,
        "get_current_reservation",
        lambda: ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="no reservation",
        ),
    )
    assert client.cancel_current_reservation() is False


def test_cancel_current_reservation_raises_when_api_post_fails(monkeypatch) -> None:
    """HTTP errors from cancellation endpoint should surface as typed booking errors."""

    client = _authenticated_client()
    monkeypatch.setattr(
        client,
        "get_current_reservation",
        lambda: ReservationSummary(
            has_active_reservation=True,
            cancellation_token="cancel-token",
            raw_text="active",
        ),
    )
    fake_request = _FakeRequestContext(response=_FakePostResponse(ok=False, status=500))
    client._page = object()
    client._context = SimpleNamespace(request=fake_request)

    with pytest.raises(BookingError):
        client.cancel_current_reservation()


def test_cancel_current_reservation_posts_token_and_confirms_state(monkeypatch) -> None:
    """Successful cancellation should post the profile token and verify inactive refresh."""

    client = _authenticated_client()
    summaries = iter(
        (
            ReservationSummary(
                has_active_reservation=True,
                cancellation_token="cancel-token",
                raw_text="active",
            ),
            ReservationSummary(
                has_active_reservation=False,
                cancellation_token="",
                raw_text="inactive",
            ),
        )
    )
    monkeypatch.setattr(client, "get_current_reservation", lambda: next(summaries))

    fake_request = _FakeRequestContext(response=_FakePostResponse(ok=True, status=200))
    client._page = object()
    client._context = SimpleNamespace(request=fake_request)

    canceled = client.cancel_current_reservation()
    assert (canceled, fake_request.last_form) == (
        True,
        {"annulation": "true", "token": "cancel-token"},
    )


def test_book_first_available_rejects_days_under_two() -> None:
    """High-level booking helper should enforce a minimum advance booking horizon."""

    client = _authenticated_client()
    with pytest.raises(BookingError):
        client.book_first_available(days_in_advance=1)


def test_book_first_available_uses_first_available_venue(monkeypatch) -> None:
    """Booking helper should iterate venues and stop at the first venue with slots."""

    client = _authenticated_client()
    catalog = _catalog()
    captured: dict[str, str] = {}
    target_slot = _slot(equipment_id="eq-booked")

    def _search(request: SearchRequest) -> SearchResult:
        if request.venue_name == "Unavailable Venue":
            return SearchResult(slots=(), captcha_request_id="")
        return SearchResult(slots=(target_slot,), captcha_request_id="captcha-id")

    monkeypatch.setattr(client, "get_search_catalog", lambda: catalog)
    monkeypatch.setattr(client, "search_slots", _search)
    monkeypatch.setattr(
        client,
        "book_slot",
        lambda slot, captcha_request_id: captured.update(
            {"slot": slot.equipment_id, "captcha": captcha_request_id}
        ),
    )
    monkeypatch.setattr(
        client,
        "get_current_reservation",
        lambda: ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="active",
        ),
    )

    booked = client.book_first_available(
        days_in_advance=2,
        preferred_venues=("Unavailable Venue", "Alain Mimoun"),
    )
    assert (booked.venue_name, captured) == (
        "Alain Mimoun",
        {"slot": "eq-booked", "captcha": "captcha-id"},
    )


def test_book_first_available_raises_when_no_slot_exists(monkeypatch) -> None:
    """Booking helper should fail with explicit error when every venue search is empty."""

    client = _authenticated_client()
    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())
    monkeypatch.setattr(client, "search_slots", lambda _request: SearchResult(slots=(), captcha_request_id=""))

    with pytest.raises(BookingError):
        client.book_first_available(days_in_advance=2)


def test_book_first_available_raises_when_profile_does_not_show_booking(monkeypatch) -> None:
    """After booking call returns, helper must verify profile state before returning success."""

    client = _authenticated_client()
    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())
    monkeypatch.setattr(
        client,
        "search_slots",
        lambda _request: SearchResult(slots=(_slot(),), captcha_request_id="captcha-id"),
    )
    monkeypatch.setattr(client, "book_slot", lambda slot, captcha_request_id: None)
    monkeypatch.setattr(
        client,
        "get_current_reservation",
        lambda: ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="inactive",
        ),
    )

    with pytest.raises(BookingError):
        client.book_first_available(days_in_advance=2)


def test_book_first_available_passes_target_date_to_search(monkeypatch) -> None:
    """Search request date should use `today + days_in_advance` in DD/MM/YYYY format."""

    client = _authenticated_client()
    expected_date = (dt.date.today() + dt.timedelta(days=3)).strftime("%d/%m/%Y")
    observed: dict[str, str] = {}

    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())

    def _search(request: SearchRequest) -> SearchResult:
        observed["date"] = request.date_iso
        return SearchResult(slots=(), captcha_request_id="")

    monkeypatch.setattr(client, "search_slots", _search)

    with pytest.raises(BookingError):
        client.book_first_available(days_in_advance=3, preferred_venues=("Alain Mimoun",))

    assert observed["date"] == expected_date
