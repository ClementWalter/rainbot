"""Unit tests for `ParisTennisClient` control-flow and error guardrails."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from paris_tennis_api.client import ParisTennisClient, ProfileTab
from paris_tennis_api.config import ParisTennisSettings
from paris_tennis_api.exceptions import AuthenticationError, BookingError
from paris_tennis_api.models import (
    AntiBotConfig,
    AntiBotToken,
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

    def post(
        self, _url: str, *, form: dict[str, str], timeout: int
    ) -> _FakePostResponse:
        """Return a deterministic response and keep the submitted form for assertions."""

        _ = timeout
        self.last_form = form
        return self._response


class _FakePage:
    """Page test-double that captures interactions used by search operations."""

    def __init__(
        self, *, urls_after_goto: tuple[str, ...], html: str = "<html></html>"
    ) -> None:
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


class _NoopContext:
    """Context manager shim for page.expect_navigation in booking flow tests."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


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

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
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
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_search_catalog", lambda _html: _catalog()
    )
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
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_search_catalog", lambda _html: _catalog()
    )

    client.get_search_catalog(force_refresh=True)
    assert (called["clear"], fake_page.goto_calls) == (1, 2)


def test_search_slots_clears_pending_booking_before_submitting(monkeypatch) -> None:
    """Search retries after a stuck booking should clear the wizard, not crash in JS."""

    fake_page = _FakePage(
        urls_after_goto=(
            # First goto lands on the blocked booking wizard (previous flow stuck).
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=methode_paiement",
            # After clearing, the second goto lands on the real search page.
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche",
        )
    )
    client = _authenticated_client()
    called = {"clear": 0}
    expected_result = SearchResult(
        slots=(_slot(),), captcha_request_id="captcha-request"
    )
    request = SearchRequest(
        venue_name="Alain Mimoun",
        date_iso="12/04/2026",
        hour_start=8,
        hour_end=9,
        surface_ids=("1324",),
        in_out_codes=("V",),
    )

    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())
    monkeypatch.setattr(client, "_require_page", lambda: fake_page)
    monkeypatch.setattr(
        client,
        "_clear_pending_booking",
        lambda: called.__setitem__("clear", called["clear"] + 1),
    )
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_search_result", lambda _html: expected_result
    )
    client.search_slots(request)
    assert (called["clear"], fake_page.goto_calls) == (1, 2)


def test_search_slots_submits_expected_payload(monkeypatch) -> None:
    """Search should transform request data into the browser payload expected by page JS."""

    fake_page = _FakePage(
        urls_after_goto=(
            "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=recherche",
        )
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
    expected_result = SearchResult(
        slots=(_slot(),), captcha_request_id="captcha-request"
    )

    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())
    monkeypatch.setattr(client, "_require_page", lambda: fake_page)
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_search_result", lambda _html: expected_result
    )

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


def test_cancel_current_reservation_returns_false_when_nothing_active(
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        client,
        "search_slots",
        lambda _request: SearchResult(slots=(), captcha_request_id=""),
    )

    with pytest.raises(BookingError):
        client.book_first_available(days_in_advance=2)


