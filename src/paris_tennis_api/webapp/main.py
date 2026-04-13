"""FastAPI application for the local low-maintenance Paris Tennis web UI."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.exceptions import BookingError, ParisTennisError, ValidationError
from paris_tennis_api.models import SearchRequest
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import AllowedUser, SavedSearch, WebAppStore

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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

    app = FastAPI(title="RainClaude Tennis Booker", version="0.1.0")
    app.add_middleware(
        SessionMiddleware,
        # Signed cookie sessions avoid a dedicated cache/database dependency.
        secret_key=app_settings.session_secret,
        same_site="lax",
        https_only=False,
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    app.state.settings = app_settings
    app.state.store = app_store
    app.state.client_factory = client_factory

    @app.get("/healthz")
    def healthz(request: Request) -> dict[str, object]:
        """Expose a minimal unauthenticated probe for deployment health checks."""

        store = _store(request)
        # Keep this payload stable so infrastructure probes can alert on drift.
        return {
            "status": "ok",
            "users": store.count_users(),
            "enabled_admins": store.count_admin_users(),
        }

    @app.get("/", response_class=HTMLResponse)
    def root(request: Request) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")
        return _redirect("/searches")

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request) -> Response:
        user = _get_current_user(request)
        if user is not None:
            return _redirect("/searches")

        return _render(
            request,
            "login.html",
            needs_bootstrap=_store(request).count_users() == 0,
            flash=_pop_flash(request),
            active_page="login",
        )

    @app.post("/bootstrap-admin")
    def bootstrap_admin(
        request: Request,
        display_name: str = Form(...),
        paris_username: str = Form(...),
        paris_password: str = Form(...),
    ) -> Response:
        app_store = _store(request)
        if app_store.count_users() > 0:
            _set_flash(
                request, "Bootstrap is only available for the first account.", "error"
            )
            return _redirect("/login")
        if not display_name.strip() or not paris_username.strip() or not paris_password:
            _set_flash(request, "All admin bootstrap fields are required.", "error")
            return _redirect("/login")

        user = app_store.create_user(
            display_name=display_name,
            paris_username=paris_username,
            paris_password=paris_password,
            is_admin=True,
            is_enabled=True,
        )
        request.session["user_id"] = user.id
        _set_flash(request, "Admin account created.", "success")
        return _redirect("/searches")

    @app.post("/login")
    def login(
        request: Request,
        paris_username: str = Form(...),
        paris_password: str = Form(...),
    ) -> Response:
        user = _store(request).get_user_by_credentials(
            paris_username=paris_username,
            paris_password=paris_password,
        )
        if user is None:
            _set_flash(
                request, "Invalid credentials or user is not allow-listed.", "error"
            )
            return _redirect("/login")

        request.session["user_id"] = user.id
        _set_flash(request, f"Welcome back {user.display_name}.", "success")
        return _redirect("/searches")

    @app.post("/logout")
    def logout(request: Request) -> Response:
        request.session.clear()
        _set_flash(request, "Logged out.", "info")
        return _redirect("/login")

    @app.get("/searches", response_class=HTMLResponse)
    def searches_page(request: Request) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        return _render(
            request,
            "searches.html",
            user=user,
            searches=_store(request).list_saved_searches(user_id=user.id),
            flash=_pop_flash(request),
            active_page="searches",
            captcha_configured=bool(_settings(request).captcha_api_key),
        )

    @app.post("/searches")
    def create_saved_search(
        request: Request,
        label: str = Form(...),
        venue_name: str = Form(...),
        date_iso: str = Form(...),
        hour_start: int = Form(...),
        hour_end: int = Form(...),
        surface_ids: str = Form(""),
        in_out_codes: str = Form(""),
        slot_index: int = Form(1),
    ) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        try:
            if hour_start >= hour_end:
                raise ValidationError("hour_start must be lower than hour_end.")
            if slot_index < 1:
                raise ValidationError("slot_index must be >= 1.")
            dt.datetime.strptime(date_iso.strip(), "%d/%m/%Y")
        except ValueError as error:
            _set_flash(request, f"Date must use DD/MM/YYYY format: {error}", "error")
            return _redirect("/searches")
        except ValidationError as error:
            _set_flash(request, str(error), "error")
            return _redirect("/searches")

        _store(request).create_saved_search(
            user_id=user.id,
            label=label,
            venue_name=venue_name,
            date_iso=date_iso,
            hour_start=hour_start,
            hour_end=hour_end,
            surface_ids=_split_csv(surface_ids),
            in_out_codes=_split_csv(in_out_codes),
            slot_index=slot_index,
        )
        _set_flash(request, "Saved search created.", "success")
        return _redirect("/searches")

    @app.post("/searches/{search_id}/toggle")
    def toggle_saved_search(request: Request, search_id: int) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        search = _store(request).toggle_saved_search(
            user_id=user.id, search_id=search_id
        )
        if search is None:
            _set_flash(request, "Saved search not found.", "error")
            return _redirect("/searches")

        state = "active" if search.is_active else "inactive"
        _set_flash(request, f"Saved search switched to {state}.", "info")
        return _redirect("/searches")

    @app.post("/searches/{search_id}/delete")
    def delete_saved_search(request: Request, search_id: int) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        _store(request).delete_saved_search(user_id=user.id, search_id=search_id)
        _set_flash(request, "Saved search deleted.", "info")
        return _redirect("/searches")

    @app.post("/searches/{search_id}/book")
    def book_from_saved_search(request: Request, search_id: int) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        saved_search = _store(request).get_saved_search(
            user_id=user.id, search_id=search_id
        )
        if saved_search is None:
            _set_flash(request, "Saved search not found.", "error")
            return _redirect("/searches")

        try:
            _book_saved_search(
                request=request,
                user=user,
                saved_search=saved_search,
            )
        except ParisTennisError as error:
            LOGGER.warning("Booking failed for user %s: %s", user.id, error)
            _set_flash(request, str(error), "error")
            return _redirect("/searches")

        _set_flash(request, "Booking created and saved to history.", "success")
        return _redirect("/history")

    @app.get("/history", response_class=HTMLResponse)
    def history_page(request: Request) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        pending = None
        pending_error = ""
        try:
            with _client_factory(request)(
                email=user.paris_username,
                password=user.paris_password,
                captcha_api_key=_settings(request).captcha_api_key,
                headless=_settings(request).headless,
            ) as client:
                client.login()
                pending = client.get_current_reservation()
        except ParisTennisError as error:
            pending_error = str(error)
            LOGGER.warning(
                "Pending reservation fetch failed for user %s: %s", user.id, error
            )

        return _render(
            request,
            "history.html",
            user=user,
            pending=pending,
            pending_error=pending_error,
            records=_store(request).list_booking_history(user_id=user.id),
            flash=_pop_flash(request),
            active_page="history",
        )

    @app.get("/admin/users", response_class=HTMLResponse)
    def admin_users_page(request: Request) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")
        if not user.is_admin:
            _set_flash(request, "Admin role required.", "error")
            return _redirect("/searches")

        return _render(
            request,
            "admin_users.html",
            user=user,
            users=_store(request).list_users(),
            flash=_pop_flash(request),
            active_page="admin",
        )

    @app.post("/admin/users")
    def admin_create_user(
        request: Request,
        display_name: str = Form(...),
        paris_username: str = Form(...),
        paris_password: str = Form(...),
        is_admin: bool = Form(False),
    ) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")
        if not user.is_admin:
            _set_flash(request, "Admin role required.", "error")
            return _redirect("/searches")
        if not display_name.strip() or not paris_username.strip() or not paris_password:
            _set_flash(request, "All fields are required when adding a user.", "error")
            return _redirect("/admin/users")

        try:
            _store(request).create_user(
                display_name=display_name,
                paris_username=paris_username,
                paris_password=paris_password,
                is_admin=is_admin,
            )
        except sqlite3.IntegrityError:
            _set_flash(request, "That Paris username already exists.", "error")
            return _redirect("/admin/users")

        _set_flash(request, "User added to allow-list.", "success")
        return _redirect("/admin/users")

    @app.post("/admin/users/{target_user_id}/toggle-admin")
    def admin_toggle_admin_role(request: Request, target_user_id: int) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")
        if not user.is_admin:
            _set_flash(request, "Admin role required.", "error")
            return _redirect("/searches")

        target = _store(request).get_user(target_user_id)
        if target is None:
            _set_flash(request, "Target user not found.", "error")
            return _redirect("/admin/users")

        if (
            target.id == user.id
            and target.is_admin
            and _store(request).count_admin_users() == 1
        ):
            _set_flash(request, "Cannot remove the last admin role.", "error")
            return _redirect("/admin/users")

        _store(request).update_user_admin(
            user_id=target.id, is_admin=not target.is_admin
        )
        _set_flash(request, "Admin role updated.", "success")
        return _redirect("/admin/users")

    @app.post("/admin/users/{target_user_id}/toggle-enabled")
    def admin_toggle_enabled(request: Request, target_user_id: int) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")
        if not user.is_admin:
            _set_flash(request, "Admin role required.", "error")
            return _redirect("/searches")

        target = _store(request).get_user(target_user_id)
        if target is None:
            _set_flash(request, "Target user not found.", "error")
            return _redirect("/admin/users")

        if (
            target.id == user.id
            and target.is_enabled
            and _store(request).count_admin_users() == 1
        ):
            _set_flash(request, "Cannot disable the last active admin.", "error")
            return _redirect("/admin/users")

        _store(request).update_user_enabled(
            user_id=target.id, is_enabled=not target.is_enabled
        )
        _set_flash(request, "User status updated.", "success")
        return _redirect("/admin/users")

    return app


def _book_saved_search(
    *,
    request: Request,
    user: AllowedUser,
    saved_search: SavedSearch,
) -> None:
    """Run search and booking from one saved-search record and persist a history row."""

    settings = _settings(request)
    if not settings.captcha_api_key:
        raise BookingError("Missing PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY for booking.")

    with _client_factory(request)(
        email=user.paris_username,
        password=user.paris_password,
        captcha_api_key=settings.captcha_api_key,
        headless=settings.headless,
    ) as client:
        client.login()
        result = client.search_slots(
            SearchRequest(
                venue_name=saved_search.venue_name,
                date_iso=saved_search.date_iso,
                hour_start=saved_search.hour_start,
                hour_end=saved_search.hour_end,
                surface_ids=saved_search.surface_ids,
                in_out_codes=saved_search.in_out_codes,
            )
        )

        if not result.slots:
            raise BookingError("No slot available for this saved search.")
        if not result.captcha_request_id:
            raise BookingError(
                "Search result is not bookable (missing captcha request id)."
            )

        selected_index = saved_search.slot_index - 1
        if selected_index < 0 or selected_index >= len(result.slots):
            raise BookingError(
                f"slot_index={saved_search.slot_index} exceeds {len(result.slots)} available slot(s)."
            )

        slot = result.slots[selected_index]
        client.book_slot(slot=slot, captcha_request_id=result.captcha_request_id)
        reservation = client.get_current_reservation()
        if not reservation.has_active_reservation:
            raise BookingError(
                "Booking flow finished but no active reservation was detected."
            )

    _store(request).add_booking_record(
        user_id=user.id,
        search_id=saved_search.id,
        venue_name=saved_search.venue_name,
        slot=slot,
    )


def _render(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    """Inject global template values once so each route stays concise."""

    user = _get_current_user(request)
    return TEMPLATES.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "request": request,
            "current_user": user,
            **context,
        },
    )


def _split_csv(raw_value: str) -> tuple[str, ...]:
    """Normalize comma-separated form input into stable tuple storage."""

    values = [piece.strip() for piece in raw_value.split(",") if piece.strip()]
    return tuple(values)


def _redirect(path: str) -> RedirectResponse:
    """Use HTTP 303 to keep browser refreshes from resubmitting forms."""

    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


def _set_flash(request: Request, message: str, level: str) -> None:
    """Store one-shot UI messages in the signed session cookie."""

    request.session["flash"] = {"message": message, "level": level}


def _pop_flash(request: Request) -> dict[str, str] | None:
    """Read and clear a one-shot flash message in one operation."""

    value = request.session.pop("flash", None)
    if isinstance(value, dict):
        message = str(value.get("message", "")).strip()
        level = str(value.get("level", "info")).strip() or "info"
        if message:
            return {"message": message, "level": level}
    return None


def _get_current_user(request: Request) -> AllowedUser | None:
    """Resolve session user id to the current allow-listed user."""

    raw_user_id = request.session.get("user_id")
    if not isinstance(raw_user_id, int):
        return None
    user = _store(request).get_user(raw_user_id)
    if user is None or not user.is_enabled:
        # Invalid or disabled users are actively removed from the session.
        request.session.pop("user_id", None)
        return None
    return user


def _store(request: Request) -> WebAppStore:
    return request.app.state.store


def _settings(request: Request) -> WebAppSettings:
    return request.app.state.settings


def _client_factory(request: Request) -> type[ParisTennisClient]:
    return request.app.state.client_factory


app = create_app()
