"""Route-level tests for webapp branches not covered by the base flow suite."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from paris_tennis_api.exceptions import BookingError
from paris_tennis_api.models import ReservationSummary, SearchResult, SlotOffer
from paris_tennis_api.webapp.main import create_app
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import WebAppStore


class _HappyClient:
    """Local fake client that returns deterministic search/booking responses."""

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
    """Fake client variant that fails login to cover history error rendering path."""

    def login(self) -> None:
        raise BookingError("history failed")


class _NoSlotsClient(_HappyClient):
    """Fake client variant that returns no slots to cover booking error branch."""

    def search_slots(self, _request) -> SearchResult:
        return SearchResult(slots=(), captcha_request_id="captcha-request")


class _NoCaptchaClient(_HappyClient):
    """Fake client variant that omits captcha request id for booking branch coverage."""

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
    """Fake client variant that reports no active reservation after booking."""

    def get_current_reservation(self) -> ReservationSummary:
        return ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="none",
        )


def _build_bundle(
    tmp_path: Path,
    *,
    captcha_api_key: str = "captcha-key",
    client_factory=_HappyClient,
) -> tuple[TestClient, WebAppStore]:
    """Build isolated app+store pair for route tests with deterministic dependencies."""

    settings = WebAppSettings(
        database_path=tmp_path / "webapp.sqlite3",
        session_secret="test-secret",
        captcha_api_key=captcha_api_key,
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
    app = create_app(settings=settings, store=store, client_factory=client_factory)
    return TestClient(app), store


def _login_admin(client: TestClient) -> None:
    """Centralize admin login so tests can focus on route-specific behavior."""

    client.post(
        "/login",
        data={"paris_username": "admin@example.com", "paris_password": "secret"},
        follow_redirects=False,
    )


def test_root_redirects_to_login_when_session_is_missing(tmp_path: Path) -> None:
    """Anonymous root access should route to login page."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_root_redirects_to_searches_when_logged_in(tmp_path: Path) -> None:
    """Authenticated root access should go directly to saved searches dashboard."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.get("/", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_login_page_redirects_for_authenticated_user(tmp_path: Path) -> None:
    """Logged-in users should not see login form again."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.get("/login", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_login_page_renders_for_anonymous_user(tmp_path: Path) -> None:
    """Anonymous users should receive the login page HTML."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/login")
    assert response.status_code == 200


def test_bootstrap_admin_rejects_when_users_already_exist(tmp_path: Path) -> None:
    """Bootstrap endpoint should be one-time only once any user exists."""

    client, _store = _build_bundle(tmp_path)
    response = client.post(
        "/bootstrap-admin",
        data={
            "display_name": "Owner",
            "paris_username": "owner@example.com",
            "paris_password": "secret",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/login"


def test_bootstrap_admin_requires_non_empty_fields(tmp_path: Path) -> None:
    """Bootstrap should reject empty values to prevent unusable first-admin records."""

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
    app = create_app(settings=settings, store=store, client_factory=_HappyClient)
    client = TestClient(app)
    response = client.post(
        "/bootstrap-admin",
        data={"display_name": " ", "paris_username": "owner@example.com", "paris_password": "secret"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/login"


def test_bootstrap_admin_success_redirects_to_searches(tmp_path: Path) -> None:
    """Bootstrap should create the first admin and continue to the dashboard."""

    settings = WebAppSettings(
        database_path=tmp_path / "bootstrap-success.sqlite3",
        session_secret="test-secret",
        captcha_api_key="captcha-key",
        headless=True,
        host="127.0.0.1",
        port=8000,
    )
    store = WebAppStore(settings.database_path)
    store.initialize()
    app = create_app(settings=settings, store=store, client_factory=_HappyClient)
    client = TestClient(app)
    response = client.post(
        "/bootstrap-admin",
        data={
            "display_name": "Owner",
            "paris_username": "owner@example.com",
            "paris_password": "secret",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/searches"


def test_login_rejects_invalid_credentials(tmp_path: Path) -> None:
    """Unknown credentials should redirect back to login with error flash."""

    client, _store = _build_bundle(tmp_path)
    response = client.post(
        "/login",
        data={"paris_username": "bad@example.com", "paris_password": "bad"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/login"


def test_logout_clears_session_and_redirects(tmp_path: Path) -> None:
    """Logout should clear session cookie state and return to login route."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/logout", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_searches_route_redirects_when_anonymous(tmp_path: Path) -> None:
    """Search dashboard requires authentication and should reject anonymous access."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/searches", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_searches_route_renders_for_authenticated_user(tmp_path: Path) -> None:
    """Authenticated users should receive the saved-searches dashboard page."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.get("/searches")
    assert response.status_code == 200


