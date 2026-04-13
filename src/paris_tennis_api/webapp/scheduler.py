"""Background scheduler that auto-books saved searches as slots open up.

Design (locked with the user):

- One daemon thread inside the FastAPI process.  It re-reads its own
  configuration from ``app_settings`` on every loop so admin tweaks take
  effect without a restart.
- Every tick: snapshot every active saved search across all users; for
  each user, run an anonymous availability probe (cheap, no login); for
  users with a hit, log into their persistent session, refuse to book if
  they already have a pending reservation (one-reservation-per-user
  constraint), otherwise book the first available slot.
- On success: auto-deactivate the search (decision 2a — never auto-book
  the same window twice).
- On failure: bump failure_count; auto-deactivate after 3 consecutive
  failures so a broken account/venue does not loop forever.
- Sleep intervals come from ``default_interval_seconds`` plus optional
  burst windows so the operator can poll heavily around 08:00 Paris.

The scheduler depends on the same ``UserSessionManager`` and ``WebAppStore``
the request handlers use, so booking flows that work for "Book now" also
work here without duplication.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import random
import threading
import time
from dataclasses import asdict
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from paris_tennis_api.exceptions import ParisTennisError
from paris_tennis_api.models import SearchRequest
from paris_tennis_api.webapp.sessions import UserSessionManager
from paris_tennis_api.webapp.store import SavedSearch, WebAppStore

LOGGER = logging.getLogger(__name__)

# Settings keys in app_settings — kept here so the API layer and the
# scheduler agree on the wire format.
SETTING_ENABLED = "scheduler.enabled"
SETTING_INTERVAL = "scheduler.default_interval_seconds"
SETTING_BURST_WINDOWS = "scheduler.burst_windows"
SETTING_TICK_NOISE = "scheduler.tick_noise_seconds"

# Defaults applied when no row exists in app_settings yet.  Conservative on
# purpose so the scheduler does not start booking on a fresh deploy.
DEFAULT_ENABLED = False
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_BURST_WINDOWS: list[dict[str, int | str]] = []
DEFAULT_TICK_NOISE_SECONDS = 0
MAX_FAILURES_BEFORE_PAUSE = 3
# Outer bounds the scheduler enforces regardless of admin input.  Lower
# bound prevents accidental DoS on tennis.paris.fr; upper keeps the loop
# responsive to admin toggles within one minute.
MIN_INTERVAL_SECONDS = 5
MAX_INTERVAL_SECONDS = 3600
# Jitter ceiling.  Anything bigger than 60s makes the bounds checks noisy
# and is not a use case we care about (the goal is to mask the periodic
# pattern, not randomize wildly).
MAX_TICK_NOISE_SECONDS = 60


class SchedulerService:
    """Daemon-thread scheduler for auto-booking active saved searches."""

    def __init__(
        self,
        *,
        store: WebAppStore,
        session_manager: UserSessionManager,
        timezone_name: str,
    ) -> None:
        self._store = store
        self._session_manager = session_manager
        self._timezone_name = timezone_name
        self._shutdown = threading.Event()
        # Tick lock protects both the run loop and force-tick callers; we
        # never want two ticks running concurrently because they would
        # double-book or fight over the anonymous browser.
        self._tick_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the daemon thread.  Idempotent for re-init scenarios."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="paris-tennis-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        """Signal the loop to exit and join the thread."""

        self._shutdown.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def run_once(self) -> dict[str, Any]:
        """Force a tick now and return its summary; used by admin "Run now"."""

        return self._run_tick(forced=True)

    # ------------------------------------------------------------------
    # Settings access (re-read every loop so admin edits apply live)
    # ------------------------------------------------------------------

    def read_settings(self) -> dict[str, Any]:
        """Return the current scheduler settings + read-only diagnostics."""

        raw = self._store.list_app_settings()
        return {
            "enabled": _parse_bool(
                raw.get(SETTING_ENABLED), default=DEFAULT_ENABLED
            ),
            "default_interval_seconds": _parse_int(
                raw.get(SETTING_INTERVAL),
                default=DEFAULT_INTERVAL_SECONDS,
                lower=MIN_INTERVAL_SECONDS,
                upper=MAX_INTERVAL_SECONDS,
            ),
            "tick_noise_seconds": _parse_int(
                raw.get(SETTING_TICK_NOISE),
                default=DEFAULT_TICK_NOISE_SECONDS,
                lower=0,
                upper=MAX_TICK_NOISE_SECONDS,
            ),
            "burst_windows": _parse_burst_windows(raw.get(SETTING_BURST_WINDOWS)),
            "min_interval_seconds": MIN_INTERVAL_SECONDS,
            "max_interval_seconds": MAX_INTERVAL_SECONDS,
            "max_tick_noise_seconds": MAX_TICK_NOISE_SECONDS,
        }

    def write_settings(
        self,
        *,
        enabled: bool | None = None,
        default_interval_seconds: int | None = None,
        tick_noise_seconds: int | None = None,
        burst_windows: list[dict[str, int | str]] | None = None,
    ) -> dict[str, Any]:
        """Persist any subset of settings; unspecified keys keep their value."""

        if enabled is not None:
            self._store.set_app_setting(SETTING_ENABLED, "1" if enabled else "0")
        if default_interval_seconds is not None:
            clamped = max(
                MIN_INTERVAL_SECONDS,
                min(MAX_INTERVAL_SECONDS, default_interval_seconds),
            )
            self._store.set_app_setting(SETTING_INTERVAL, str(clamped))
        if tick_noise_seconds is not None:
            clamped_noise = max(0, min(MAX_TICK_NOISE_SECONDS, tick_noise_seconds))
            self._store.set_app_setting(SETTING_TICK_NOISE, str(clamped_noise))
        if burst_windows is not None:
            sanitized = _sanitize_burst_windows(burst_windows)
            self._store.set_app_setting(
                SETTING_BURST_WINDOWS, json.dumps(sanitized)
            )
        return self.read_settings()

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        LOGGER.info("Scheduler loop started")
        # Tiny startup delay so the FastAPI lifespan finishes before we
        # begin hitting tennis.paris.fr — avoids a flurry of requests
        # while the catalog warmer is still spinning up.
        if self._shutdown.wait(timeout=5):
            return
        while not self._shutdown.is_set():
            settings = self.read_settings()
            try:
                if settings["enabled"]:
                    self._run_tick(forced=False)
                else:
                    LOGGER.debug("Scheduler disabled — skipping tick")
            except Exception as error:  # noqa: BLE001
                # Never let the loop die — log and keep going on the next tick.
                LOGGER.exception("Scheduler tick crashed: %s", error)
            sleep_seconds = self._compute_sleep(settings)
            if self._shutdown.wait(timeout=sleep_seconds):
                return
        LOGGER.info("Scheduler loop exiting")

    def _compute_sleep(self, settings: dict[str, Any]) -> float:
        """Return how long to sleep before the next tick, honouring burst windows.

        We add a uniform ±``tick_noise_seconds`` jitter so the loop never
        looks like a perfectly periodic source — easier on the upstream
        rate-limiter and harder to fingerprint.  Floor of 1 second so a
        large negative jitter never produces a zero or negative sleep.
        """

        now = self._now()
        base: float = float(settings["default_interval_seconds"])
        for window in settings["burst_windows"]:
            if _is_within_burst_window(now, window):
                base = float(window["interval_seconds"])
                break
        noise_amplitude = float(settings.get("tick_noise_seconds") or 0)
        if noise_amplitude > 0:
            base += random.uniform(-noise_amplitude, noise_amplitude)
        return max(1.0, base)

    def _now(self) -> dt.datetime:
        """Localized 'now' so burst-window comparisons match the operator's wall clock."""

        try:
            tz = ZoneInfo(self._timezone_name)
        except ZoneInfoNotFoundError:
            LOGGER.warning(
                "Unknown scheduler timezone '%s' — falling back to UTC",
                self._timezone_name,
            )
            tz = dt.timezone.utc
        return dt.datetime.now(tz)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def _run_tick(self, *, forced: bool) -> dict[str, Any]:
        """Snapshot active searches, attempt bookings, and persist the summary."""

        # Serialize ticks so a force-run from the admin UI cannot collide
        # with the loop, and back-to-back loop ticks cannot overlap.
        if not self._tick_lock.acquire(blocking=False):
            LOGGER.warning(
                "Scheduler tick already in progress — skipping this iteration"
            )
            return {"skipped": True, "reason": "tick already in progress"}
        run_id: int | None = None
        try:
            started_at = self._now().isoformat(timespec="seconds")
            run_id = self._store.insert_scheduler_run(started_at=started_at)
            summary = self._tick_body(forced=forced)
            return summary
        finally:
            try:
                if run_id is not None:
                    finished_at = self._now().isoformat(timespec="seconds")
                    self._store.finish_scheduler_run(
                        run_id=run_id,
                        finished_at=finished_at,
                        summary_json=json.dumps(summary, default=str),
                    )
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("Failed to persist scheduler run %s: %s", run_id, error)
            self._tick_lock.release()

    def _tick_body(self, *, forced: bool) -> dict[str, Any]:
        """The actual per-tick work — split out to keep _run_tick small."""

        searches = self._store.list_active_saved_searches()
        users_seen: set[int] = set()
        per_user: dict[int, list[SavedSearch]] = {}
        for search in searches:
            per_user.setdefault(search.user_id, []).append(search)
            users_seen.add(search.user_id)

        # Cache one user lookup per id; the scheduler can run thousands of
        # times without touching disk for unchanged user rows.
        users_by_id = {
            user_id: self._store.get_user(user_id) for user_id in users_seen
        }

        attempts: list[dict[str, Any]] = []
        bookings_succeeded = 0
        users_skipped_pending = 0
        for user_id, user_searches in per_user.items():
            user = users_by_id.get(user_id)
            if user is None or not user.is_enabled:
                LOGGER.info(
                    "Scheduler skipping user %s (missing or disabled)", user_id
                )
                continue
            outcome = self._process_user(user=user, searches=user_searches)
            attempts.append({"user_id": user_id, **outcome})
            if outcome.get("skipped_pending"):
                users_skipped_pending += 1
            bookings_succeeded += outcome.get("booked_count", 0)

        return {
            "forced": forced,
            "active_searches": len(searches),
            "users_evaluated": len(per_user),
            "bookings_succeeded": bookings_succeeded,
            "users_skipped_pending": users_skipped_pending,
            "per_user": attempts,
        }

    def _process_user(
        self, *, user: Any, searches: list[SavedSearch]
    ) -> dict[str, Any]:
        """Run the anonymous probe + book attempt for one user."""

        timezone_name = self._timezone_name
        attempt_at = self._now().isoformat(timespec="seconds")
        # Step 1: anonymous availability probe per saved search.  A search
        # with no slot today is left untouched (no failure stamp) so its
        # failure_count only grows on real booking errors.
        candidates: list[tuple[SavedSearch, str]] = []
        anonymous_session = self._session_manager.get_anonymous_session()
        for search in searches:
            try:
                target_date = _resolve_next_weekday_date_iso(
                    weekday=search.weekday, timezone_name=timezone_name
                )
            except ValueError as error:
                LOGGER.warning(
                    "Skipping search %s with invalid weekday: %s",
                    search.id,
                    error,
                )
                continue
            if (
                search.last_target_date == target_date
                and search.last_success_at
            ):
                # Already booked this date — nothing to do until the next
                # weekly window opens.  Won't normally hit this path
                # because we auto-deactivate on success, but the guard
                # keeps the scheduler honest if the admin re-enables a
                # search before the date passes.
                continue
            try:
                slots_found = self._anonymous_probe(
                    session=anonymous_session,
                    search=search,
                    target_date=target_date,
                )
            except ParisTennisError as error:
                LOGGER.warning(
                    "Anonymous probe failed for search %s: %s", search.id, error
                )
                continue
            if slots_found:
                candidates.append((search, target_date))

        if not candidates:
            return {"checked": len(searches), "candidates": 0}

        # Step 2: a candidate exists.  Confirm the user has no pending
        # reservation (one-reservation-per-user constraint) before we try
        # to book.  If they do, skip the user entirely this tick.
        try:
            user_session = self._session_manager.get_session(
                user_id=user.id,
                paris_username=user.paris_username,
                paris_password=user.paris_password,
            )
            pending = user_session.run(
                lambda client: client.get_current_reservation()
            )
        except Exception as error:  # noqa: BLE001
            LOGGER.warning(
                "Could not load pending reservation for user %s: %s",
                user.id,
                error,
            )
            return {"checked": len(searches), "candidates": len(candidates),
                    "error": str(error)}
        if pending.has_active_reservation:
            return {
                "checked": len(searches),
                "candidates": len(candidates),
                "skipped_pending": True,
            }

        # Step 3: actually book the first candidate.  Booking another
        # search after the first success would violate the one-reservation
        # constraint, so we stop after one success per user per tick.
        booked_count = 0
        attempted: list[dict[str, Any]] = []
        for search, target_date in candidates:
            outcome = self._book_one(
                user_session=user_session,
                search=search,
                target_date=target_date,
                attempt_at=attempt_at,
            )
            attempted.append(outcome)
            if outcome["success"]:
                booked_count += 1
                break
        return {
            "checked": len(searches),
            "candidates": len(candidates),
            "booked_count": booked_count,
            "attempts": attempted,
        }

    def _anonymous_probe(
        self,
        *,
        session: Any,
        search: SavedSearch,
        target_date: str,
    ) -> bool:
        """Return True when the anonymous search returns at least one slot."""

        def _probe(client: Any) -> bool:
            for venue_name in search.venue_names:
                try:
                    result = client.search_slots(
                        SearchRequest(
                            venue_name=venue_name,
                            date_iso=target_date,
                            hour_start=search.hour_start,
                            hour_end=search.hour_end,
                            surface_ids=tuple(),
                            in_out_codes=search.in_out_codes,
                        )
                    )
                except ParisTennisError as error:
                    LOGGER.debug(
                        "Anonymous search miss for %s @ %s: %s",
                        search.id,
                        venue_name,
                        error,
                    )
                    continue
                if result.slots:
                    return True
            return False

        return bool(session.run(_probe))

    def _book_one(
        self,
        *,
        user_session: Any,
        search: SavedSearch,
        target_date: str,
        attempt_at: str,
    ) -> dict[str, Any]:
        """Run the authenticated booking flow for one search, then bookkeep."""

        # Resolve the per-user catalog once for parity with the manual
        # "Book now" path (broaden empty surface filter to catalog-all).
        catalog = user_session.get_catalog_cached()
        all_surface_ids = (
            tuple(catalog.surface_options.keys()) if catalog is not None else tuple()
        )
        all_in_out_codes = (
            tuple(catalog.in_out_options.keys()) if catalog is not None else tuple()
        )
        effective_in_out_codes = search.in_out_codes or all_in_out_codes

        def _book(client: Any) -> tuple[str, Any]:
            chosen_venue = ""
            chosen_result = None
            for venue_name in search.venue_names:
                result = client.search_slots(
                    SearchRequest(
                        venue_name=venue_name,
                        date_iso=target_date,
                        hour_start=search.hour_start,
                        hour_end=search.hour_end,
                        surface_ids=all_surface_ids,
                        in_out_codes=effective_in_out_codes,
                    )
                )
                if result.slots:
                    chosen_venue = venue_name
                    chosen_result = result
                    break
            if chosen_result is None:
                raise ParisTennisError(
                    "Slot disappeared between probe and book attempt."
                )
            if not chosen_result.captcha_request_id:
                raise ParisTennisError("Result missing captcha_request_id.")
            slot = chosen_result.slots[0]
            client.book_slot(
                slot=slot, captcha_request_id=chosen_result.captcha_request_id
            )
            reservation = client.get_current_reservation()
            if not reservation.has_active_reservation:
                raise ParisTennisError(
                    "Booking flow finished but no active reservation detected."
                )
            return chosen_venue, slot

        try:
            venue_name, slot = user_session.run(_book)
        except ParisTennisError as error:
            new_failure_count = search.failure_count + 1
            deactivate = new_failure_count >= MAX_FAILURES_BEFORE_PAUSE
            self._store.record_search_attempt(
                search_id=search.id,
                target_date=target_date,
                success=False,
                attempt_at=attempt_at,
                deactivate=deactivate,
            )
            LOGGER.warning(
                "Scheduler booking failed for search %s (failures=%d, deactivated=%s): %s",
                search.id,
                new_failure_count,
                deactivate,
                error,
            )
            return {
                "search_id": search.id,
                "success": False,
                "deactivated": deactivate,
                "error": str(error),
            }
        except Exception as error:  # noqa: BLE001
            # Unexpected (Playwright crash etc.) — count as failure but log loud.
            new_failure_count = search.failure_count + 1
            deactivate = new_failure_count >= MAX_FAILURES_BEFORE_PAUSE
            self._store.record_search_attempt(
                search_id=search.id,
                target_date=target_date,
                success=False,
                attempt_at=attempt_at,
                deactivate=deactivate,
            )
            LOGGER.exception(
                "Scheduler unexpected error for search %s", search.id
            )
            return {
                "search_id": search.id,
                "success": False,
                "deactivated": deactivate,
                "error": str(error),
            }

        # Persist booking_history + flip search to inactive (decision 2a).
        self._store.add_booking_record(
            user_id=search.user_id,
            search_id=search.id,
            venue_name=venue_name,
            slot=slot,
        )
        self._store.record_search_attempt(
            search_id=search.id,
            target_date=target_date,
            success=True,
            attempt_at=attempt_at,
            deactivate=True,
        )
        LOGGER.info(
            "Scheduler booked search %s @ %s for user %s (slot=%s→%s)",
            search.id,
            venue_name,
            search.user_id,
            slot.date_deb,
            slot.date_fin,
        )
        return {
            "search_id": search.id,
            "success": True,
            "deactivated": True,
            "venue": venue_name,
            "slot": asdict(slot),
        }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(raw: str | None, *, default: int, lower: int, upper: int) -> int:
    if raw is None or not raw.strip().lstrip("-").isdigit():
        return default
    return max(lower, min(upper, int(raw)))


