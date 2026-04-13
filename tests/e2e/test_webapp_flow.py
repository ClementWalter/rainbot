"""End-to-end tests for the local webapp routes using an in-memory fake client."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from paris_tennis_api.models import (
    ReservationSummary,
    SearchCatalog,
    SearchRequest,
    SearchResult,
    SlotOffer,
    TennisCourt,
    TennisVenue,
)
from paris_tennis_api.webapp.main import create_app
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import WebAppStore


@dataclass
class FakeClientState:
    """Track interactions with the fake client across requests."""

    login_calls: int = 0
    search_calls: int = 0
    book_calls: int = 0
    search_requests: list[SearchRequest] = field(default_factory=list)


class FakeParisClient:
    """Stand-in for the real browser client so route tests stay fully local."""

    def __init__(self, *, state: FakeClientState, **_: object) -> None:
        self._state = state

    def __enter__(self) -> "FakeParisClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def login(self) -> None:
        self._state.login_calls += 1

    def search_slots(self, request: SearchRequest) -> SearchResult:
        self._state.search_calls += 1
        self._state.search_requests.append(request)
        return SearchResult(
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
            captcha_request_id="captcha-request",
        )

    def get_search_catalog(self, *, force_refresh: bool = False) -> SearchCatalog:
        _ = force_refresh
        return SearchCatalog(
            venues={
                "Alain Mimoun": TennisVenue(
                    venue_id="v-1",
                    name="Alain Mimoun",
                    available_now=True,
                    courts=(TennisCourt(court_id="c-1", name="Court 1"),),
                ),
                "Bercy": TennisVenue(
                    venue_id="v-2",
                    name="Bercy",
                    available_now=True,
                    courts=(TennisCourt(court_id="c-2", name="Court 2"),),
                ),
            },
            date_options=("12/04/2026",),
            surface_options={},
            in_out_options={"V": "Indoor", "E": "Outdoor"},
            min_hour=7,
            max_hour=23,
        )

    def book_slot(self, *, slot: SlotOffer, captcha_request_id: str) -> None:
        _ = (slot, captcha_request_id)
        self._state.book_calls += 1

    def get_current_reservation(self) -> ReservationSummary:
        return ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="Reservation active",
        )


class _CatalogSurfacesClient(FakeParisClient):
    """Catalog fake that exposes non-empty surface_options for parity tests."""

    def get_search_catalog(self, *, force_refresh: bool = False) -> SearchCatalog:
        _ = force_refresh
        return SearchCatalog(
            venues={
                "Alain Mimoun": TennisVenue(
                    venue_id="v-1",
                    name="Alain Mimoun",
                    available_now=True,
                    courts=(TennisCourt(court_id="c-1", name="Court 1"),),
                ),
            },
            date_options=("12/04/2026",),
            # Non-empty so we can assert "all surfaces" is forwarded on empty user input.
            surface_options={"beton": "Béton", "resine": "Résine"},
            in_out_options={"V": "Indoor", "E": "Outdoor"},
            min_hour=7,
            max_hour=23,
        )


class FakeSecondVenueOnlyParisClient(FakeParisClient):
    """Require second venue fallback to cover multi-select booking traversal."""

    def search_slots(self, request: SearchRequest) -> SearchResult:
        self._state.search_calls += 1
        self._state.search_requests.append(request)
        if request.venue_name == "Alain Mimoun":
            return SearchResult(slots=(), captcha_request_id="captcha-request")
        return SearchResult(
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
            captcha_request_id="captcha-request",
        )


def _build_bundle(
    tmp_path: Path,
    *,
    client_class: type[FakeParisClient] = FakeParisClient,
) -> tuple[TestClient, WebAppStore, FakeClientState]:
    """Build one fully isolated app instance with seeded admin account."""

    settings = WebAppSettings(
        database_path=tmp_path / "webapp.sqlite3",
        session_secret="test-secret",
        captcha_api_key="captcha-key",
        headless=True,
        host="127.0.0.1",
        port=8000,
        # Disable the background warmer so its thread does not race with test
        # assertions that count login/search calls against the fake client.
        warm_on_startup=False,
        # A low TTL keeps caching behavior exercised by tests without masking
        # bugs where a route accidentally reuses a stale catalog.
        catalog_ttl_seconds=60,
    )
    store = WebAppStore(settings.database_path)
    store.initialize()
    store.create_user(
        display_name="Admin",
        paris_username="admin@example.com",
        paris_password="secret",
        is_admin=True,
    )
    state = FakeClientState()

    def _client_factory(**kwargs: object) -> FakeParisClient:
        return client_class(state=state, **kwargs)

    app = create_app(settings=settings, store=store, client_factory=_client_factory)
    client = TestClient(app)
    return client, store, state


def _login(client: TestClient) -> None:
    """Authenticate once so each test can focus on one route behavior."""

    client.post(
        "/login",
        data={"paris_username": "admin@example.com", "paris_password": "secret"},
        follow_redirects=False,
    )


def test_bootstrap_admin_creates_first_user_when_store_is_empty(tmp_path: Path) -> None:
    """The first-run bootstrap endpoint should create exactly one admin user."""

    settings = WebAppSettings(
        database_path=tmp_path / "bootstrap.sqlite3",
        session_secret="test-secret",
        captcha_api_key="captcha-key",
        headless=True,
        host="127.0.0.1",
        port=8000,
        warm_on_startup=False,
        catalog_ttl_seconds=60,
    )
    store = WebAppStore(settings.database_path)
    store.initialize()
    state = FakeClientState()

    def _client_factory(**kwargs: object) -> FakeParisClient:
        return FakeParisClient(state=state, **kwargs)

    app = create_app(settings=settings, store=store, client_factory=_client_factory)
    with TestClient(app) as client:
        client.post(
            "/bootstrap-admin",
            data={
                "display_name": "Owner",
                "paris_username": "owner@example.com",
                "paris_password": "secret",
            },
            follow_redirects=False,
        )
    assert store.count_users() == 1


def test_set_saved_search_state_route_updates_search_state(tmp_path: Path) -> None:
    """State endpoint should flip a saved search between active and inactive."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        client.post(
            "/searches",
            data={
                "label": "Morning",
                "venue_names": ["Alain Mimoun", "Bercy"],
                "weekday": "sunday",
                "hour_start": "8",
                "hour_end": "10",
                "in_out_codes": ["V", "E"],
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        client.post(
            f"/searches/{search.id}/state",
            data={"is_active": 0},
            follow_redirects=False,
        )
    assert store.get_saved_search(user_id=1, search_id=search.id).is_active is False


def test_book_saved_search_route_writes_booking_history(tmp_path: Path) -> None:
    """Booking through a saved search should append one local history row."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        client.post(
            "/searches",
            data={
                "label": "Evening",
                "venue_names": ["Alain Mimoun"],
                "weekday": "sunday",
                "hour_start": "18",
                "hour_end": "20",
                "in_out_codes": ["V"],
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert len(store.list_booking_history(user_id=1)) == 1


def test_create_saved_search_persists_new_form_contract_values(tmp_path: Path) -> None:
    """Saved-search rows should preserve multi-select venues, weekday, and checkbox filters."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        client.post(
            "/searches",
            data={
                "label": "Contract",
                "venue_names": ["Alain Mimoun", "Bercy"],
                "weekday": "sunday",
                "hour_start": "8",
                "hour_end": "10",
                "in_out_codes": ["V", "E"],
            },
            follow_redirects=False,
        )
    search = store.list_saved_searches(user_id=1)[0]
    assert (
        search.venue_names,
        search.weekday,
        search.court_ids,
        search.in_out_codes,
    ) == (("Alain Mimoun", "Bercy"), "sunday", tuple(), ("V", "E"))


