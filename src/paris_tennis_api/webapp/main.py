"""FastAPI application for the local low-maintenance Paris Tennis web UI."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.exceptions import BookingError, ParisTennisError, ValidationError
from paris_tennis_api.models import SearchCatalog, SearchRequest
from paris_tennis_api.webapp.settings import WebAppSettings
from paris_tennis_api.webapp.store import AllowedUser, SavedSearch, WebAppStore

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
WEEKDAY_OPTIONS = (
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
    ("saturday", "Saturday"),
    ("sunday", "Sunday"),
)
WEEKDAY_LABELS = {value: label for value, label in WEEKDAY_OPTIONS}


@dataclass(frozen=True, slots=True)
class VenueOption:
    """One venue option rendered in the saved-search form select field."""

    venue_name: str
    label: str


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

        searches = _store(request).list_saved_searches(user_id=user.id)
        catalog = _load_search_catalog_for_user(request=request, user=user)
        venue_options = _build_venue_options(
            catalog=catalog,
            searches=searches,
        )
        in_out_options = _build_in_out_options(catalog=catalog)
        in_out_label_map = {code: label for code, label in in_out_options}
        next_dates: dict[int, str] = {}
        for search in searches:
            try:
                next_dates[search.id] = _resolve_next_weekday_date_iso(
                    weekday=search.weekday,
                    timezone_name=_settings(request).timezone,
                )
            except ValidationError:
                next_dates[search.id] = ""

        return _render(
            request,
            "searches.html",
            user=user,
            searches=searches,
            venue_options=venue_options,
            weekday_options=WEEKDAY_OPTIONS,
            in_out_options=in_out_options,
            in_out_label_map=in_out_label_map,
            weekday_labels=WEEKDAY_LABELS,
            next_dates=next_dates,
            flash=_pop_flash(request),
            active_page="searches",
            captcha_configured=_has_captcha_key(_settings(request)),
        )

    @app.post("/searches")
    def create_saved_search(
        request: Request,
        label: str = Form(...),
        venue_names: list[str] = Form(default=[]),
        weekday: str = Form(""),
        venue_name: str = Form(""),
        date_iso: str = Form(""),
        hour_start: int = Form(...),
        hour_end: int = Form(...),
        in_out_codes: list[str] = Form(default=[]),
    ) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        catalog = _load_search_catalog_for_user(request=request, user=user)
        normalized_venues = _normalize_form_values(venue_names)
        if not normalized_venues and venue_name.strip():
            normalized_venues = (venue_name.strip(),)
        normalized_in_out_codes = _normalize_form_values(in_out_codes)

        try:
            if hour_start >= hour_end:
                raise ValidationError("hour_start must be lower than hour_end.")
            if not normalized_venues:
                raise ValidationError("Select at least one venue.")
            if weekday.strip():
                normalized_weekday = _normalize_weekday(weekday)
            elif date_iso.strip():
                normalized_weekday = _weekday_from_date_iso(date_iso)
            else:
                raise ValidationError("Select a weekday.")
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
            _set_flash(request, str(error), "error")
            return _redirect("/searches")

        _store(request).create_saved_search(
            user_id=user.id,
            label=label,
            venue_names=normalized_venues,
            court_ids=tuple(),
            weekday=normalized_weekday,
            hour_start=hour_start,
            hour_end=hour_end,
            in_out_codes=normalized_in_out_codes,
        )
        _set_flash(request, "Saved search created.", "success")
        return _redirect("/searches")

    @app.post("/searches/{search_id}/state")
    def set_saved_search_state(
        request: Request,
        search_id: int,
        is_active: int = Form(...),
    ) -> Response:
        user = _get_current_user(request)
        if user is None:
            return _redirect("/login")

        search = _store(request).set_saved_search_active(
            user_id=user.id,
            search_id=search_id,
            is_active=bool(is_active),
        )
        if search is None:
            _set_flash(request, "Saved search not found.", "error")
            return _redirect("/searches")

        state = "active" if search.is_active else "inactive"
        _set_flash(request, f"Saved search switched to {state}.", "info")
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
    if not _has_captcha_key(settings):
        raise BookingError("Missing PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY for booking.")

    target_date_iso = _resolve_next_weekday_date_iso(
        weekday=saved_search.weekday,
        timezone_name=settings.timezone,
    )

    with _client_factory(request)(
        email=user.paris_username,
        password=user.paris_password,
        captcha_api_key=settings.captcha_api_key,
        headless=settings.headless,
    ) as client:
        client.login()

        chosen_venue_name = ""
        chosen_result = None
        for venue_name in saved_search.venue_names:
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

        selected_index = saved_search.slot_index - 1
        if selected_index < 0 or selected_index >= len(chosen_result.slots):
            raise BookingError(
                f"slot_index={saved_search.slot_index} exceeds {len(chosen_result.slots)} available slot(s)."
            )

        slot = chosen_result.slots[selected_index]
        client.book_slot(slot=slot, captcha_request_id=chosen_result.captcha_request_id)
        reservation = client.get_current_reservation()
        if not reservation.has_active_reservation:
            raise BookingError(
                "Booking flow finished but no active reservation was detected."
            )

    _store(request).add_booking_record(
        user_id=user.id,
        search_id=saved_search.id,
        venue_name=chosen_venue_name,
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


def _normalize_form_values(values: list[str]) -> tuple[str, ...]:
    """Normalize multi-select and checkbox form values into unique, stable tuples."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = raw_value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _normalize_weekday(raw_weekday: str) -> str:
    """Validate weekday select values so booking date resolution is always deterministic."""

    weekday = raw_weekday.strip().lower()
    if weekday not in WEEKDAY_LABELS:
        raise ValidationError("Weekday must be one of Monday-Sunday.")
    return weekday