def test_book_first_available_raises_when_profile_does_not_show_booking(
    monkeypatch,
) -> None:
    """After booking call returns, helper must verify profile state before returning success."""

    client = _authenticated_client()
    monkeypatch.setattr(client, "get_search_catalog", lambda: _catalog())
    monkeypatch.setattr(
        client,
        "search_slots",
        lambda _request: SearchResult(
            slots=(_slot(),), captcha_request_id="captcha-id"
        ),
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
        client.book_first_available(
            days_in_advance=3, preferred_venues=("Alain Mimoun",)
        )

    assert observed["date"] == expected_date


def test_from_settings_transfers_runtime_values() -> None:
    """from_settings should preserve credentials and headless mode on client creation."""

    settings = ParisTennisSettings(
        email="user@example.com",
        password="secret",
        captcha_api_key="captcha",
        headless=False,
    )
    client = ParisTennisClient.from_settings(settings)
    assert (client._email, client._password, client._headless) == (
        "user@example.com",
        "secret",
        False,
    )


def test_context_manager_opens_and_closes_client(monkeypatch) -> None:
    """Context manager should call open/close exactly once to manage browser resources."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    state = {"open": 0, "close": 0}
    monkeypatch.setattr(
        client, "open", lambda: state.__setitem__("open", state["open"] + 1)
    )
    monkeypatch.setattr(
        client, "close", lambda: state.__setitem__("close", state["close"] + 1)
    )
    with client:
        pass
    assert (state["open"], state["close"]) == (1, 1)


def test_login_sets_authenticated_flag(monkeypatch) -> None:
    """Successful login should mark the client as authenticated for protected methods."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    page = MagicMock()
    page.goto.return_value = SimpleNamespace(status=200)
    username = MagicMock()
    username.count.return_value = 1
    submit = MagicMock()
    page.locator.side_effect = lambda selector: (
        username if selector == "#username" else submit
    )
    page.content.return_value = "<html>ok</html>"
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_profile_reservation",
        lambda html: ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="profile",
        ),
    )
    client.login()
    assert client._is_authenticated is True


def test_login_rejects_http_error(monkeypatch) -> None:
    """Login entrypoint HTTP failures should raise AuthenticationError."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    page = MagicMock()
    page.goto.return_value = SimpleNamespace(status=403)
    monkeypatch.setattr(client, "_require_page", lambda: page)
    with pytest.raises(AuthenticationError):
        client.login()


def test_login_requires_username_input(monkeypatch) -> None:
    """Missing username input indicates broken auth page and should fail immediately."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    page = MagicMock()
    page.goto.return_value = SimpleNamespace(status=200)
    username = MagicMock()
    username.count.return_value = 0
    page.locator.return_value = username
    monkeypatch.setattr(client, "_require_page", lambda: page)
    with pytest.raises(AuthenticationError):
        client.login()


def test_login_rejects_empty_profile_summary(monkeypatch) -> None:
    """Post-login profile validation should fail when parser returns empty text."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    page = MagicMock()
    page.goto.return_value = SimpleNamespace(status=200)
    username = MagicMock()
    username.count.return_value = 1
    submit = MagicMock()
    page.locator.side_effect = lambda selector: (
        username if selector == "#username" else submit
    )
    page.content.return_value = "<html>empty</html>"
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_profile_reservation",
        lambda html: ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="",
        ),
    )
    with pytest.raises(AuthenticationError):
        client.login()


def test_book_slot_runs_browser_flow(monkeypatch) -> None:
    """book_slot should run captcha submission and final step hooks before returning HTML."""

    client = _authenticated_client()
    page = MagicMock()
    page.expect_navigation.return_value = _NoopContext()
    page.content.return_value = "<html>final</html>"
    page.url = "https://tennis.paris.fr/captcha"
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_antibot_config",
        lambda html: AntiBotConfig(
            method="IMAGE",
            fallback_method="AUDIO",
            locale="FR",
            sp_key="sp",
            base_url="https://captcha.liveidentity.com/captcha",
            container_id="li-antibot",
            custom_css_url=None,
            antibot_id="ab",
            request_id="rq",
        ),
    )
    client._captcha_solver = MagicMock()
    client._captcha_solver.solve.return_value = AntiBotToken(
        container_id="li-antibot",
        token="token",
        token_code="code",
    )
    monkeypatch.setattr(client, "_submit_validation_step", lambda: None)
    monkeypatch.setattr(client, "_submit_payment_step", lambda: None)
    html = client.book_slot(slot=_slot(), captcha_request_id="captcha-request-id")
    assert html == "<html>final</html>"


def test_get_profile_tab_returns_html_when_authenticated(monkeypatch) -> None:
    """Profile tab helper should navigate and return page HTML for authenticated users."""

    client = _authenticated_client()
    page = MagicMock()
    page.content.return_value = "<html>profile</html>"
    monkeypatch.setattr(client, "_require_page", lambda: page)
    html = client.get_profile_tab(ProfileTab.MA_RESERVATION)
    assert html == "<html>profile</html>"


def test_get_profile_tab_requires_authentication() -> None:
    """Profile tab helper should reject anonymous client state."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    with pytest.raises(AuthenticationError):
        client.get_profile_tab(ProfileTab.MA_RESERVATION)


