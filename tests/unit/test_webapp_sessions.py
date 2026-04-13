"""Unit tests for the per-user persistent session + TTL catalog cache.

The session owns a dedicated worker thread so Playwright's sync API stays on
one thread for its entire lifetime.  These tests exercise the queue+Future
dispatch, catalog TTL caching, failure recovery, and clean shutdown using a
thread-safe fake client.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pytest

from paris_tennis_api.exceptions import BookingError
from paris_tennis_api.webapp.sessions import UserSession, UserSessionManager


@dataclass
class _CallCounters:
    """Counters used by the FakeClient to expose call-shape assertions."""

    enters: int = 0
    exits: int = 0
    logins: int = 0
    catalog_calls: int = 0
    client_threads: set[int] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_thread(self) -> None:
        with self.lock:
            self.client_threads.add(threading.get_ident())


@dataclass
class _FakeCatalog:
    """Tiny stand-in returned by the fake client to keep tests focused on caching."""

    label: str


class _FakeClient:
    """Context-manager-shaped fake whose login/catalog behavior is configurable."""

    def __init__(
        self,
        *,
        counters: _CallCounters,
        catalog_responses: list[object],
        login_error: Exception | None = None,
        **_: object,
    ) -> None:
        self._counters = counters
        self._catalog_responses = catalog_responses
        self._login_error = login_error

    def __enter__(self) -> "_FakeClient":
        with self._counters.lock:
            self._counters.enters += 1
        self._counters.record_thread()
        return self

    def __exit__(self, *_: object) -> None:
        with self._counters.lock:
            self._counters.exits += 1
        self._counters.record_thread()

    def login(self) -> None:
        with self._counters.lock:
            self._counters.logins += 1
        self._counters.record_thread()
        if self._login_error is not None:
            raise self._login_error

    def get_search_catalog(self, *, force_refresh: bool = False) -> object:
        _ = force_refresh
        with self._counters.lock:
            self._counters.catalog_calls += 1
        self._counters.record_thread()
        response = self._catalog_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _build_session(
    *,
    counters: _CallCounters,
    catalog_responses: list[object] | None = None,
    login_error: Exception | None = None,
    catalog_ttl_seconds: int = 600,
) -> UserSession:
    """Build a fake-backed session so tests stay isolated from Playwright."""

    catalog_payload = list(catalog_responses or [])

    def _factory(**kwargs: object) -> _FakeClient:
        return _FakeClient(
            counters=counters,
            catalog_responses=catalog_payload,
            login_error=login_error,
            **kwargs,
        )

    return UserSession(
        user_id=1,
        paris_username="user@example.com",
        paris_password="secret",
        client_factory=_factory,
        captcha_api_key="captcha",
        headless=True,
        catalog_ttl_seconds=catalog_ttl_seconds,
    )


def test_run_reuses_one_logged_in_client_across_calls() -> None:
    """The persistent client should be built once with login() called once."""

    counters = _CallCounters()
    session = _build_session(counters=counters)
    try:
        first = session.run(lambda client: client)
        second = session.run(lambda client: client)
    finally:
        session.close()
    assert (counters.enters, counters.logins, first is second) == (1, 1, True)


def test_run_executes_every_task_on_the_same_worker_thread() -> None:
    """All client interactions must happen on one thread for Playwright safety."""

    counters = _CallCounters()
    session = _build_session(counters=counters)
    try:
        task_threads: set[int] = set()

        def _capture(_client: object) -> int:
            thread_id = threading.get_ident()
            task_threads.add(thread_id)
            return thread_id

        session.run(_capture)
        session.run(_capture)
        session.run(_capture)
    finally:
        session.close()
    # enter + login + 3 tasks + __exit__ all from the same thread.
    assert len(task_threads) == 1 and len(counters.client_threads) == 1


def test_run_propagates_exceptions_from_callable() -> None:
    """Errors raised inside the callable should surface on the caller's thread."""

    counters = _CallCounters()
    session = _build_session(counters=counters)
    try:
        with pytest.raises(BookingError) as excinfo:
            session.run(lambda _client: (_ for _ in ()).throw(BookingError("boom")))
    finally:
        session.close()
    assert "boom" in str(excinfo.value)


def test_get_catalog_cached_serves_cached_value_within_ttl() -> None:
    """Within the TTL window the catalog should not be re-fetched from the client."""

    counters = _CallCounters()
    session = _build_session(
        counters=counters,
        catalog_responses=[_FakeCatalog("first")],
        catalog_ttl_seconds=600,
    )
    try:
        first = session.get_catalog_cached()
        second = session.get_catalog_cached()
    finally:
        session.close()
    assert (counters.catalog_calls, first is second) == (1, True)


