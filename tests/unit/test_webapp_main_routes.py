"""Route-level JSON API tests for the React-backed webapp."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paris_tennis_api.exceptions import BookingError
from paris_tennis_api.models import (
    ReservationSummary,
    SearchCatalog,
    SearchResult,
    SlotOffer,
    TennisCourt,
    TennisVenue,
)
from paris_tennis_api.webapp.main import create_app
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import WebAppStore


class _HappyClient:
    """Local fake client returning deterministic search/booking responses."""

    def __init__(self, **_: object) -> None:
        return None

    def __enter__(self) -> "_HappyClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def login(self) -> None:
        return None

    def search_slots(self, _request) -> SearchResult:
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
                )
            },
            date_options=("12/04/2026",),
            surface_options={},
            in_out_options={"V": "Indoor", "E": "Outdoor"},
            min_hour=7,
            max_hour=23,
        )

    def book_slot(self, *, slot: SlotOffer, captcha_request_id: str) -> None:
        _ = (slot, captcha_request_id)
        return None

    def get_current_reservation(self) -> ReservationSummary:
        return ReservationSummary(
            has_active_reservation=True,
            cancellation_token="token",
            raw_text="Reservation active",
        )


class _FailingHistoryClient(_HappyClient):
    """Fake variant whose login() fails — used to cover pending-error path."""

    def login(self) -> None:
        raise BookingError("history failed")


class _NoSlotsClient(_HappyClient):
    """Fake variant returning no slots so booking raises the domain error."""

    def search_slots(self, _request) -> SearchResult:
        return SearchResult(slots=(), captcha_request_id="captcha-request")


class _NoCaptchaClient(_HappyClient):
    """Fake variant that omits captchaRequestId so booking aborts with 400."""

    def search_slots(self, _request) -> SearchResult:
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
            captcha_request_id="",
        )


class _InactiveReservationClient(_HappyClient):
    """Fake variant whose post-booking check reports no active reservation."""

    def get_current_reservation(self) -> ReservationSummary:
        return ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="none",
        )


class _PlaywrightExplodingClient(_HappyClient):
    """Simulates a raw Playwright TypeError bubbling out of search_slots."""

    def search_slots(self, _request) -> SearchResult:
        raise TypeError("Cannot set properties of null (setting 'innerHTML')")


def _build_bundle(
    tmp_path: Path,
    *,
    captcha_api_key: str = "captcha-key",
    client_factory=_HappyClient,
) -> tuple[TestClient, WebAppStore]:
    """Build isolated app+store pair with a seeded admin for JSON route tests."""

    settings = WebAppSettings(
        database_path=tmp_path / "webapp.sqlite3",
        session_secret="test-secret",
        captcha_api_key=captcha_api_key,
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
    app = create_app(settings=settings, store=store, client_factory=client_factory)
    return TestClient(app), store


def _login_admin(client: TestClient) -> None:
    """Authenticate the seeded admin to share session cookies across calls."""

    client.post(
        "/api/session",
        json={"paris_username": "admin@example.com", "paris_password": "secret"},
    )


def _saved_search_payload(
    *,
    label: str = "Morning",
    venue_names: tuple[str, ...] = ("Alain Mimoun",),
    weekday: str = "sunday",
    hour_start: int = 8,
    hour_end: int = 9,
    in_out_codes: tuple[str, ...] = ("V",),
) -> dict[str, object]:
    """Build JSON payloads matching the API contract for saved-search creation."""

    return {
        "label": label,
        "venue_names": list(venue_names),
        "weekday": weekday,
        "hour_start": hour_start,
        "hour_end": hour_end,
        "in_out_codes": list(in_out_codes),
    }


# ------------------------------------------------------------------ infra
def test_healthz_is_public(tmp_path: Path) -> None:
    """Health checks must work without auth for infra probes."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_reports_store_counts(tmp_path: Path) -> None:
    """Health payload exposes user/admin counts for operational visibility."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/healthz")
    assert response.json() == {"status": "ok", "users": 1, "enabled_admins": 1}


# ------------------------------------------------------------------ session
def test_me_returns_null_when_anonymous(tmp_path: Path) -> None:
    """/api/me for unauthenticated callers returns user=null but still 200."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/api/me")
    assert (response.status_code, response.json()["user"]) == (200, None)


def test_login_sets_session_cookie_and_returns_user(tmp_path: Path) -> None:
    """POST /api/session must authenticate and echo the user payload."""

    client, _store = _build_bundle(tmp_path)
    with client:
        response = client.post(
            "/api/session",
            json={"paris_username": "admin@example.com", "paris_password": "secret"},
        )
    assert (response.status_code, response.json()["user"]["display_name"]) == (
        200,
        "Admin",
    )


def test_login_rejects_bad_credentials_with_401(tmp_path: Path) -> None:
    """Unknown credentials should 401 with a detail message."""

    client, _store = _build_bundle(tmp_path)
    response = client.post(
        "/api/session",
        json={"paris_username": "nobody", "paris_password": "nothing"},
    )
    assert response.status_code == 401


def test_logout_clears_session(tmp_path: Path) -> None:
    """DELETE /api/session must return 200 and drop the cookie."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.delete("/api/session")
    assert response.status_code == 200


def test_bootstrap_admin_requires_non_empty_fields(tmp_path: Path) -> None:
    """Bootstrap must reject blank values to prevent unusable admin records."""

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
    app = create_app(settings=settings, store=store, client_factory=_HappyClient)
    client = TestClient(app)
    response = client.post(
        "/api/bootstrap-admin",
        json={
            "display_name": " ",
            "paris_username": "owner@example.com",
            "paris_password": "secret",
        },
    )
    assert response.status_code == 422


def test_bootstrap_admin_blocks_when_users_already_exist(tmp_path: Path) -> None:
    """Bootstrap is only valid on an empty store; 409 once a user exists."""

    client, _store = _build_bundle(tmp_path)
    response = client.post(
        "/api/bootstrap-admin",
        json={
            "display_name": "Owner",
            "paris_username": "owner@example.com",
            "paris_password": "secret",
        },
    )
    assert response.status_code == 409


# ------------------------------------------------------------------ searches
def test_searches_endpoint_requires_authentication(tmp_path: Path) -> None:
    """Anonymous callers get 401 instead of an HTML redirect."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/api/searches")
    assert response.status_code == 401