def _parse_burst_windows(raw: str | None) -> list[dict[str, int | str]]:
    """Tolerant JSON parse with sanitized output shape."""

    if not raw:
        return list(DEFAULT_BURST_WINDOWS)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("Invalid burst_windows JSON in app_settings — ignoring")
        return list(DEFAULT_BURST_WINDOWS)
    if not isinstance(parsed, list):
        return list(DEFAULT_BURST_WINDOWS)
    return _sanitize_burst_windows(parsed)


def _sanitize_burst_windows(
    raw: list[Any],
) -> list[dict[str, int | str]]:
    """Coerce admin-supplied burst-window dicts into a stable shape."""

    cleaned: list[dict[str, int | str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        time_str = str(entry.get("time", "")).strip()
        if not _is_valid_hhmm(time_str):
            continue
        plus_minus = _coerce_int(
            entry.get("plus_minus_minutes"), default=5, lower=0, upper=120
        )
        interval = _coerce_int(
            entry.get("interval_seconds"),
            default=DEFAULT_INTERVAL_SECONDS,
            lower=MIN_INTERVAL_SECONDS,
            upper=MAX_INTERVAL_SECONDS,
        )
        cleaned.append(
            {
                "time": time_str,
                "plus_minus_minutes": plus_minus,
                "interval_seconds": interval,
            }
        )
    return cleaned


def _coerce_int(value: Any, *, default: int, lower: int, upper: int) -> int:
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, as_int))


