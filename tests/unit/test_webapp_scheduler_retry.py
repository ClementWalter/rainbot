"""Unit tests for the scheduler retry when the auth search races against a probe."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from paris_tennis_api.models import SearchResult, SlotOffer
from paris_tennis_api.webapp.scheduler import SchedulerService
from paris_tennis_api.webapp.store import SavedSearch


def _saved_search() -> SavedSearch:
    """Build a SavedSearch fixture aimed at one venue for predictable retry loops."""

    return SavedSearch(
        id=42,
        user_id=7,
        label="08h Alain Mimoun",
        venue_names=("Alain Mimoun",),
        court_ids=(),
        weekday="monday",
        hour_start=8,
        hour_end=9,
        in_out_codes=("V",),
        slot_index=0,
        is_active=True,
        created_at="2026-04-23T07:00:00",
        updated_at="2026-04-23T07:00:00",
    )


def _slot() -> SlotOffer:
    """Slot payload returned once the auth search recovers."""

    return SlotOffer(
        equipment_id="eq",
        court_id="court",
        date_deb="2026/04/27 08:00:00",
        date_fin="2026/04/27 09:00:00",
        price_eur="12",
        price_label="Tarif plein",
    )


class _FakeUserSession:
    """UserSession stub that executes the callable on the caller's thread."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def get_catalog_cached(self) -> None:
        # The scheduler tolerates a None catalog by falling back to empty filters.
        return None

    def run(self, fn):
        return fn(self._client)


class _ScriptedClient:
    """Client stub whose search_slots returns a scripted sequence of results."""

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def search_slots(self, _request) -> SearchResult:
        self.calls += 1
        if self._results:
            return self._results.pop(0)
        return SearchResult(slots=(), captcha_request_id="")

    def book_slot(self, *, slot, captcha_request_id) -> None:
        _ = slot, captcha_request_id

    def get_current_reservation(self):
        # has_active_reservation=True so _book_one returns the happy-path branch.
        from paris_tennis_api.models import ReservationSummary

        return ReservationSummary(
            has_active_reservation=True, cancellation_token="", raw_text="ok"
        )


class _FakeStore:
    """Store stub capturing the calls the scheduler makes on booking outcomes."""

    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self.bookings: list[dict[str, Any]] = []

    def record_search_attempt(self, **kwargs) -> None:
        self.attempts.append(kwargs)

    def add_booking_record(self, **kwargs) -> None:
        self.bookings.append(kwargs)


def _service(store: _FakeStore) -> SchedulerService:
    """Build a SchedulerService with just enough wiring for _book_one under test."""

    return SchedulerService(
        store=store,  # type: ignore[arg-type]
        session_manager=None,  # type: ignore[arg-type]
        timezone_name="Europe/Paris",
    )


def test_book_one_recovers_when_auth_search_returns_slot_on_retry(monkeypatch) -> None:
    """Scheduler must retry the auth search and recover when the slot reappears."""

    monkeypatch.setattr("paris_tennis_api.webapp.scheduler.time.sleep", lambda _s: None)
    store = _FakeStore()
    service = _service(store)
    client = _ScriptedClient(
        [
            SearchResult(slots=(), captcha_request_id=""),
            SearchResult(slots=(_slot(),), captcha_request_id="captcha-id"),
        ]
    )
    outcome = service._book_one(
        user_session=_FakeUserSession(client),
        search=_saved_search(),
        target_date="2026-04-27",
        attempt_at="2026-04-23T08:00:00+02:00",
    )
    assert (outcome["success"], client.calls) == (True, 2)


def test_book_one_raises_with_pass_count_when_all_retries_empty(monkeypatch) -> None:
    """After exhausting retries, the error message should record the pass count."""

    monkeypatch.setattr("paris_tennis_api.webapp.scheduler.time.sleep", lambda _s: None)
    store = _FakeStore()
    service = _service(store)
    client = _ScriptedClient([])  # all empty
    outcome = service._book_one(
        user_session=_FakeUserSession(client),
        search=_saved_search(),
        target_date="2026-04-27",
        attempt_at="2026-04-23T08:00:00+02:00",
    )
    assert (outcome["success"], client.calls) == (False, 3)
    assert "auth_passes=3" in outcome["error"]


def test_book_one_stops_retrying_after_first_hit(monkeypatch) -> None:
    """Once a venue returns slots, the retry loop must exit immediately."""

    monkeypatch.setattr("paris_tennis_api.webapp.scheduler.time.sleep", lambda _s: None)
    store = _FakeStore()
    service = _service(store)
    client = _ScriptedClient(
        [SearchResult(slots=(_slot(),), captcha_request_id="captcha-id")]
    )
    outcome = service._book_one(
        user_session=_FakeUserSession(client),
        search=_saved_search(),
        target_date="2026-04-27",
        attempt_at="2026-04-23T08:00:00+02:00",
    )
    # Only one call: first pass succeeded on the first (and only) venue.
    assert (outcome["success"], client.calls) == (True, 1)


def test_book_one_reports_all_venues_in_error_message(monkeypatch) -> None:
    """Post-mortems need the searched venues listed when the race is lost."""

    monkeypatch.setattr("paris_tennis_api.webapp.scheduler.time.sleep", lambda _s: None)
    store = _FakeStore()
    service = _service(store)
    client = _ScriptedClient([])
    search = replace(
        _saved_search(), venue_names=("Alain Mimoun", "Jandelle", "Elisabeth")
    )
    outcome = service._book_one(
        user_session=_FakeUserSession(client),
        search=search,
        target_date="2026-04-27",
        attempt_at="2026-04-23T08:00:00+02:00",
    )
    assert outcome["success"] is False
    # Each retry pass iterates all three venues before sleeping.
    assert client.calls == 9
    assert "Alain Mimoun" in outcome["error"]
    assert "Elisabeth" in outcome["error"]