def _weekday_from_date_iso(raw_date_iso: str) -> str:
    """Map legacy DD/MM/YYYY date payloads to weekday names for backward compatibility."""

    try:
        parsed = dt.datetime.strptime(raw_date_iso.strip(), "%d/%m/%Y")
    except ValueError as error:
        raise ValidationError(f"Date must use DD/MM/YYYY format: {error}") from error
    return parsed.strftime("%A").lower()


def _resolve_next_weekday_date_iso(*, weekday: str, timezone_name: str) -> str:
    """Resolve selected weekday to the next upcoming DD/MM/YYYY date in app timezone."""

    normalized_weekday = _normalize_weekday(weekday)
    day_index = [value for value, _ in WEEKDAY_OPTIONS].index(normalized_weekday)
    today = _today_in_timezone(timezone_name)
    days_until_target = (day_index - today.weekday()) % 7
    if days_until_target == 0:
        # Same-day selection should book the *next* occurrence, not today's slots.
        days_until_target = 7
    target = today + dt.timedelta(days=days_until_target)
    return target.strftime("%d/%m/%Y")


def _today_in_timezone(timezone_name: str) -> dt.date:
    """Return today's date in configured timezone, with UTC fallback for invalid tz names."""

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        LOGGER.warning("Unknown timezone '%s'. Falling back to UTC.", timezone_name)
        timezone = dt.timezone.utc
    return dt.datetime.now(timezone).date()


def _load_search_catalog_for_user(
    *, request: Request, user: AllowedUser
) -> SearchCatalog | None:
    """Fetch live search catalog so forms only expose values accepted by tennis.paris.fr."""

    try:
        with _client_factory(request)(
            email=user.paris_username,
            password=user.paris_password,
            captcha_api_key=_settings(request).captcha_api_key,
            headless=_settings(request).headless,
        ) as client:
            client.login()
            return client.get_search_catalog()
    except (ParisTennisError, AttributeError) as error:
        LOGGER.warning("Could not load search catalog for user %s: %s", user.id, error)
        return None


def _build_venue_options(
    *,
    catalog: SearchCatalog | None,
    searches: tuple[SavedSearch, ...],
) -> tuple[VenueOption, ...]:
    """Build form options from live catalog, with saved-search fallback when unavailable."""

    if catalog is not None and catalog.venues:
        options: list[VenueOption] = []
        for venue in sorted(catalog.venues.values(), key=lambda value: value.name.lower()):
            if venue.courts:
                preview = ", ".join(
                    court.name for court in venue.courts[:2] if court.name.strip()
                )
                suffix = f" ({preview})" if preview else ""
            else:
                suffix = ""
            options.append(VenueOption(venue_name=venue.name, label=f"{venue.name}{suffix}"))
        return tuple(options)

    # Preserve usability during transient upstream failures by falling back to existing searches.
    fallback_names = sorted({name for search in searches for name in search.venue_names})
    return tuple(VenueOption(venue_name=name, label=name) for name in fallback_names)


def _build_in_out_options(catalog: SearchCatalog | None) -> tuple[tuple[str, str], ...]:
    """Expose indoor/outdoor checkbox options with sensible defaults."""

    if catalog is not None and catalog.in_out_options:
        return tuple(catalog.in_out_options.items())
    return (
        ("V", "Indoor"),
        ("E", "Outdoor"),
    )


def _has_captcha_key(settings: WebAppSettings) -> bool:
    """Share one captcha-enabled check across templates and booking flow guards."""

    return bool(settings.captcha_api_key.strip())


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