def test_get_catalog_cached_returns_stale_on_refresh_failure() -> None:
    """When a refresh fails, the previously cached catalog must still be served."""

    counters = _CallCounters()
    session = _build_session(
        counters=counters,
        catalog_responses=[_FakeCatalog("good"), BookingError("upstream")],
        catalog_ttl_seconds=0,
    )
    try:
        first = session.get_catalog_cached()
        second = session.get_catalog_cached()
    finally:
        session.close()
    assert (counters.catalog_calls, first is second, isinstance(first, _FakeCatalog)) == (
        2,
        True,
        True,
    )


def test_get_catalog_cached_returns_none_when_first_fetch_fails() -> None:
    """The very first fetch failure has no stale value to fall back on."""

    counters = _CallCounters()
    session = _build_session(
        counters=counters, catalog_responses=[BookingError("first-time fail")]
    )
    try:
        value = session.get_catalog_cached()
    finally:
        session.close()
    assert value is None


def test_ensure_client_failure_allows_retry_with_fresh_login() -> None:
    """A login error must not wedge the session; a later call should retry cleanly."""

    counters = _CallCounters()

    # Rotate so the first attempt fails and the second succeeds on re-login.
    login_errors: list[Exception | None] = [BookingError("login broke"), None]
    catalog_payload = [_FakeCatalog("ok")]

    def _factory(**kwargs: object) -> _FakeClient:
        error = login_errors.pop(0)
        return _FakeClient(
            counters=counters,
            catalog_responses=catalog_payload,
            login_error=error,
            **kwargs,
        )

    session = UserSession(
        user_id=2,
        paris_username="user@example.com",
        paris_password="secret",
        client_factory=_factory,
        captcha_api_key="captcha",
        headless=True,
        catalog_ttl_seconds=60,
    )
    try:
        with pytest.raises(BookingError):
            session.run(lambda _client: None)
        value = session.get_catalog_cached()
    finally:
        session.close()
    assert (counters.logins, counters.enters, isinstance(value, _FakeCatalog)) == (
        2,
        2,
        True,
    )


def test_session_manager_returns_same_session_for_repeated_user_id() -> None:
    """Per-user session reuse is what makes the catalog cache effective."""

    counters = _CallCounters()

    def _factory(**kwargs: object) -> _FakeClient:
        return _FakeClient(counters=counters, catalog_responses=[], **kwargs)

    manager = UserSessionManager(
        client_factory=_factory,
        captcha_api_key="captcha",
        headless=True,
        catalog_ttl_seconds=60,
    )
    try:
        first = manager.get_session(
            user_id=42, paris_username="u@example.com", paris_password="p"
        )
        second = manager.get_session(
            user_id=42, paris_username="u@example.com", paris_password="p"
        )
    finally:
        manager.shutdown()
    assert first is second


def test_session_manager_shutdown_closes_every_active_session() -> None:
    """App shutdown must close every browser we kept open across requests."""

    counters = _CallCounters()

    def _factory(**kwargs: object) -> _FakeClient:
        return _FakeClient(
            counters=counters, catalog_responses=[_FakeCatalog("ok")], **kwargs
        )

    manager = UserSessionManager(
        client_factory=_factory,
        captcha_api_key="captcha",
        headless=True,
        catalog_ttl_seconds=60,
    )
    session = manager.get_session(
        user_id=1, paris_username="u@example.com", paris_password="p"
    )
    session.get_catalog_cached()
    manager.shutdown()
    assert (counters.exits, counters.enters) == (1, 1)


def test_session_manager_invalidate_drops_and_closes_one_session() -> None:
    """Per-user invalidation must close that user's browser without touching others."""

    counters = _CallCounters()

    def _factory(**kwargs: object) -> _FakeClient:
        return _FakeClient(
            counters=counters, catalog_responses=[_FakeCatalog("ok")], **kwargs
        )

    manager = UserSessionManager(
        client_factory=_factory,
        captcha_api_key="captcha",
        headless=True,
        catalog_ttl_seconds=60,
    )
    session = manager.get_session(
        user_id=7, paris_username="u@example.com", paris_password="p"
    )
    session.get_catalog_cached()
    manager.invalidate(7)
    rebuilt = manager.get_session(
        user_id=7, paris_username="u@example.com", paris_password="p"
    )
    try:
        assert (counters.exits, rebuilt is session) == (1, False)
    finally:
        manager.shutdown()


def test_run_raises_after_session_close() -> None:
    """Once closed, the session must refuse further tasks instead of hanging."""

    counters = _CallCounters()
    session = _build_session(counters=counters)
    session.close()
    with pytest.raises(RuntimeError):
        session.run(lambda _client: None)
