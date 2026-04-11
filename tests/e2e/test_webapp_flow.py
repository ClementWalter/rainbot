"""End-to-end tests for the local webapp routes using an in-memory fake client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from paris_tennis_api.models import ReservationSummary, SearchResult, SlotOffer
from paris_tennis_api.webapp.main import create_app
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import WebAppStore


@dataclass
class FakeClientState:
    """Track interactions with the fake client across requests."""

    login_calls: int = 0
    search_calls: int = 0
    book_calls: int = 0


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

    def search_slots(self, _request) -> SearchResult:
        self._state.search_calls += 1
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

    def book_slot(self, *, slot: SlotOffer, captcha_request_id: str) -> None:
        _ = (slot, captcha_request_id)
        self._state.book_calls += 1

    def get_current_reservation(self) -> ReservationSummary:
        return ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="Reservation active",
        )


def _build_bundle(tmp_path: Path) -> tuple[TestClient, WebAppStore, FakeClientState]:
    """Build one fully isolated app instance with seeded admin account."""

    settings = WebAppSettings(
        database_path=tmp_path / "webapp.sqlite3",
        session_secret="test-secret",
        captcha_api_key="captcha-key",
        headless=True,
        host="127.0.0.1",
        port=8000,
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
        return FakeParisClient(state=state, **kwargs)

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


def test_toggle_saved_search_route_updates_search_state(tmp_path: Path) -> None:
    """The toggle endpoint should flip a saved search between active and inactive."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        client.post(
            "/searches",
            data={
                "label": "Morning",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 10,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        client.post(f"/searches/{search.id}/toggle", follow_redirects=False)
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
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 18,
                "hour_end": 20,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert len(store.list_booking_history(user_id=1)) == 1


def test_history_page_displays_live_pending_reservation_status(tmp_path: Path) -> None:
    """History page should render the live pending reservation summary text."""

    client, _store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        response = client.get("/history")
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