def test_create_search_rejects_invalid_hour_range(tmp_path: Path) -> None:
    """hour_start >= hour_end must return 422 with a clear message."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/api/searches",
            json=_saved_search_payload(label="Invalid", hour_start=10, hour_end=10),
        )
    assert response.status_code == 422


def test_create_search_rejects_invalid_weekday(tmp_path: Path) -> None:
    """Weekday input must be constrained to Monday-Sunday."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/api/searches",
            json=_saved_search_payload(label="Invalid", weekday="funday"),
        )
    assert response.status_code == 422


def test_update_search_returns_404_for_unknown_id(tmp_path: Path) -> None:
    """Unknown saved-search ids must 404 instead of silently succeeding."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.patch("/api/searches/999", json={"is_active": True})
    assert response.status_code == 404


def test_book_saved_search_returns_400_when_no_slots(tmp_path: Path) -> None:
    """No-slot responses should surface as 400 with the domain error message."""

    client, store = _build_bundle(tmp_path, client_factory=_NoSlotsClient)
    with client:
        _login_admin(client)
        created = client.post("/api/searches", json=_saved_search_payload())
        search_id = created.json()["search"]["id"]
        response = client.post(f"/api/searches/{search_id}/book")
    assert (response.status_code, len(store.list_booking_history(user_id=1))) == (
        400,
        0,
    )


def test_book_saved_search_returns_400_when_captcha_missing(tmp_path: Path) -> None:
    """Missing captcha_request_id is a domain error, surfaced as 400."""

    client, _store = _build_bundle(tmp_path, client_factory=_NoCaptchaClient)
    with client:
        _login_admin(client)
        created = client.post("/api/searches", json=_saved_search_payload())
        search_id = created.json()["search"]["id"]
        response = client.post(f"/api/searches/{search_id}/book")
    assert response.status_code == 400


def test_book_saved_search_returns_400_when_reservation_not_active(
    tmp_path: Path,
) -> None:
    """Post-booking inactive reservation must raise, not silently succeed."""

    client, _store = _build_bundle(tmp_path, client_factory=_InactiveReservationClient)
    with client:
        _login_admin(client)
        created = client.post("/api/searches", json=_saved_search_payload())
        search_id = created.json()["search"]["id"]
        response = client.post(f"/api/searches/{search_id}/book")
    assert response.status_code == 400


def test_book_saved_search_returns_500_for_unexpected_exceptions(
    tmp_path: Path,
) -> None:
    """Raw Playwright errors must bubble up as 500 with logged context."""

    client, _store = _build_bundle(tmp_path, client_factory=_PlaywrightExplodingClient)
    with client:
        _login_admin(client)
        created = client.post("/api/searches", json=_saved_search_payload())
        search_id = created.json()["search"]["id"]
        response = client.post(f"/api/searches/{search_id}/book")
    assert response.status_code == 500


def test_book_saved_search_returns_400_when_captcha_key_missing(tmp_path: Path) -> None:
    """Missing captcha config should fail before the browser session spins up."""

    client, _store = _build_bundle(tmp_path, captcha_api_key="")
    with client:
        _login_admin(client)
        created = client.post("/api/searches", json=_saved_search_payload())
        search_id = created.json()["search"]["id"]
        response = client.post(f"/api/searches/{search_id}/book")
    assert response.status_code == 400


# ------------------------------------------------------------------ history
def test_history_pending_reports_client_errors_without_500(tmp_path: Path) -> None:
    """A failing pending fetch should return JSON with error, not HTTP 500."""

    client, _store = _build_bundle(tmp_path, client_factory=_FailingHistoryClient)
    with client:
        _login_admin(client)
        response = client.get("/api/history/pending")
    body = response.json()
    assert (response.status_code, body["pending"], "history failed" in body["error"]) == (
        200,
        None,
        True,
    )


# ------------------------------------------------------------------ admin
def test_admin_users_rejects_non_admin_users(tmp_path: Path) -> None:
    """Non-admin sessions must receive 403 on admin endpoints."""

    client, store = _build_bundle(tmp_path)
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
        response = client.get("/api/admin/users")
    assert response.status_code == 403


def test_admin_create_user_rejects_duplicate_username(tmp_path: Path) -> None:
    """Duplicate usernames must 409 rather than 500 on IntegrityError."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/api/admin/users",
            json={
                "display_name": "Dup",
                "paris_username": "admin@example.com",
                "paris_password": "secret",
                "is_admin": True,
            },
        )
    assert response.status_code == 409


def test_admin_update_user_blocks_last_admin_demotion(tmp_path: Path) -> None:
    """Removing admin from the only admin must 409 to prevent lockout."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.patch("/api/admin/users/1", json={"is_admin": False})
    assert response.status_code == 409


def test_admin_update_user_toggles_enabled_flag(tmp_path: Path) -> None:
    """PATCH with is_enabled must flip the flag when safeguards allow it."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="Operator",
        paris_username="operator@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        _login_admin(client)
        response = client.patch("/api/admin/users/2", json={"is_enabled": False})
    assert (response.status_code, response.json()["user"]["is_enabled"]) == (200, False)


# ---------------------------------------------------- keep unused import happy
_ = pytest