def test_get_all_profile_tabs_aggregates_each_enum_tab(monkeypatch) -> None:
    """Bulk profile helper should map every profile tab to fetched HTML."""

    client = _authenticated_client()
    monkeypatch.setattr(client, "get_profile_tab", lambda tab: tab.value)
    tabs = client.get_all_profile_tabs()
    assert set(tabs) == set(ProfileTab)


def test_get_current_reservation_parses_profile_tab(monkeypatch) -> None:
    """Current reservation should parse MA_RESERVATION tab via parser utility."""

    client = _authenticated_client()
    monkeypatch.setattr(
        client, "get_profile_tab", lambda tab: "<html>reservation</html>"
    )
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_profile_reservation",
        lambda html: ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="active",
        ),
    )
    summary = client.get_current_reservation()
    assert summary.has_active_reservation is True


def test_get_available_tickets_parses_ticket_tab(monkeypatch) -> None:
    """Ticket helper should parse CARNET_RESERVATION tab via ticket parser utility."""

    client = _authenticated_client()
    monkeypatch.setattr(client, "get_profile_tab", lambda tab: "<html>tickets</html>")
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_ticket_availability",
        lambda html: SimpleNamespace(tickets=(), raw_text="tickets"),
    )
    summary = client.get_available_tickets()
    assert summary.raw_text == "tickets"