def test_create_saved_search_redirects_when_anonymous(tmp_path: Path) -> None:
    """Creating saved searches should require logged-in user context."""

    client, _store = _build_bundle(tmp_path)
    response = client.post(
        "/searches",
        data={
            "label": "Morning",
            "venue_name": "Alain Mimoun",
            "date_iso": "12/04/2026",
            "hour_start": 8,
            "hour_end": 9,
            "surface_ids": "1324",
            "in_out_codes": "V",
            "slot_index": 1,
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/login"


def test_create_saved_search_rejects_invalid_hour_range(tmp_path: Path) -> None:
    """Hour start >= hour end should be rejected to avoid invalid search requests."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/searches",
            data={
                "label": "Invalid",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 10,
                "hour_end": 10,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/searches"


def test_create_saved_search_rejects_invalid_slot_index(tmp_path: Path) -> None:
    """slot_index must be >=1 so booking picks a valid 1-based search result index."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/searches",
            data={
                "label": "Invalid",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 0,
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/searches"


def test_create_saved_search_rejects_invalid_date_format(tmp_path: Path) -> None:
    """Date parser should reject non-DD/MM/YYYY values for predictable API inputs."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/searches",
            data={
                "label": "Invalid",
                "venue_name": "Alain Mimoun",
                "date_iso": "2026-04-12",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/searches"


def test_toggle_saved_search_reports_missing_entry(tmp_path: Path) -> None:
    """Toggling unknown search ids should redirect with missing-search error path."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/searches/999/toggle", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_toggle_saved_search_success_redirects_to_searches(tmp_path: Path) -> None:
    """Toggling an existing saved search should return to the dashboard."""

    client, store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        search = store.create_saved_search(
            user_id=1,
            label="Morning",
            venue_name="Alain Mimoun",
            date_iso="12/04/2026",
            hour_start=8,
            hour_end=9,
            surface_ids=("1324",),
            in_out_codes=("V",),
            slot_index=1,
        )
        response = client.post(f"/searches/{search.id}/toggle", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_delete_saved_search_redirects_when_anonymous(tmp_path: Path) -> None:
    """Delete endpoint should require session ownership before modifying data."""

    client, _store = _build_bundle(tmp_path)
    response = client.post("/searches/1/delete", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_book_saved_search_reports_missing_entry(tmp_path: Path) -> None:
    """Booking endpoint should handle unknown saved search ids gracefully."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/searches/999/book", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_book_saved_search_handles_missing_captcha_key(tmp_path: Path) -> None:
    """Booking should fail early when webapp captcha config is absent."""

    client, store = _build_bundle(tmp_path, captcha_api_key="")
    with client:
        _login_admin(client)
        client.post(
            "/searches",
            data={
                "label": "Book",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        response = client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_book_saved_search_rejects_non_positive_index_from_store(tmp_path: Path) -> None:
    """Defensive branch should reject corrupted saved-search rows with invalid slot index."""

    client, store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        search = store.create_saved_search(
            user_id=1,
            label="Corrupt",
            venue_name="Alain Mimoun",
            date_iso="12/04/2026",
            hour_start=8,
            hour_end=9,
            surface_ids=("1324",),
            in_out_codes=("V",),
            slot_index=0,
        )
        response = client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_history_page_renders_error_message_when_client_fails(tmp_path: Path) -> None:
    """History route should render error state when live reservation fetch fails."""

    client, _store = _build_bundle(tmp_path, client_factory=_FailingHistoryClient)
    with client:
        _login_admin(client)
        response = client.get("/history")
    assert "history failed" in response.text


def test_history_page_renders_live_pending_reservation_on_success(tmp_path: Path) -> None:
    """History should display the live pending reservation summary when fetch works."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.get("/history")
    assert "Reservation active" in response.text


def test_history_route_redirects_when_anonymous(tmp_path: Path) -> None:
    """History endpoint should require login and redirect anonymous users."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/history", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_admin_users_route_rejects_non_admin_users(tmp_path: Path) -> None:
    """Admin pages should reject authenticated users without admin role."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="User",
        paris_username="user@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        client.post(
            "/login",
            data={"paris_username": "user@example.com", "paris_password": "secret"},
            follow_redirects=False,
        )
        response = client.get("/admin/users", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_admin_users_route_redirects_when_anonymous(tmp_path: Path) -> None:
    """Anonymous access to admin users page should redirect to login."""

    client, _store = _build_bundle(tmp_path)
    response = client.get("/admin/users", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_admin_users_route_renders_for_admin(tmp_path: Path) -> None:
    """Admin users page should render successfully for authenticated admins."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.get("/admin/users")
    assert response.status_code == 200


def test_admin_create_user_requires_non_empty_fields(tmp_path: Path) -> None:
    """Admin creation route should reject empty required fields."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/admin/users",
            data={
                "display_name": " ",
                "paris_username": "new@example.com",
                "paris_password": "secret",
                "is_admin": "true",
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/admin/users"


def test_admin_create_user_redirects_when_anonymous(tmp_path: Path) -> None:
    """Anonymous admin-create calls should redirect to login."""

    client, _store = _build_bundle(tmp_path)
    response = client.post(
        "/admin/users",
        data={
            "display_name": "Anon",
            "paris_username": "anon@example.com",
            "paris_password": "secret",
            "is_admin": "false",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/login"


def test_admin_create_user_rejects_non_admin_user(tmp_path: Path) -> None:
    """Non-admin users should be blocked from creating new allow-listed accounts."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="User",
        paris_username="user4@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        client.post(
            "/login",
            data={"paris_username": "user4@example.com", "paris_password": "secret"},
            follow_redirects=False,
        )
        response = client.post(
            "/admin/users",
            data={
                "display_name": "Blocked",
                "paris_username": "blocked@example.com",
                "paris_password": "secret",
                "is_admin": "false",
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/searches"


def test_admin_create_user_rejects_duplicate_username(tmp_path: Path) -> None:
    """Duplicate usernames should follow sqlite integrity error handling branch."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/admin/users",
            data={
                "display_name": "Dup",
                "paris_username": "admin@example.com",
                "paris_password": "secret",
                "is_admin": "true",
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/admin/users"


def test_admin_create_user_success_redirects_to_admin_users(tmp_path: Path) -> None:
    """Admin user creation should follow the success redirect branch."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post(
            "/admin/users",
            data={
                "display_name": "Operator",
                "paris_username": "operator@example.com",
                "paris_password": "secret",
                "is_admin": "false",
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/admin/users"


def test_admin_toggle_admin_handles_missing_target(tmp_path: Path) -> None:
    """Toggle-admin endpoint should reject unknown target users cleanly."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/admin/users/999/toggle-admin", follow_redirects=False)
    assert response.headers["location"] == "/admin/users"


def test_admin_toggle_admin_redirects_when_anonymous(tmp_path: Path) -> None:
    """Anonymous toggle-admin calls should redirect to login."""

    client, _store = _build_bundle(tmp_path)
    response = client.post("/admin/users/1/toggle-admin", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_admin_toggle_admin_rejects_non_admin_user(tmp_path: Path) -> None:
    """Non-admin users should be blocked from toggle-admin operations."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="User",
        paris_username="user2@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        client.post(
            "/login",
            data={"paris_username": "user2@example.com", "paris_password": "secret"},
            follow_redirects=False,
        )
        response = client.post("/admin/users/1/toggle-admin", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_admin_toggle_admin_blocks_last_admin_self_demotion(tmp_path: Path) -> None:
    """Last admin should not be able to remove its own admin role."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/admin/users/1/toggle-admin", follow_redirects=False)
    assert response.headers["location"] == "/admin/users"


def test_admin_toggle_admin_updates_target_role_on_success(tmp_path: Path) -> None:
    """Admin toggle should update target role when safeguards do not block action."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="Second Admin",
        paris_username="second-admin@example.com",
        paris_password="secret",
        is_admin=True,
    )
    with client:
        _login_admin(client)
        response = client.post("/admin/users/2/toggle-admin", follow_redirects=False)
    assert response.headers["location"] == "/admin/users"


def test_admin_toggle_enabled_handles_missing_target(tmp_path: Path) -> None:
    """Toggle-enabled endpoint should handle unknown user ids without crashing."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/admin/users/999/toggle-enabled", follow_redirects=False)
    assert response.headers["location"] == "/admin/users"


def test_admin_toggle_enabled_redirects_when_anonymous(tmp_path: Path) -> None:
    """Anonymous toggle-enabled calls should redirect to login."""

    client, _store = _build_bundle(tmp_path)
    response = client.post("/admin/users/1/toggle-enabled", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_admin_toggle_enabled_rejects_non_admin_user(tmp_path: Path) -> None:
    """Non-admin users should not be able to toggle enabled status."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="User",
        paris_username="user3@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        client.post(
            "/login",
            data={"paris_username": "user3@example.com", "paris_password": "secret"},
            follow_redirects=False,
        )
        response = client.post("/admin/users/1/toggle-enabled", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_admin_toggle_enabled_blocks_last_active_admin_disable(tmp_path: Path) -> None:
    """Last active admin cannot be disabled to prevent administrative lockout."""

    client, _store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        response = client.post("/admin/users/1/toggle-enabled", follow_redirects=False)
    assert response.headers["location"] == "/admin/users"


def test_admin_toggle_enabled_updates_target_status_on_success(tmp_path: Path) -> None:
    """Admin toggle-enabled should update other users when safeguards allow it."""

    client, store = _build_bundle(tmp_path)
    store.create_user(
        display_name="Operator",
        paris_username="operator2@example.com",
        paris_password="secret",
        is_admin=False,
    )
    with client:
        _login_admin(client)
        response = client.post("/admin/users/2/toggle-enabled", follow_redirects=False)
    assert response.headers["location"] == "/admin/users"


def test_delete_saved_search_success_path_redirects_to_searches(tmp_path: Path) -> None:
    """Delete endpoint should remove owned searches and redirect back to dashboard."""

    client, store = _build_bundle(tmp_path)
    with client:
        _login_admin(client)
        client.post(
            "/searches",
            data={
                "label": "Delete me",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        response = client.post(f"/searches/{search.id}/delete", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_toggle_saved_search_redirects_when_anonymous(tmp_path: Path) -> None:
    """Anonymous toggle requests should redirect instead of mutating state."""

    client, _store = _build_bundle(tmp_path)
    response = client.post("/searches/1/toggle", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_book_saved_search_redirects_when_anonymous(tmp_path: Path) -> None:
    """Anonymous book requests should redirect to login route."""

    client, _store = _build_bundle(tmp_path)
    response = client.post("/searches/1/book", follow_redirects=False)
    assert response.headers["location"] == "/login"


def test_book_saved_search_handles_no_slot_result(tmp_path: Path) -> None:
    """Booking should fail with no-slot client responses instead of writing history."""

    client, store = _build_bundle(tmp_path, client_factory=_NoSlotsClient)
    with client:
        _login_admin(client)
        client.post(
            "/searches",
            data={
                "label": "Book",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        response = client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_book_saved_search_handles_missing_captcha_request_id(tmp_path: Path) -> None:
    """Booking should fail when search result is not bookable due missing captcha id."""

    client, store = _build_bundle(tmp_path, client_factory=_NoCaptchaClient)
    with client:
        _login_admin(client)
        client.post(
            "/searches",
            data={
                "label": "Book",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        response = client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_book_saved_search_handles_inactive_reservation_after_booking(tmp_path: Path) -> None:
    """Booking should fail if post-booking reservation check is inactive."""

    client, store = _build_bundle(tmp_path, client_factory=_InactiveReservationClient)
    with client:
        _login_admin(client)
        client.post(
            "/searches",
            data={
                "label": "Book",
                "venue_name": "Alain Mimoun",
                "date_iso": "12/04/2026",
                "hour_start": 8,
                "hour_end": 9,
                "surface_ids": "1324",
                "in_out_codes": "V",
                "slot_index": 1,
            },
            follow_redirects=False,
        )
        search = store.list_saved_searches(user_id=1)[0]
        response = client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert response.headers["location"] == "/searches"


def test_book_saved_search_success_redirects_to_history(tmp_path: Path) -> None:
    """Successful booking should redirect to history page."""

    client, store = _build_bundle(tmp_path, client_factory=_HappyClient)
    with client:
        _login_admin(client)
        search = store.create_saved_search(
            user_id=1,
            label="Book",
            venue_name="Alain Mimoun",
            date_iso="12/04/2026",
            hour_start=8,
            hour_end=9,
            surface_ids=("1324",),
            in_out_codes=("V",),
            slot_index=1,
        )
        response = client.post(f"/searches/{search.id}/book", follow_redirects=False)
    assert response.headers["location"] == "/history"
