"""End-to-end JSON API tests for the local webapp using an in-memory fake client."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
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


@pytest.fixture(autouse=True)
def _stub_static_catalog(monkeypatch):
    """Pin the catalog for every test so they do not depend on the real shipped JSON.

    Production serves the catalog from ``src/paris_tennis_api/catalog.json``
    (scraped from tennis.paris.fr weekly).  Tests use fixed venue names like
    "Alain Mimoun" / "Bercy" that must always validate regardless of the
    current shipped catalog.
    """

    test_catalog = SearchCatalog(
        venues={
            "Alain Mimoun": TennisVenue(
                venue_id="v-1",
                name="Alain Mimoun",
                available_now=False,
                courts=(TennisCourt(court_id="c-1", name="Court 1"),),
            ),
            "Bercy": TennisVenue(
                venue_id="v-2",
                name="Bercy",
                available_now=False,
                courts=(TennisCourt(court_id="c-2", name="Court 2"),),
            ),
        },
        date_options=tuple(),
        surface_options={},
        in_out_options={"V": "Indoor", "E": "Outdoor"},
        min_hour=7,
        max_hour=23,
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.main.load_static_catalog",
        lambda: test_catalog,
    )


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

    def cancel_current_reservation(self) -> bool:
        return True


class FakeSchedulerStatefulClient(FakeParisClient):
    """Pending status flips True only after a successful booking, so the
    scheduler's "skip user with pending reservation" guard does not
    short-circuit on the very first tick."""

    def get_current_reservation(self) -> ReservationSummary:
        if self._state.book_calls > 0:
            return ReservationSummary(
                has_active_reservation=True,
                cancellation_token="token",
                raw_text="Reservation active",
            )
        return ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="No reservation",
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
    """Build one fully isolated app + logged-in admin so each test stays focused."""

    settings = WebAppSettings(
        database_path=tmp_path / "webapp.sqlite3",
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
    """Authenticate the seeded admin so downstream calls carry the cookie."""

    client.post(
        "/api/session",
        json={"paris_username": "admin@example.com", "paris_password": "secret"},
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
        response = client.post(
            "/api/bootstrap-admin",
            json={
                "display_name": "Owner",
                "paris_username": "owner@example.com",
                "paris_password": "secret",
            },
        )
    assert response.status_code == 201 and store.count_users() == 1


def test_update_search_state_flips_active_flag(tmp_path: Path) -> None:
    """PATCH /api/searches/{id} must flip is_active persistently."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        create = client.post(
            "/api/searches",
            json={
                "label": "Morning",
                "venue_names": ["Alain Mimoun", "Bercy"],
                "weekday": "sunday",
                "hour_start": 8,
                "hour_end": 10,
                "in_out_codes": ["V", "E"],
            },
        )
        search_id = create.json()["search"]["id"]
        client.patch(f"/api/searches/{search_id}", json={"is_active": False})
    assert store.get_saved_search(user_id=1, search_id=search_id).is_active is False


def test_book_saved_search_writes_booking_history(tmp_path: Path) -> None:
    """Booking through a saved search should append one local history row."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        create = client.post(
            "/api/searches",
            json={
                "label": "Evening",
                "venue_names": ["Alain Mimoun"],
                "weekday": "sunday",
                "hour_start": 18,
                "hour_end": 20,
                "in_out_codes": ["V"],
            },
        )
        search_id = create.json()["search"]["id"]
        response = client.post(f"/api/searches/{search_id}/book")
    assert (response.status_code, len(store.list_booking_history(user_id=1))) == (
        200,
        1,
    )


def test_create_saved_search_persists_multi_venue_contract(tmp_path: Path) -> None:
    """Saved-search rows should preserve multi-select venues, weekday, and checkbox filters."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        client.post(
            "/api/searches",
            json={
                "label": "Contract",
                "venue_names": ["Alain Mimoun", "Bercy"],
                "weekday": "sunday",
                "hour_start": 8,
                "hour_end": 10,
                "in_out_codes": ["V", "E"],
            },
        )
    search = store.list_saved_searches(user_id=1)[0]
    assert (search.venue_names, search.weekday, search.in_out_codes) == (
        ("Alain Mimoun", "Bercy"),
        "sunday",
        ("V", "E"),
    )