def test_cancel_current_reservation_requires_authenticated_client() -> None:
    """Cancellation should enforce authenticated client state."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    with pytest.raises(AuthenticationError):
        client.cancel_current_reservation()


def test_submit_validation_step_completes_with_minimal_page(monkeypatch) -> None:
    """Validation step should click submit even when player fields are unavailable."""

    client = _authenticated_client()
    page = MagicMock()
    # Simulate a successful navigation off the validation step so we assert the
    # happy path without tripping the new URL-progress guard.
    page.url = "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=methode_paiement"
    players = MagicMock()
    players.count.return_value = 0
    submit = MagicMock()
    page.locator.side_effect = lambda selector: (
        players if selector == "input[name='player1']" else submit
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    client._submit_validation_step()
    assert submit.click.called is True


def test_submit_validation_step_raises_when_url_does_not_advance(monkeypatch) -> None:
    """Validation step must raise when URL stays on reservation_creneau after submit."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=reservation_creneau"
    players = MagicMock()
    players.count.return_value = 2
    submit = MagicMock()
    page.locator.side_effect = lambda selector: (
        players if selector == "input[name='player1']" else submit
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    with pytest.raises(BookingError):
        client._submit_validation_step()


def _payment_page_locator_router(
    *,
    cards_by_mode: dict[str, MagicMock],
    missing_card: MagicMock,
    submit: MagicMock,
):
    """Build a locator side-effect that distinguishes paymentmode selectors from #submit."""

    def _router(selector: str) -> MagicMock:
        for mode, card in cards_by_mode.items():
            if selector == f"table[paymentmode='{mode}']":
                return card
        if selector.startswith("table[paymentmode="):
            return missing_card
        return submit

    return _router


def test_submit_payment_step_refuses_when_only_paid_ticket_mode_available(
    monkeypatch,
) -> None:
    """Account without prepaid balance must raise instead of clicking into payfip."""

    client = _authenticated_client()
    page = MagicMock()
    page.evaluate.return_value = ["ticket"]
    missing_card = MagicMock()
    missing_card.count.return_value = 0
    submit = MagicMock()
    page.locator.side_effect = _payment_page_locator_router(
        cards_by_mode={},
        missing_card=missing_card,
        submit=submit,
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    with pytest.raises(BookingError) as excinfo:
        client._submit_payment_step()
    # The error must flag that a paid option was deliberately skipped so the
    # user can decide to top up or book a different venue.
    assert (
        submit.click.called is False
        and "payfip" in str(excinfo.value)
        and "ticket" in str(excinfo.value)
    )


def test_submit_payment_step_prefers_wallet_over_legacy_existing_ticket(
    monkeypatch,
) -> None:
    """Wallet (current prepaid naming) must win against existingTicket (legacy)."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=reservation_confirmation"
    page.evaluate.return_value = ["wallet", "wallet", "existingTicket"]
    wallet_card = MagicMock()
    wallet_card.count.return_value = 2
    wallet_card.first = MagicMock()
    existing_card = MagicMock()
    existing_card.count.return_value = 1
    existing_card.first = MagicMock()
    missing_card = MagicMock()
    missing_card.count.return_value = 0
    submit = MagicMock()
    page.locator.side_effect = _payment_page_locator_router(
        cards_by_mode={
            "wallet": wallet_card,
            "existingTicket": existing_card,
        },
        missing_card=missing_card,
        submit=submit,
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    client._submit_payment_step()
    assert (
        wallet_card.first.click.called is True
        and existing_card.first.click.called is False
    )


def test_submit_payment_step_raises_when_redirected_to_payfip(monkeypatch) -> None:
    """Any payfip redirect must abort the flow so we never silently auto-charge."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://www.payfip.gouv.fr/tpa/tpa.web"
    page.evaluate.return_value = ["wallet"]
    wallet_card = MagicMock()
    wallet_card.count.return_value = 1
    wallet_card.first = MagicMock()
    missing_card = MagicMock()
    missing_card.count.return_value = 0
    submit = MagicMock()
    page.locator.side_effect = _payment_page_locator_router(
        cards_by_mode={"wallet": wallet_card},
        missing_card=missing_card,
        submit=submit,
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    with pytest.raises(BookingError) as excinfo:
        client._submit_payment_step()
    assert "payfip" in str(excinfo.value)


def test_submit_payment_step_raises_with_diagnostic_when_url_does_not_advance(
    monkeypatch,
) -> None:
    """Payment step must raise a diagnostic error when URL stays at methode_paiement."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=methode_paiement"
    page.evaluate.return_value = ["creditCard"]
    missing_card = MagicMock()
    missing_card.count.return_value = 0
    submit = MagicMock()
    page.locator.side_effect = _payment_page_locator_router(
        cards_by_mode={},
        missing_card=missing_card,
        submit=submit,
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    with pytest.raises(BookingError) as excinfo:
        client._submit_payment_step()
    assert "creditCard" in str(excinfo.value)


def test_clear_pending_booking_handles_reservation_captcha_flow(monkeypatch) -> None:
    """Pending-booking cleanup should solve captcha and call validation+abort steps."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://tennis.paris.fr/reservation_captcha/reservation_creneau/methode_paiement"
    page.expect_navigation.return_value = _NoopContext()
    page.content.return_value = "<html>captcha</html>"
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr(
        "paris_tennis_api.client.parse_antibot_config",
        lambda html: AntiBotConfig(
            method="IMAGE",
            fallback_method="AUDIO",
            locale="FR",
            sp_key="sp",
            base_url="https://captcha.liveidentity.com/captcha",
            container_id="li-antibot",
            custom_css_url=None,
            antibot_id="ab",
            request_id="rq",
        ),
    )
    client._captcha_solver = MagicMock()
    client._captcha_solver.solve.return_value = AntiBotToken(
        container_id="li-antibot",
        token="token",
        token_code="code",
    )
    called = {"validation": 0}
    monkeypatch.setattr(
        client,
        "_submit_validation_step",
        lambda: called.__setitem__("validation", called["validation"] + 1),
    )
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    client._clear_pending_booking()
    assert called["validation"] == 1


def test_open_initializes_playwright_handles(monkeypatch) -> None:
    """open() should create playwright, browser, context, and page handles."""

    page = MagicMock()
    context = MagicMock()
    context.new_page.return_value = page
    browser = MagicMock()
    browser.new_context.return_value = context
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.start.return_value = playwright
    monkeypatch.setattr("paris_tennis_api.client.sync_playwright", lambda: manager)
    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    client.open()
    assert client._page is page


def test_close_clears_playwright_handles() -> None:
    """close() should reset internal handles to None after cleanup calls."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    client._context = MagicMock()
    client._browser = MagicMock()
    client._playwright = MagicMock()
    client._page = MagicMock()
    client.close()
    assert (client._context, client._browser, client._playwright, client._page) == (
        None,
        None,
        None,
        None,
    )


def test_request_property_raises_when_context_is_missing(monkeypatch) -> None:
    """Request property should raise when open() does not create a browser context."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    monkeypatch.setattr(client, "open", lambda: None)
    with pytest.raises(RuntimeError):
        _ = client._request


def test_require_page_raises_when_open_keeps_page_none(monkeypatch) -> None:
    """_require_page should fail fast when page handle is still unavailable."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    monkeypatch.setattr(client, "open", lambda: None)
    with pytest.raises(RuntimeError):
        client._require_page()


def test_require_page_returns_existing_page_handle(monkeypatch) -> None:
    """_require_page should return existing page handle when client is already initialized."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    page = object()
    client._page = page
    monkeypatch.setattr(client, "open", lambda: None)
    assert client._require_page() is page


def test_require_authenticated_optional_mode_skips_check() -> None:
    """optional=True should bypass auth failure for flows that permit anonymous access."""

    client = ParisTennisClient(
        email="user@example.com", password="pwd", captcha_api_key="captcha"
    )
    client._require_authenticated(optional=True)
    assert True


def test_submit_validation_step_fills_two_player_fields(monkeypatch) -> None:
    """Validation helper should fill both partner fields when they are present."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=methode_paiement"
    players = MagicMock()
    players.count.return_value = 2
    first = MagicMock()
    second = MagicMock()
    players.nth.side_effect = [first, second]
    submit = MagicMock()
    page.locator.side_effect = lambda selector: (
        players if selector == "input[name='player1']" else submit
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    client._submit_validation_step()
    assert (first.fill.call_args.args[0], second.fill.call_args.args[0]) == (
        "Partenaire",
        "Test",
    )


def test_submit_payment_step_clicks_existing_ticket_as_legacy_fallback(
    monkeypatch,
) -> None:
    """Legacy accounts that only expose existingTicket must still book successfully."""

    client = _authenticated_client()
    page = MagicMock()
    page.url = "https://tennis.paris.fr/tennis/jsp/site/Portal.jsp?page=reservation&view=reservation_confirmation"
    page.evaluate.return_value = ["existingTicket"]
    card = MagicMock()
    card.count.return_value = 1
    card.first = MagicMock()
    missing_card = MagicMock()
    missing_card.count.return_value = 0
    submit = MagicMock()
    page.locator.side_effect = _payment_page_locator_router(
        cards_by_mode={"existingTicket": card},
        missing_card=missing_card,
        submit=submit,
    )
    monkeypatch.setattr(client, "_require_page", lambda: page)
    monkeypatch.setattr("paris_tennis_api.client.time.sleep", lambda *_: None)
    client._submit_payment_step()
    assert card.first.click.called is True


def test_book_first_available_falls_back_to_all_venues_when_none_available(
    monkeypatch,
) -> None:
    """Fallback venue selection should include all venues when none are marked available_now."""

    client = _authenticated_client()
    catalog = _catalog()
    catalog.venues["Alain Mimoun"] = TennisVenue(
        venue_id="327",
        name="Alain Mimoun",
        available_now=False,
        courts=(TennisCourt(court_id="3096", name="Court 6"),),
    )
    monkeypatch.setattr(client, "get_search_catalog", lambda: catalog)
    monkeypatch.setattr(
        client,
        "search_slots",
        lambda request: SearchResult(
            slots=(_slot(),) if request.venue_name == "Alain Mimoun" else (),
            captcha_request_id="captcha-id",
        ),
    )
    monkeypatch.setattr(client, "book_slot", lambda slot, captcha_request_id: None)
    monkeypatch.setattr(
        client,
        "get_current_reservation",
        lambda: ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="active",
        ),
    )
    reservation = client.book_first_available(days_in_advance=2)
    assert reservation.venue_name == "Alain Mimoun"
