"""FastAPI JSON API backing the React webapp for Paris Tennis bookings.

All UI lives under ``web/`` (built with Vite) and hits ``/api/*`` here.  This
module keeps the persistent per-user browser session, catalog TTL cache and
SQLite store set up by previous iterations; only the HTTP surface changed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.exceptions import BookingError, ParisTennisError, ValidationError
from paris_tennis_api.models import SearchCatalog, SearchRequest
from paris_tennis_api.webapp.scheduler import SchedulerService
from paris_tennis_api.webapp.sessions import UserSessionManager
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import AllowedUser, SavedSearch, WebAppStore

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
# Vite build output.  Resolved relative to the repo root so the webapp works
# regardless of the CWD the process was launched from.
WEB_DIST_DIR = BASE_DIR.parent.parent.parent / "web" / "dist"
WEEKDAY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
    ("saturday", "Saturday"),
    ("sunday", "Sunday"),
)
_WEEKDAY_LABELS = {value: label for value, label in WEEKDAY_OPTIONS}


# ---------------------------------------------------------------------------
# Pydantic request bodies — FastAPI validates shape + types before our code.
# ---------------------------------------------------------------------------


class LoginBody(BaseModel):
    paris_username: str
    paris_password: str


class BootstrapAdminBody(BaseModel):
    display_name: str
    paris_username: str
    paris_password: str


class CreateSearchBody(BaseModel):
    label: str
    venue_names: list[str] = Field(default_factory=list)
    weekday: str
    hour_start: int
    hour_end: int
    in_out_codes: list[str] = Field(default_factory=list)


class UpdateSearchBody(BaseModel):
    """All fields optional — partial PATCHes are how the SPA toggles or edits."""

    is_active: bool | None = None
    label: str | None = None
    venue_names: list[str] | None = None
    weekday: str | None = None
    hour_start: int | None = None
    hour_end: int | None = None
    in_out_codes: list[str] | None = None


class CreateUserBody(BaseModel):
    display_name: str
    paris_username: str
    paris_password: str
    is_admin: bool = False


class UpdateUserBody(BaseModel):
    display_name: str | None = None
    paris_username: str | None = None
    paris_password: str | None = None
    is_admin: bool | None = None
    is_enabled: bool | None = None


class UpdateMeBody(BaseModel):
    """Self-edit body — users can change their own profile but not roles."""

    display_name: str | None = None
    paris_username: str | None = None
    paris_password: str | None = None


class BurstWindowBody(BaseModel):
    """One burst window: poll faster around a precise time of day."""

    time: str
    plus_minus_minutes: int = 5
    interval_seconds: int = 30


class UpdateSchedulerBody(BaseModel):
    """Scheduler config body — every field optional for partial PATCHes."""

    enabled: bool | None = None
    default_interval_seconds: int | None = None
    tick_noise_seconds: int | None = None
    burst_windows: list[BurstWindowBody] | None = None


class UpdateSettingsBody(BaseModel):
    """Key/value pairs to upsert into the app_settings table."""

    captcha_api_key: str | None = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    settings: WebAppSettings | None = None,
    store: WebAppStore | None = None,
    client_factory: type[ParisTennisClient] = ParisTennisClient,
) -> FastAPI:
    """Build an app instance with injectable storage and client dependencies for tests."""

    app_settings = settings or WebAppSettings.from_env()
    app_store = store or WebAppStore(app_settings.database_path)
    app_store.initialize()

    # DB-stored captcha key takes precedence over env var so admins can
    # update it at runtime without restarting the container.
    captcha_api_key = (
        app_store.get_app_setting("captcha_api_key")
        or app_settings.captcha_api_key
    )

    session_manager = UserSessionManager(
        client_factory=client_factory,
        captcha_api_key=captcha_api_key,
        headless=app_settings.headless,
        catalog_ttl_seconds=app_settings.catalog_ttl_seconds,
    )
    scheduler = SchedulerService(
        store=app_store,
        session_manager=session_manager,
        timezone_name=app_settings.timezone,
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Lifespan hook: warm catalogs, start scheduler, tear them down on exit."""

        if app_settings.warm_on_startup:
            _warm_catalogs_in_background(store=app_store, manager=session_manager)
        # Scheduler thread is always started; whether it actually books is
        # gated on the admin-controlled `scheduler.enabled` setting so the
        # operator can flip it without restarting the process.
        scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()
            session_manager.shutdown()

    app = FastAPI(title="Rainbot", version="0.2.0", lifespan=_lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=app_settings.session_secret,
        same_site="lax",
        https_only=False,
    )
    app.state.settings = app_settings
    app.state.store = app_store
    app.state.client_factory = client_factory
    app.state.session_manager = session_manager
    app.state.scheduler = scheduler

    # ----------------------------------------------------------- infra
    @app.get("/healthz")
    def healthz(request: Request) -> dict[str, object]:
        """Unauthenticated probe for deployment health checks."""

        store = _store(request)
        return {
            "status": "ok",
            "users": store.count_users(),
            "enabled_admins": store.count_admin_users(),
        }

    # ----------------------------------------------------------- session
    @app.get("/api/me")
    def api_me(request: Request) -> JSONResponse:
        """Return the authenticated user or a bootstrap hint for the SPA."""

        user = _get_current_user(request)
        if user is None:
            return JSONResponse(
                {
                    "user": None,
                    "needs_bootstrap": _store(request).count_users() == 0,
                }
            )
        return JSONResponse({"user": _user_payload(user), "needs_bootstrap": False})

    @app.post("/api/session")
    def api_login(request: Request, body: LoginBody) -> JSONResponse:
        """Authenticate against the local allow-list and set the session cookie."""

        user = _store(request).get_user_by_credentials(
            paris_username=body.paris_username,
            paris_password=body.paris_password,
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials or user is not allow-listed.",
            )
        request.session["user_id"] = user.id
        return JSONResponse({"user": _user_payload(user)})

    @app.delete("/api/session")
    def api_logout(request: Request) -> JSONResponse:
        """Clear the session cookie.  Idempotent so the client can fire-and-forget."""

        request.session.clear()
        return JSONResponse({"ok": True})

    @app.post("/api/bootstrap-admin", status_code=status.HTTP_201_CREATED)
    def api_bootstrap_admin(
        request: Request, body: BootstrapAdminBody
    ) -> JSONResponse:
        """Create the very first admin account — only works on an empty store."""

        app_store = _store(request)
        if app_store.count_users() > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bootstrap is only available for the first account.",
            )
        if (
            not body.display_name.strip()
            or not body.paris_username.strip()
            or not body.paris_password
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="All admin bootstrap fields are required.",
            )
        user = app_store.create_user(
            display_name=body.display_name,
            paris_username=body.paris_username,
            paris_password=body.paris_password,
            is_admin=True,
            is_enabled=True,
        )
        request.session["user_id"] = user.id
        return JSONResponse({"user": _user_payload(user)}, status_code=201)

    # ----------------------------------------------------------- catalog
    @app.get("/api/catalog")
    def api_catalog(request: Request) -> JSONResponse:
        """Return live venue + filter options so the SPA can populate the form."""

        user = _require_user(request)
        catalog = _load_search_catalog_for_user(request=request, user=user)
        return JSONResponse(_catalog_payload(catalog))

    # ----------------------------------------------------------- searches
    @app.get("/api/searches")
    def api_list_searches(request: Request) -> JSONResponse:
        """List the current user's saved searches with resolved next booking dates."""

        user = _require_user(request)
        searches = _store(request).list_saved_searches(user_id=user.id)
        payload = [
            _search_payload(search, _settings(request).timezone) for search in searches
        ]
        return JSONResponse({"searches": payload})

    @app.post("/api/searches", status_code=status.HTTP_201_CREATED)
    def api_create_search(request: Request, body: CreateSearchBody) -> JSONResponse:
        """Create a new saved search with locally validated venue/weekday choices."""

        user = _require_user(request)
        catalog = _load_search_catalog_for_user(request=request, user=user)
        normalized_venues = _normalize_form_values(body.venue_names)
        normalized_in_out_codes = _normalize_form_values(body.in_out_codes)

        try:
            if body.hour_start >= body.hour_end:
                raise ValidationError("hour_start must be lower than hour_end.")
            if not normalized_venues:
                raise ValidationError("Select at least one venue.")
            normalized_weekday = _normalize_weekday(body.weekday)
            if catalog is not None:
                for venue_name in normalized_venues:
                    if venue_name not in catalog.venues:
                        raise ValidationError(f"Unknown venue '{venue_name}'.")
                for in_out_code in normalized_in_out_codes:
                    if in_out_code not in catalog.in_out_options:
                        raise ValidationError(
                            f"Unknown indoor/outdoor option '{in_out_code}'."
                        )
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error

        search = _store(request).create_saved_search(
            user_id=user.id,
            label=body.label,
            venue_names=normalized_venues,
            court_ids=tuple(),
            weekday=normalized_weekday,
            hour_start=body.hour_start,
            hour_end=body.hour_end,
            in_out_codes=normalized_in_out_codes,
        )
        return JSONResponse(
            {"search": _search_payload(search, _settings(request).timezone)},
            status_code=201,
        )

    @app.patch("/api/searches/{search_id}")
    def api_update_search(
        request: Request, search_id: int, body: UpdateSearchBody
    ) -> JSONResponse:
        """Patch any subset of editable fields on a saved search."""

        user = _require_user(request)
        existing = _store(request).get_saved_search(
            user_id=user.id, search_id=search_id
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Saved search not found.")

        # Validate any editable fields the client sent.  Reuse the same rules
        # as create so the contract stays consistent across endpoints.
        catalog = _load_search_catalog_for_user(request=request, user=user)
        normalized_venues: tuple[str, ...] | None = None
        normalized_in_out_codes: tuple[str, ...] | None = None
        normalized_weekday: str | None = None
        try:
            if body.venue_names is not None:
                normalized_venues = _normalize_form_values(body.venue_names)
                if not normalized_venues:
                    raise ValidationError("Select at least one venue.")
            if body.in_out_codes is not None:
                normalized_in_out_codes = _normalize_form_values(body.in_out_codes)
            if body.weekday is not None:
                normalized_weekday = _normalize_weekday(body.weekday)
            new_start = body.hour_start if body.hour_start is not None else existing.hour_start
            new_end = body.hour_end if body.hour_end is not None else existing.hour_end
            if new_start >= new_end:
                raise ValidationError("hour_start must be lower than hour_end.")
            if catalog is not None:
                check_venues = (
                    normalized_venues
                    if normalized_venues is not None
                    else existing.venue_names
                )
                for venue_name in check_venues:
                    if venue_name not in catalog.venues:
                        raise ValidationError(f"Unknown venue '{venue_name}'.")
                check_in_out = (
                    normalized_in_out_codes
                    if normalized_in_out_codes is not None
                    else existing.in_out_codes
                )
                for in_out_code in check_in_out:
                    if in_out_code not in catalog.in_out_options:
                        raise ValidationError(
                            f"Unknown indoor/outdoor option '{in_out_code}'."
                        )
        except ValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error

        search = existing
        # `is_active` keeps its dedicated setter so existing tests + the
        # toggle button do not need to reach through the larger update path.
        if body.is_active is not None:
            updated = _store(request).set_saved_search_active(
                user_id=user.id, search_id=search_id, is_active=body.is_active
            )
            if updated is not None:
                search = updated

        # Apply field edits in one SQL statement so the row update is atomic.
        if any(
            value is not None
            for value in (
                body.label,
                normalized_venues,
                normalized_weekday,
                body.hour_start,
                body.hour_end,
                normalized_in_out_codes,
            )
        ):
            updated = _store(request).update_saved_search(
                user_id=user.id,
                search_id=search_id,
                label=body.label,
                venue_names=normalized_venues,
                weekday=normalized_weekday,
                hour_start=body.hour_start,
                hour_end=body.hour_end,
                in_out_codes=normalized_in_out_codes,
            )
            if updated is not None:
                search = updated

        return JSONResponse(
            {"search": _search_payload(search, _settings(request).timezone)}
        )

    @app.delete("/api/searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
    def api_delete_search(request: Request, search_id: int) -> Response:
        """Remove one owned saved search.

        204 responses must have an empty body — return a bare ``Response`` so
        h11 does not raise ``Too much data for declared Content-Length``.
        """

        user = _require_user(request)
        _store(request).delete_saved_search(user_id=user.id, search_id=search_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/searches/{search_id}/book")
    def api_book_saved_search(request: Request, search_id: int) -> JSONResponse:
        """Run the booking flow for one saved search and return success/error JSON."""

        user = _require_user(request)
        saved_search = _store(request).get_saved_search(
            user_id=user.id, search_id=search_id
        )
        if saved_search is None:
            raise HTTPException(status_code=404, detail="Saved search not found.")
        try:
            _book_saved_search(request=request, user=user, saved_search=saved_search)
        except ParisTennisError as error:
            LOGGER.warning("Booking failed for user %s: %s", user.id, error)
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Unexpected booking error for user %s", user.id)
            raise HTTPException(status_code=500, detail=str(error)) from error
        return JSONResponse({"ok": True})

    @app.post("/api/searches/{search_id}/check-availability")
    def api_check_availability(request: Request, search_id: int) -> JSONResponse:
        """Run an anonymous search across the saved venues and return raw slots.

        No login, no captcha, no booking — purely a "is anything available
        right now?" probe.  Slots come back without bookable ids because the
        site only exposes those to authenticated sessions.
        """

        user = _require_user(request)
        saved_search = _store(request).get_saved_search(
            user_id=user.id, search_id=search_id
        )
        if saved_search is None:
            raise HTTPException(status_code=404, detail="Saved search not found.")

        target_date_iso = _resolve_next_weekday_date_iso(
            weekday=saved_search.weekday,
            timezone_name=_settings(request).timezone,
        )

        def _probe(client: Any) -> list[dict[str, object]]:
            results: list[dict[str, object]] = []
            for venue_name in saved_search.venue_names:
                venue_payload: dict[str, object] = {
                    "name": venue_name,
                    "slots": [],
                    "error": "",
                }
                try:
                    result = client.search_slots(
                        SearchRequest(
                            venue_name=venue_name,
                            date_iso=target_date_iso,
                            hour_start=saved_search.hour_start,
                            hour_end=saved_search.hour_end,
                            surface_ids=tuple(),
                            in_out_codes=saved_search.in_out_codes,
                        )
                    )
                except ParisTennisError as error:
                    venue_payload["error"] = str(error)
                else:
                    venue_payload["slots"] = [
                        {
                            "hour": slot.date_deb,
                            "price": slot.price_eur,
                            "label": slot.price_label,
                        }
                        for slot in result.slots
                    ]
                results.append(venue_payload)
            return results

        session = _session_manager(request).get_anonymous_session()
        try:
            venues = session.run(_probe)
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Anonymous availability check failed for user %s", user.id)
            raise HTTPException(status_code=502, detail=str(error)) from error

        return JSONResponse({"date": target_date_iso, "venues": venues})

    @app.post("/api/searches/{search_id}/duplicate", status_code=status.HTTP_201_CREATED)
    def api_duplicate_search(request: Request, search_id: int) -> JSONResponse:
        """Clone a saved search so the user can tweak a copy without losing the original."""

        user = _require_user(request)
        original = _store(request).get_saved_search(
            user_id=user.id, search_id=search_id
        )
        if original is None:
            raise HTTPException(status_code=404, detail="Saved search not found.")
        copy = _store(request).create_saved_search(
            user_id=user.id,
            label=f"{original.label} (copy)",
            venue_names=original.venue_names,
            court_ids=original.court_ids,
            weekday=original.weekday,
            hour_start=original.hour_start,
            hour_end=original.hour_end,
            in_out_codes=original.in_out_codes,
        )
        return JSONResponse(
            {"search": _search_payload(copy, _settings(request).timezone)},
            status_code=201,
        )

    # ----------------------------------------------------------- history
    @app.get("/api/history")
    def api_history(request: Request) -> JSONResponse:
        """Return locally recorded booking history enriched with court labels."""

        user = _require_user(request)
        records = _store(request).list_booking_history(user_id=user.id)
        # Resolve human-readable court names from the catalog so the SPA does
        # not have to display raw ids like "court=4387".  The lookup is keyed
        # by (venue_name, court_id) because court ids are not globally unique.
        catalog = _load_search_catalog_for_user(request=request, user=user)
        court_names: dict[tuple[str, str], str] = {}
        if catalog is not None:
            for venue in catalog.venues.values():
                for court in venue.courts:
                    court_names[(venue.name, court.court_id)] = court.name
        enriched = []
        for record in records:
            payload = asdict(record)
            payload["court_name"] = court_names.get(
                (record.venue_name, record.court_id), ""
            )
            enriched.append(payload)
        return JSONResponse({"records": enriched})

    @app.get("/api/history/pending")
    def api_history_pending(request: Request) -> JSONResponse:
        """Fetch the live reservation status — slow, so it has its own endpoint."""

        user = _require_user(request)
        try:
            session = _session_manager(request).get_session(
                user_id=user.id,
                paris_username=user.paris_username,
                paris_password=user.paris_password,
            )
            pending = session.run(lambda client: client.get_current_reservation())
        except ParisTennisError as error:
            LOGGER.warning(
                "Pending reservation fetch failed for user %s: %s", user.id, error
            )
            return JSONResponse({"pending": None, "error": str(error)})
        return JSONResponse(
            {
                "pending": {
                    "has_active_reservation": pending.has_active_reservation,
                    "raw_text": pending.raw_text,
                    "details": (
                        asdict(pending.details) if pending.details is not None else None
                    ),
                },
                "error": "",
            }
        )

    @app.delete("/api/history/pending")
    def api_cancel_pending(request: Request) -> JSONResponse:
        """Cancel the live reservation by driving the same API the CLI uses."""

        user = _require_user(request)
        try:
            session = _session_manager(request).get_session(
                user_id=user.id,
                paris_username=user.paris_username,
                paris_password=user.paris_password,
            )
            canceled = session.run(
                lambda client: client.cancel_current_reservation()
            )
        except ParisTennisError as error:
            LOGGER.warning("Cancellation failed for user %s: %s", user.id, error)
            raise HTTPException(status_code=400, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Unexpected cancellation error for user %s", user.id)
            raise HTTPException(status_code=500, detail=str(error)) from error
        return JSONResponse({"canceled": bool(canceled)})

    # ----------------------------------------------------------- admin
    @app.get("/api/admin/users")
    def api_admin_list_users(request: Request) -> JSONResponse:
        """Return every user in the allow-list.  Admin only."""

        _require_admin(request)
        return JSONResponse(
            {"users": [_user_payload(u) for u in _store(request).list_users()]}
        )

    @app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
    def api_admin_create_user(
        request: Request, body: CreateUserBody
    ) -> JSONResponse:
        """Create a new allow-listed user.  Admin only."""

        _require_admin(request)
        if (
            not body.display_name.strip()
            or not body.paris_username.strip()
            or not body.paris_password
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="All fields are required when adding a user.",
            )
        try:
            user = _store(request).create_user(
                display_name=body.display_name,
                paris_username=body.paris_username,
                paris_password=body.paris_password,
                is_admin=body.is_admin,
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That Paris username already exists.",
            ) from error
        return JSONResponse({"user": _user_payload(user)}, status_code=201)

    @app.post("/api/admin/users/{target_user_id}/check-login")
    def api_admin_check_user_login(
        request: Request, target_user_id: int
    ) -> JSONResponse:
        """Attempt a Paris Tennis login for one user and report success/failure."""

        _require_admin(request)
        target = _store(request).get_user(target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found.")
        try:
            with client_factory(
                email=target.paris_username,
                password=target.paris_password,
                captcha_api_key=_session_manager(request)._captcha_api_key,
                headless=app_settings.headless,
            ) as client:
                client.login()
            return JSONResponse({"ok": True, "detail": "Login succeeded."})
        except Exception as error:  # noqa: BLE001
            LOGGER.warning(
                "Login check failed for user %s: %s", target.display_name, error
            )
            return JSONResponse(
                {"ok": False, "detail": str(error)},
                status_code=status.HTTP_200_OK,
            )

    @app.patch("/api/admin/users/{target_user_id}")
    def api_admin_update_user(
        request: Request, target_user_id: int, body: UpdateUserBody
    ) -> JSONResponse:
        """Update any user field.  Validates credentials when they change."""

        actor = _require_admin(request)
        target = _store(request).get_user(target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Target user not found.")

        # Guard: the last remaining admin cannot be demoted.
        if body.is_admin is not None:
            if (
                target.is_admin
                and not body.is_admin
                and _store(request).count_admin_users() == 1
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot remove the last admin role.",
                )

        # Guard: the last active admin cannot be disabled out of the system.
        if body.is_enabled is not None:
            if (
                target.id == actor.id
                and target.is_enabled
                and not body.is_enabled
                and _store(request).count_admin_users() == 1
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot disable the last active admin.",
                )

        # When credentials change, verify they work before persisting.
        _verify_credentials_if_changed(
            request,
            current_user=target,
            new_username=body.paris_username,
            new_password=body.paris_password,
            captcha_api_key=_session_manager(request)._captcha_api_key,
            headless=app_settings.headless,
            client_factory=client_factory,
        )

        try:
            updated = _store(request).update_user(
                user_id=target.id,
                display_name=body.display_name,
                paris_username=body.paris_username,
                paris_password=body.paris_password,
                is_admin=body.is_admin,
                is_enabled=body.is_enabled,
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That Paris username already exists.",
            ) from error
        return JSONResponse({"user": _user_payload(updated or target)})

    @app.delete("/api/admin/users/{target_user_id}")
    def api_admin_delete_user(
        request: Request, target_user_id: int
    ) -> JSONResponse:
        """Hard-delete a user and all their data.  Cannot delete the last admin."""

        actor = _require_admin(request)
        target = _store(request).get_user(target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found.")

        # Prevent deleting yourself if you're the last admin.
        if (
            target.is_admin
            and _store(request).count_admin_users() == 1
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the last admin.",
            )

        # Invalidate session if deleting yourself (edge case: admin deletes self).
        if target.id == actor.id:
            request.session.clear()

        _store(request).delete_user(user_id=target.id)
        return JSONResponse({"ok": True})

    # ----------------------------------------------------------- self-edit
    @app.patch("/api/me")
    def api_update_me(request: Request, body: UpdateMeBody) -> JSONResponse:
        """Let any user update their own profile.  Validates credentials on change."""

        user = _require_user(request)

        _verify_credentials_if_changed(
            request,
            current_user=user,
            new_username=body.paris_username,
            new_password=body.paris_password,
            captcha_api_key=_session_manager(request)._captcha_api_key,
            headless=app_settings.headless,
            client_factory=client_factory,
        )

        try:
            updated = _store(request).update_user(
                user_id=user.id,
                display_name=body.display_name,
                paris_username=body.paris_username,
                paris_password=body.paris_password,
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That Paris username already exists.",
            ) from error
        return JSONResponse({"user": _user_payload(updated or user)})

    # ----------------------------------------------------------- scheduler
    @app.get("/api/admin/scheduler")
    def api_admin_scheduler(request: Request) -> JSONResponse:
        """Return scheduler config + recent tick log for the admin page."""

        _require_admin(request)
        runs = _store(request).list_scheduler_runs(limit=25)
        return JSONResponse(
            {
                "settings": _scheduler(request).read_settings(),
                "runs": [_scheduler_run_payload(run) for run in runs],
            }
        )

    @app.patch("/api/admin/scheduler")
    def api_admin_update_scheduler(
        request: Request, body: UpdateSchedulerBody
    ) -> JSONResponse:
        """Patch any subset of scheduler settings; loop re-reads on next tick."""

        _require_admin(request)
        burst_windows = (
            [bw.model_dump() for bw in body.burst_windows]
            if body.burst_windows is not None
            else None
        )
        settings = _scheduler(request).write_settings(
            enabled=body.enabled,
            default_interval_seconds=body.default_interval_seconds,
            tick_noise_seconds=body.tick_noise_seconds,
            burst_windows=burst_windows,
        )
        return JSONResponse({"settings": settings})

    @app.post("/api/admin/scheduler/run")
    def api_admin_run_scheduler_now(request: Request) -> JSONResponse:
        """Force one tick immediately and return its summary."""

        _require_admin(request)
        try:
            summary = _scheduler(request).run_once()
        except Exception as error:  # noqa: BLE001
            LOGGER.exception("Force-tick failed")
            raise HTTPException(status_code=500, detail=str(error)) from error
        return JSONResponse({"summary": summary})

    @app.get("/api/admin/scheduler/runs")
    def api_admin_scheduler_runs(
        request: Request, limit: int = 100
    ) -> JSONResponse:
        """Return paginated tick history for the admin log view."""

        _require_admin(request)
        clamped = max(1, min(500, limit))
        runs = _store(request).list_scheduler_runs(limit=clamped)
        return JSONResponse(
            {"runs": [_scheduler_run_payload(run) for run in runs]}
        )

    # ----------------------------------------------------------- settings
    @app.get("/api/admin/settings")
    def api_admin_settings(request: Request) -> JSONResponse:
        """Return runtime-configurable settings for the admin page."""

        _require_admin(request)
        stored = _store(request).list_app_settings()
        return JSONResponse({
            "settings": {
                "captcha_api_key": stored.get("captcha_api_key", ""),
            }
        })

    @app.patch("/api/admin/settings")
    def api_admin_update_settings(
        request: Request, body: UpdateSettingsBody
    ) -> JSONResponse:
        """Update runtime settings; changes take effect immediately."""

        _require_admin(request)
        store = _store(request)
        if body.captcha_api_key is not None:
            store.set_app_setting("captcha_api_key", body.captcha_api_key.strip())
            # Propagate to the live session manager so new browser sessions
            # pick up the key without requiring a process restart.
            _session_manager(request)._captcha_api_key = body.captcha_api_key.strip()
        stored = store.list_app_settings()
        return JSONResponse({
            "settings": {
                "captcha_api_key": stored.get("captcha_api_key", ""),
            }
        })

    # ----------------------------------------------------------- SPA
    # In production the Vite build is mounted at / and any unknown path
    # returns index.html so client-side React Router can handle it.  In dev
    # the frontend runs on :5173 and proxies /api to this server, so these
    # routes are only hit when someone opens the FastAPI port directly.
    if WEB_DIST_DIR.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=str(WEB_DIST_DIR / "assets")),
            name="assets",
        )

        @app.get("/{full_path:path}")
        def spa_catch_all(full_path: str) -> FileResponse:
            # Serve real files if present (e.g. favicon.ico), otherwise
            # hand back the SPA shell so React Router can route the URL.
            candidate = WEB_DIST_DIR / full_path if full_path else None
            if candidate and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEB_DIST_DIR / "index.html")
    else:
        @app.get("/")
        def spa_missing_hint() -> JSONResponse:
            """Helpful 503 when the dev run forgot to build the SPA."""

            return JSONResponse(
                {
                    "detail": (
                        "web/dist not found. Run `cd web && bun install && bun run "
                        "build`, or start the Vite dev server on :5173."
                    )
                },
                status_code=503,
            )

    return app


# ---------------------------------------------------------------------------
# Booking core — unchanged from the Jinja version, still runs through the
# per-user session worker so Playwright stays thread-bound.
# ---------------------------------------------------------------------------


def _book_saved_search(
    *,
    request: Request,
    user: AllowedUser,
    saved_search: SavedSearch,
) -> None:
    """Run search and booking from one saved-search record and persist a history row."""

    settings = _settings(request)
    if not _has_captcha_key(request):
        raise BookingError(
            "Missing captcha key for booking. "
            "Set it in Admin > Settings or via the CAPTCHA_API_KEY env var."
        )

    target_date_iso = _resolve_next_weekday_date_iso(
        weekday=saved_search.weekday,
        timezone_name=settings.timezone,
    )

    session = _session_manager(request).get_session(
        user_id=user.id,
        paris_username=user.paris_username,
        paris_password=user.paris_password,
    )

    catalog = session.get_catalog_cached()
    all_surface_ids = (
        tuple(catalog.surface_options.keys()) if catalog is not None else tuple()
    )
    all_in_out_codes = (
        tuple(catalog.in_out_options.keys()) if catalog is not None else tuple()
    )
    effective_in_out_codes = saved_search.in_out_codes or all_in_out_codes

    def _booking_task(client: Any) -> tuple[str, Any]:
        chosen_venue_name = ""
        chosen_result = None
        for venue_name in saved_search.venue_names:
            result = client.search_slots(
                SearchRequest(
                    venue_name=venue_name,
                    date_iso=target_date_iso,
                    hour_start=saved_search.hour_start,
                    hour_end=saved_search.hour_end,
                    surface_ids=all_surface_ids,
                    in_out_codes=effective_in_out_codes,
                )
            )
            LOGGER.debug(
                "Saved search %s @ %s: %d slot(s) found (captcha=%s)",
                saved_search.id,
                venue_name,
                len(result.slots),
                bool(result.captcha_request_id),
            )
            if result.slots:
                chosen_venue_name = venue_name
                chosen_result = result
                break

        if chosen_result is None:
            raise BookingError("No slot available for this saved search.")
        if not chosen_result.captcha_request_id:
            raise BookingError(
                "Search result is not bookable (missing captcha request id)."
            )

        slot = chosen_result.slots[0]
        LOGGER.info(
            "Saved search %s booking slot @ %s: equipment=%s court=%s %s→%s",
            saved_search.id,
            chosen_venue_name,
            slot.equipment_id,
            slot.court_id,
            slot.date_deb,
            slot.date_fin,
        )
        client.book_slot(slot=slot, captcha_request_id=chosen_result.captcha_request_id)
        reservation = client.get_current_reservation()
        if not reservation.has_active_reservation:
            raise BookingError(
                "Booking flow finished but no active reservation was detected "
                f"(profile_summary={reservation.raw_text!r})."
            )
        return chosen_venue_name, slot

    chosen_venue_name, slot = session.run(_booking_task)

    _store(request).add_booking_record(
        user_id=user.id,
        search_id=saved_search.id,
        venue_name=chosen_venue_name,
        slot=slot,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_payload(user: AllowedUser) -> dict[str, object]:
    """Serialize a user for the API without leaking the password hash column."""

    return {
        "id": user.id,
        "display_name": user.display_name,
        "paris_username": user.paris_username,
        "is_admin": user.is_admin,
        "is_enabled": user.is_enabled,
        "created_at": user.created_at,
    }


def _catalog_payload(catalog: SearchCatalog | None) -> dict[str, object]:
    """Shape the catalog for the React form: list venues + in/out options."""

    if catalog is None:
        return {
            "venues": [],
            "in_out_options": [{"code": "V", "label": "Indoor"},
                               {"code": "E", "label": "Outdoor"}],
            "min_hour": 8,
            "max_hour": 22,
            "available": False,
        }
    venues = [
        {
            "name": venue.name,
            "available_now": venue.available_now,
            "courts": [{"id": c.court_id, "name": c.name} for c in venue.courts],
        }
        for venue in sorted(
            catalog.venues.values(), key=lambda value: value.name.lower()
        )
    ]
    in_out_options = [
        {"code": code, "label": label} for code, label in catalog.in_out_options.items()
    ]
    return {
        "venues": venues,
        "in_out_options": in_out_options
        or [{"code": "V", "label": "Indoor"}, {"code": "E", "label": "Outdoor"}],
        "min_hour": catalog.min_hour,
        "max_hour": catalog.max_hour,
        "available": True,
    }


def _search_payload(search: SavedSearch, timezone_name: str) -> dict[str, object]:
    """Serialize one saved search plus the resolved next-booking date."""

    try:
        next_date = _resolve_next_weekday_date_iso(
            weekday=search.weekday, timezone_name=timezone_name
        )
    except ValidationError:
        next_date = ""
    return {
        "id": search.id,
        "label": search.label,
        "venue_names": list(search.venue_names),
        "weekday": search.weekday,
        "weekday_label": _WEEKDAY_LABELS.get(search.weekday, search.weekday),
        "hour_start": search.hour_start,
        "hour_end": search.hour_end,
        "in_out_codes": list(search.in_out_codes),
        "is_active": search.is_active,
        "next_date": next_date,
        "created_at": search.created_at,
    }


def _load_search_catalog_for_user(
    *, request: Request, user: AllowedUser
) -> SearchCatalog | None:
    """Return TTL-cached catalog so dashboard renders don't pay login latency."""

    try:
        session = _session_manager(request).get_session(
            user_id=user.id,
            paris_username=user.paris_username,
            paris_password=user.paris_password,
        )
        return session.get_catalog_cached()
    except Exception as error:  # noqa: BLE001
        LOGGER.warning("Could not load search catalog for user %s: %s", user.id, error)
        return None


def _warm_catalogs_in_background(
    *, store: WebAppStore, manager: UserSessionManager
) -> None:
    """Pre-populate per-user catalog caches so the first /searches is fast."""

    def _runner() -> None:
        for user in store.list_users():
            if not user.is_enabled:
                continue
            try:
                session = manager.get_session(
                    user_id=user.id,
                    paris_username=user.paris_username,
                    paris_password=user.paris_password,
                )
                catalog = session.get_catalog_cached()
            except Exception as error:  # noqa: BLE001
                LOGGER.warning(
                    "Catalog warm-up failed for user %s: %s", user.id, error
                )
                continue
            LOGGER.info(
                "Catalog warmed for user %s (%s): %s",
                user.id,
                user.display_name,
                "ok" if catalog is not None else "unavailable",
            )

    threading.Thread(
        target=_runner,
        name="catalog-warmer",
        daemon=True,
    ).start()


def _normalize_form_values(values: list[str]) -> tuple[str, ...]:
    """Normalize multi-select values into unique stable tuples."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = raw_value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _verify_credentials_if_changed(
    request: Request,
    *,
    current_user: AllowedUser,
    new_username: str | None,
    new_password: str | None,
    captcha_api_key: str,
    headless: bool,
    client_factory: type[ParisTennisClient],
) -> None:
    """Run a live login check when credentials differ from the stored ones.

    Raises 422 with the check-login error if the credentials are invalid,
    preventing the update from being persisted.
    """

    username = new_username or current_user.paris_username
    password = new_password or current_user.paris_password
    credentials_changed = (
        (new_username is not None and new_username != current_user.paris_username)
        or (new_password is not None and new_password != current_user.paris_password)
    )
    if not credentials_changed:
        return
    try:
        with client_factory(
            email=username,
            password=password,
            captcha_api_key=captcha_api_key,
            headless=headless,
        ) as client:
            client.login()
    except Exception as error:  # noqa: BLE001
        LOGGER.warning(
            "Credential check failed for %s: %s", current_user.display_name, error
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Login check failed with the new credentials: {error}",
        ) from error


def _normalize_weekday(raw_weekday: str) -> str:
    """Validate weekday select values so booking date resolution is deterministic."""

    weekday = raw_weekday.strip().lower()
    if weekday not in _WEEKDAY_LABELS:
        raise ValidationError("Weekday must be one of Monday-Sunday.")
    return weekday


def _resolve_next_weekday_date_iso(*, weekday: str, timezone_name: str) -> str:
    """Resolve selected weekday to the next upcoming DD/MM/YYYY date in app timezone."""

    normalized_weekday = _normalize_weekday(weekday)
    day_index = [value for value, _ in WEEKDAY_OPTIONS].index(normalized_weekday)
    today = _today_in_timezone(timezone_name)
    days_until_target = (day_index - today.weekday()) % 7
    if days_until_target == 0:
        days_until_target = 7
    target = today + dt.timedelta(days=days_until_target)
    return target.strftime("%d/%m/%Y")


def _today_in_timezone(timezone_name: str) -> dt.date:
    """Return today's date in configured timezone, with UTC fallback."""

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        LOGGER.warning("Unknown timezone '%s'. Falling back to UTC.", timezone_name)
        timezone = dt.timezone.utc
    return dt.datetime.now(timezone).date()


def _has_captcha_key(request: Request) -> bool:
    """Check DB-stored key first, then env-backed settings as fallback."""

    db_key = _store(request).get_app_setting("captcha_api_key")
    if db_key.strip():
        return True
    return bool(_settings(request).captcha_api_key.strip())


def _get_current_user(request: Request) -> AllowedUser | None:
    """Resolve session user id to the current allow-listed user."""

    raw_user_id = request.session.get("user_id")
    if not isinstance(raw_user_id, int):
        return None
    user = _store(request).get_user(raw_user_id)
    if user is None or not user.is_enabled:
        request.session.pop("user_id", None)
        return None
    return user


def _require_user(request: Request) -> AllowedUser:
    """Raise 401 instead of redirecting — the SPA handles the nav after a 401."""

    user = _get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _require_admin(request: Request) -> AllowedUser:
    """Raise 403 when a non-admin hits an admin-only endpoint."""

    user = _require_user(request)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")
    return user


def _store(request: Request) -> WebAppStore:
    return request.app.state.store


def _settings(request: Request) -> WebAppSettings:
    return request.app.state.settings


def _session_manager(request: Request) -> UserSessionManager:
    return request.app.state.session_manager


def _scheduler(request: Request) -> SchedulerService:
    return request.app.state.scheduler


def _scheduler_run_payload(run: Any) -> dict[str, Any]:
    """Inflate the JSON summary so the admin UI does not have to parse strings."""

    try:
        summary = json.loads(run.summary_json) if run.summary_json else {}
    except json.JSONDecodeError:
        summary = {"raw": run.summary_json}
    return {
        "id": run.id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "summary": summary,
    }


app = create_app()