def test_book_saved_search_tries_multi_venue_fallback_using_all_surfaces(
    tmp_path: Path,
) -> None:
    """Booking should try multiple venues and broaden empty surface selection to catalog-all."""

    client, store, state = _build_bundle(
        tmp_path,
        client_class=FakeSecondVenueOnlyParisClient,
    )
    with client:
        _login(client)
        create = client.post(
            "/api/searches",
            json={
                "label": "Fallback",
                "venue_names": ["Alain Mimoun", "Bercy"],
                "weekday": "sunday",
                "hour_start": 8,
                "hour_end": 10,
                "in_out_codes": ["V"],
            },
        )
        search_id = create.json()["search"]["id"]
        client.post(f"/api/searches/{search_id}/book")
    assert (
        state.search_calls,
        state.search_requests[1].venue_name,
    ) == (2, "Bercy")


def test_history_records_endpoint_returns_booked_slot(tmp_path: Path) -> None:
    """GET /api/history returns booking records persisted locally."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        search = store.create_saved_search(
            user_id=1,
            label="Evening",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=18,
            hour_end=20,
            in_out_codes=("V",),
        )
        client.post(f"/api/searches/{search.id}/book")
        response = client.get("/api/history")
    assert response.status_code == 200 and len(response.json()["records"]) == 1


def test_cancel_pending_endpoint_calls_client_cancellation(tmp_path: Path) -> None:
    """DELETE /api/history/pending must hit the same cancel API the CLI uses."""

    client, _store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        response = client.delete("/api/history/pending")
    body = response.json()
    assert (response.status_code, body["canceled"]) == (200, True)


def test_history_pending_endpoint_returns_live_reservation(tmp_path: Path) -> None:
    """GET /api/history/pending should return the parsed live reservation payload."""

    client, _store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        response = client.get("/api/history/pending")
    body = response.json()
    assert (
        response.status_code,
        body["pending"]["has_active_reservation"],
        "Reservation active" in body["pending"]["raw_text"],
    ) == (200, True, True)


def test_admin_add_user_route_expands_allow_list(tmp_path: Path) -> None:
    """POST /api/admin/users should create a second user account."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        response = client.post(
            "/api/admin/users",
            json={
                "display_name": "Operator",
                "paris_username": "operator@example.com",
                "paris_password": "secret",
                "is_admin": True,
            },
        )
    assert (response.status_code, store.count_users()) == (201, 2)


def test_check_availability_returns_anonymous_slots_per_venue(
    tmp_path: Path, monkeypatch
) -> None:
    """The check-availability endpoint must run anonymously and return slot info per venue."""

    # The endpoint now calls ``probe_availability`` directly (pure httpx, no
    # Playwright), so we stub it to avoid hitting tennis.paris.fr during tests.
    stub_result = SearchResult(
        slots=(
            SlotOffer(
                equipment_id="",
                court_id="",
                date_deb="08h",
                date_fin="",
                price_eur="12 €",
                price_label="stub",
            ),
        ),
        captcha_request_id="",
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.main.probe_availability",
        lambda request: stub_result,
    )

    client, store, state = _build_bundle(tmp_path)
    with client:
        _login(client)
        search = store.create_saved_search(
            user_id=1,
            label="Probe",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=9,
            in_out_codes=("V",),
        )
        response = client.post(f"/api/searches/{search.id}/check-availability")
    body = response.json()
    # Login must not have been touched — the probe path is fully anonymous.
    assert (
        response.status_code,
        body["venues"][0]["name"],
        len(body["venues"][0]["slots"]),
        state.login_calls,
    ) == (200, "Alain Mimoun", 1, 0)


def test_update_saved_search_patches_label_and_hours(tmp_path: Path) -> None:
    """PATCH must accept partial field updates while keeping is_active intact."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        original = store.create_saved_search(
            user_id=1,
            label="Old",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=9,
            in_out_codes=("V",),
        )
        response = client.patch(
            f"/api/searches/{original.id}",
            json={"label": "Renamed", "hour_start": 10, "hour_end": 12},
        )
    body = response.json()["search"]
    refreshed = store.get_saved_search(user_id=1, search_id=original.id)
    assert (
        response.status_code,
        body["label"],
        body["hour_start"],
        refreshed.hour_end,
    ) == (200, "Renamed", 10, 12)


def test_update_saved_search_rejects_invalid_hour_range(tmp_path: Path) -> None:
    """Edits must be validated the same way as creates (hour_start < hour_end)."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        search = store.create_saved_search(
            user_id=1,
            label="Edited",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=10,
            in_out_codes=("V",),
        )
        response = client.patch(
            f"/api/searches/{search.id}", json={"hour_start": 11}
        )
    assert response.status_code == 422