def _is_valid_hhmm(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    if not (parts[0].isdigit() and parts[1].isdigit()):
        return False
    hour, minute = int(parts[0]), int(parts[1])
    return 0 <= hour < 24 and 0 <= minute < 60


def _is_within_burst_window(
    now: dt.datetime, window: dict[str, int | str]
) -> bool:
    hour, minute = map(int, str(window["time"]).split(":"))
    center = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = abs((now - center).total_seconds())
    half_width = int(window["plus_minus_minutes"]) * 60
    return delta <= half_width


_WEEKDAY_VALUES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _resolve_next_weekday_date_iso(*, weekday: str, timezone_name: str) -> str:
    """Mirror the API helper so the scheduler resolves the same target date."""

    weekday_lower = weekday.strip().lower()
    if weekday_lower not in _WEEKDAY_VALUES:
        raise ValueError(f"Unknown weekday '{weekday}'.")
    day_index = _WEEKDAY_VALUES.index(weekday_lower)
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = dt.timezone.utc
    today = dt.datetime.now(tz).date()
    days_until_target = (day_index - today.weekday()) % 7
    if days_until_target == 0:
        days_until_target = 7
    return (today + dt.timedelta(days=days_until_target)).strftime("%d/%m/%Y")


# Surface for tests that want to advance a single tick without touching
# the loop directly.  Exposed under a stable name so external callers do
# not depend on the private method.
ManualTickFn = Callable[[], dict[str, Any]]


# Re-export so module-level imports stay tidy in callers.
__all__ = [
    "SchedulerService",
    "SETTING_ENABLED",
    "SETTING_INTERVAL",
    "SETTING_BURST_WINDOWS",
    "DEFAULT_INTERVAL_SECONDS",
    "MAX_FAILURES_BEFORE_PAUSE",
]


# `time` is used implicitly by tests that monkeypatch sleep helpers; keep
# the import alive for future use without lint noise.
_ = time