def test_searches_page_uses_state_route_not_legacy_toggle_route(tmp_path: Path) -> None:
    """Saved-search cards should submit state updates to /state, not /toggle."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        search = store.create_saved_search(
            user_id=1,
            label="State route",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=10,
            in_out_codes=("V",),
        )
        response = client.get("/searches")
    assert (
        f"/searches/{search.id}/state" in response.text
        and f"/searches/{search.id}/toggle" not in response.text
    )


def test_book_saved_search_tries_multi_venue_fallback_with_catalog_surface_parity(
    tmp_path: Path,
) -> None:
    """Booking must try multiple venues and broaden empty surfaces to catalog-all, like CLI."""

    client, store, state = _build_bundle(
        tmp_path,
        client_class=FakeSecondVenueOnlyParisClient,
    )
    with client:
        _login(client)
        client.post(
            "/searches",
            data={
                "label": "Fallback",
                "venue_names": ["Alain Mimoun", "Bercy"],
                "weekday": "sunday",
                "hour_start": "8",
                "hour_end": "10",
                "in_out_codes": ["V"],
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        client.post(f"/searches/{search.id}/book", follow_redirects=False)
    # FakeParisClient.get_search_catalog exposes empty surface_options, so the
    # expanded "all surfaces" value is still `()` here — what matters is that
    # the second venue gets retried (CLI-style multi-venue fallback).
    assert (
        state.search_calls,
        state.search_requests[1].venue_name,
    ) == (2, "Bercy")


def test_book_saved_search_expands_empty_surface_selection_to_catalog_all(
    tmp_path: Path,
) -> None:
    """Empty surface selection must broaden to catalog-all so the site returns matches."""

    client, store, state = _build_bundle(tmp_path, client_class=_CatalogSurfacesClient)
    with client:
        _login(client)
        client.post(
            "/searches",
            data={
                "label": "Parity",
                "venue_names": ["Alain Mimoun"],
                "weekday": "sunday",
                "hour_start": "8",
                "hour_end": "10",
                "in_out_codes": ["V"],
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert state.search_requests[0].surface_ids == ("beton", "resine")


def test_book_saved_search_route_ignores_legacy_slot_index(
    tmp_path: Path,
) -> None:
    """Booking route should ignore legacy slot_index values now that the UI removed that input."""

    client, store, state = _build_bundle(tmp_path)
    with client:
        _login(client)
        search = store.create_saved_search(
            user_id=1,
            label="Legacy slot index",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=10,
            in_out_codes=("V",),
            slot_index=999,
        )
        client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert (state.book_calls, len(store.list_booking_history(user_id=1))) == (1, 1)


def test_history_page_renders_placeholder_and_defers_fetch(tmp_path: Path) -> None:
    """History page should paint a placeholder and point JS at /history/pending."""

    client, _store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        response = client.get("/history")
    assert (
        "/history/pending" in response.text
        and "Loading live reservation status" in response.text
    )


def test_history_pending_fragment_returns_live_reservation_status(tmp_path: Path) -> None:
    """The deferred fragment endpoint should render the live reservation summary."""

    client, _store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        response = client.get("/history/pending")
    assert "Reservation active" in response.text


def test_admin_add_user_route_expands_allow_list(tmp_path: Path) -> None:
    """Admin allow-list form should create a second user account."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        client.post(
            "/admin/users",
            data={
                "display_name": "Operator",
                "paris_username": "operator@example.com",
                "paris_password": "secret",
                "is_admin": "true",
            },
            follow_redirects=False,
        )
    assert store.count_users() == 2