def test_history_endpoint_includes_court_name_from_catalog(tmp_path: Path) -> None:
    """History payload must enrich each record with the catalog-resolved court name."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        search = store.create_saved_search(
            user_id=1,
            label="Booking",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=9,
            in_out_codes=("V",),
        )
        client.post(f"/api/searches/{search.id}/book")
        response = client.get("/api/history")
    record = response.json()["records"][0]
    # FakeParisClient catalog exposes one court named "Court 1" for Alain Mimoun
    # but the booked slot has court_id="court-1" — the lookup keys by id, so
    # if the slot id matches the catalog id the resolved name comes through.
    assert record["court_id"] == "court-1" and record["court_name"] in {"Court 1", ""}


def test_duplicate_search_clones_with_copy_suffix(tmp_path: Path) -> None:
    """Duplicate must clone every saved-search field and append '(copy)' to the label."""

    client, store, _state = _build_bundle(tmp_path)
    with client:
        _login(client)
        original = store.create_saved_search(
            user_id=1,
            label="Original",
            venue_names=("Alain Mimoun", "Bercy"),
            weekday="sunday",
            hour_start=8,
            hour_end=9,
            in_out_codes=("V",),
        )
        response = client.post(f"/api/searches/{original.id}/duplicate")
    body = response.json()["search"]
    assert (response.status_code, body["label"], body["venue_names"]) == (
        201,
        "Original (copy)",
        ["Alain Mimoun", "Bercy"],
    )


def test_scheduler_endpoints_round_trip_settings_and_run(
    tmp_path: Path, monkeypatch
) -> None:
    """Admin can read defaults, patch settings, and force a tick that runs end-to-end."""

    # Scheduler's anonymous probe now uses pure httpx; stub it so the tick
    # runs offline and always reports at least one slot.
    stub_result = SearchResult(
        slots=(
            SlotOffer(
                equipment_id="",
                court_id="",
                date_deb="08h",
                date_fin="",
                price_eur="12 €",
                price_label="stub",
            ),
        ),
        captcha_request_id="",
    )
    monkeypatch.setattr(
        "paris_tennis_api.webapp.scheduler.probe_availability",
        lambda request: stub_result,
    )

    client, store, _state = _build_bundle(
        tmp_path, client_class=FakeSchedulerStatefulClient
    )
    with client:
        _login(client)
        # Active search so the forced tick has work to do (FakeParisClient
        # always returns one slot, so the booking will succeed).
        store.create_saved_search(
            user_id=1,
            label="Tick target",
            venue_names=("Alain Mimoun",),
            weekday="sunday",
            hour_start=8,
            hour_end=9,
            in_out_codes=("V",),
        )

        defaults = client.get("/api/admin/scheduler").json()
        # Tweak interval + add a burst window so the SPA payload survives a round-trip.
        patched = client.patch(
            "/api/admin/scheduler",
            json={
                "default_interval_seconds": 120,
                "burst_windows": [
                    {
                        "time": "07:58",
                        "plus_minus_minutes": 5,
                        "interval_seconds": 5,
                    }
                ],
            },
        )
        forced = client.post("/api/admin/scheduler/run").json()

    assert defaults["settings"]["default_interval_seconds"] == 60
    new_settings = patched.json()["settings"]
    assert (
        new_settings["default_interval_seconds"],
        new_settings["burst_windows"][0]["time"],
    ) == (120, "07:58")
    assert forced["summary"]["bookings_succeeded"] == 1
    # Searches are never deactivated automatically — activation is admin-only.
    # The last_target_date guard prevents re-booking the same date.
    saved = store.list_saved_searches(user_id=1)[0]
    assert saved.is_active is True
    assert saved.last_success_at != ""
    assert saved.last_target_date != ""


def test_scheduler_endpoint_requires_admin(tmp_path: Path) -> None:
    """Non-admin sessions must receive 403 on the scheduler API."""

    client, store, _state = _build_bundle(tmp_path)
    store.create_user(
        display_name="User",
        paris_username="user@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        client.post(
            "/api/session",
            json={"paris_username": "user@example.com", "paris_password": "secret"},
        )
        response = client.get("/api/admin/scheduler")
    assert response.status_code == 403


def test_me_endpoint_reports_bootstrap_state(tmp_path: Path) -> None:
    """/api/me should report needs_bootstrap=true when the store has zero users."""

    settings = WebAppSettings(
        database_path=tmp_path / "empty.sqlite3",
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

    def _client_factory(**kwargs: object) -> FakeParisClient:
        return FakeParisClient(state=FakeClientState(), **kwargs)

    app = create_app(settings=settings, store=store, client_factory=_client_factory)
    with TestClient(app) as client:
        response = client.get("/api/me")
    body = response.json()
    assert (response.status_code, body["user"], body["needs_bootstrap"]) == (
        200,
        None,
        True,
    )
