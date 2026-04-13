"""Per-user persistent browser sessions + TTL catalog cache for the webapp.

The real Playwright client is expensive to build: launching Chromium and
running the full OAuth login takes many seconds.  Rendering `/searches` on
every GET used to pay that cost end-to-end.  This module keeps one logged-in
client per user across requests and caches the search catalog with a TTL so
the dashboard hot path is essentially free.

Threading model
---------------
Playwright's sync API anchors its greenlet dispatcher to whichever thread
first called ``sync_playwright().start()``.  Any later call from a different
thread raises ``greenlet.error: cannot switch to a different thread``.  FastAPI
executes sync endpoints on a threadpool, so request handlers land on
different threads unpredictably — a plain lock is not enough.

Each ``UserSession`` therefore owns a dedicated worker thread that creates
the Playwright client lazily and executes every operation.  Callers hand work
to the session as a callable-of-client and block on a ``Future``; the worker
pulls tasks from an inbox queue and runs them serially.  Because all browser
I/O happens on that single thread for the session's lifetime, Playwright
stays happy.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future
from contextlib import ExitStack
from queue import Queue
from typing import Any, Callable, TypeVar

from paris_tennis_api.models import SearchCatalog

LOGGER = logging.getLogger(__name__)

# The client factory signature is intentionally loose so production
# (`ParisTennisClient`) and the FakeParisClient used by tests both fit.
ClientFactory = Callable[..., Any]

T = TypeVar("T")

# Sentinel posted to the worker inbox to request shutdown.  Identity compare
# avoids accidental collisions with any legitimate task payload.
_SHUTDOWN_SENTINEL = object()


class UserSession:
    """One long-lived logged-in client driven by a dedicated worker thread.

    Use ``run(fn)`` to execute ``fn(client)`` on the session's thread; that is
    the *only* supported way to touch the client, because Playwright sync
    mode forbids cross-thread access.  The catalog is cached in-memory with a
    TTL to make dashboard renders free most of the time.
    """

    def __init__(
        self,
        *,
        user_id: int,
        paris_username: str,
        paris_password: str,
        client_factory: ClientFactory,
        captcha_api_key: str,
        headless: bool,
        catalog_ttl_seconds: int,
        requires_login: bool = True,
    ) -> None:
        self._user_id = user_id
        self._paris_username = paris_username
        self._paris_password = paris_password
        self._client_factory = client_factory
        self._captcha_api_key = captcha_api_key
        self._headless = headless
        self._catalog_ttl_seconds = catalog_ttl_seconds
        # Anonymous sessions skip the OAuth round-trip entirely; the search
        # endpoints work without auth and `client.login()` would 401 with
        # empty credentials.
        self._requires_login = requires_login

        # Catalog-cache mutations must be atomic; the lock also deduplicates
        # concurrent refreshers so a cold cache does not trigger N logins.
        self._catalog_lock = threading.Lock()
        self._catalog: SearchCatalog | None = None
        self._catalog_expires_at: float = 0.0

        # Inbox is unbounded because tasks are short-lived and worker-bound
        # serialization is already guaranteed by queue FIFO semantics.
        self._inbox: Queue = Queue()
        self._shutdown_started = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name=f"user-session-{user_id}",
            daemon=True,
        )
        self._worker.start()

    def run(self, fn: Callable[[Any], T]) -> T:
        """Run ``fn(client)`` on the session's thread and return its result.

        Dispatch is synchronous from the caller's perspective: we enqueue the
        task, wait on the ``Future``, and re-raise whatever the worker caught.
        This is the pinch-point that makes Playwright's sync API safe.
        """

        if self._shutdown_started:
            raise RuntimeError("UserSession has been shut down.")
        future: Future[T] = Future()
        self._inbox.put((fn, future))
        return future.result()

    def get_catalog_cached(self) -> SearchCatalog | None:
        """Return cached catalog, or refresh under lock, or stale on failure."""

        now = time.monotonic()
        # Fast path: serve from cache without touching the worker thread.
        with self._catalog_lock:
            if self._catalog is not None and now < self._catalog_expires_at:
                return self._catalog

        # Slow path: perform a single dispatched refresh; other concurrent
        # callers will queue on the lock and reuse the fresh value once set.
        with self._catalog_lock:
            if (
                self._catalog is not None
                and time.monotonic() < self._catalog_expires_at
            ):
                return self._catalog
            try:
                catalog = self.run(
                    lambda client: client.get_search_catalog(force_refresh=True)
                )
            except Exception as error:  # noqa: BLE001
                # Keep serving the stale copy on transient upstream failures
                # so the dashboard never goes blank because of one hiccup.
                LOGGER.warning(
                    "Catalog refresh failed for user %s: %s (serving stale=%s)",
                    self._user_id,
                    error,
                    self._catalog is not None,
                )
                return self._catalog
            self._catalog = catalog
            self._catalog_expires_at = time.monotonic() + self._catalog_ttl_seconds
            LOGGER.debug(
                "Catalog cached for user %s (ttl=%ss)",
                self._user_id,
                self._catalog_ttl_seconds,
            )
            return catalog

    def invalidate_catalog(self) -> None:
        """Forget the cached catalog so the next access refetches it."""

        with self._catalog_lock:
            self._catalog = None
            self._catalog_expires_at = 0.0

    def close(self, *, timeout: float = 30.0) -> None:
        """Signal the worker to shut down and join its thread."""

        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._inbox.put(_SHUTDOWN_SENTINEL)
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            LOGGER.warning(
                "User session %s worker did not exit within %ss",
                self._user_id,
                timeout,
            )

    # ------------------------------------------------------------------
    # Worker thread implementation
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Serve tasks from the inbox; own the Playwright client lifecycle."""

        stack = ExitStack()
        client: Any | None = None
        try:
            while True:
                task = self._inbox.get()
                if task is _SHUTDOWN_SENTINEL:
                    return
                fn, future = task
                if future.cancelled():
                    continue

                # Lazy construction keeps idle sessions from holding a browser
                # process.  Any failure here resets the stack so the next
                # caller retries cleanly instead of inheriting a dead context.
                if client is None:
                    try:
                        client = stack.enter_context(
                            self._client_factory(
                                email=self._paris_username,
                                password=self._paris_password,
                                captcha_api_key=self._captcha_api_key,
                                headless=self._headless,
                            )
                        )
                        if self._requires_login:
                            client.login()
                    except BaseException as error:  # noqa: BLE001
                        future.set_exception(error)
                        try:
                            stack.close()
                        except Exception:  # noqa: BLE001
                            LOGGER.warning(
                                "Failed to roll back stack after login error "
                                "for user %s",
                                self._user_id,
                            )
                        stack = ExitStack()
                        client = None
                        continue
                    LOGGER.info(
                        "Persistent browser session ready for user %s",
                        self._user_id,
                    )

                try:
                    value = fn(client)
                except BaseException as error:  # noqa: BLE001
                    future.set_exception(error)
                else:
                    future.set_result(value)
        finally:
            # Shutdown: drain the inbox with cancellation so any caller still
            # waiting sees a clear error, then close the browser on this same
            # thread (Playwright's requirement).
            self._drain_inbox_on_shutdown()
            try:
                stack.close()
            except Exception as error:  # noqa: BLE001
                LOGGER.warning(
                    "Error closing client for user %s: %s",
                    self._user_id,
                    error,
                )

    def _drain_inbox_on_shutdown(self) -> None:
        """Fail any queued tasks so callers don't deadlock after shutdown."""

        while True:
            try:
                leftover = self._inbox.get_nowait()
            except Exception:  # noqa: BLE001  # queue.Empty is the expected exit
                return
            if leftover is _SHUTDOWN_SENTINEL:
                continue
            _fn, future = leftover
            future.set_exception(
                RuntimeError("UserSession shut down before this task could run.")
            )


class UserSessionManager:
    """Registry of `UserSession` objects keyed by user id, plus shutdown."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory,
        captcha_api_key: str,
        headless: bool,
        catalog_ttl_seconds: int,
    ) -> None:
        self._client_factory = client_factory
        self._captcha_api_key = captcha_api_key
        self._headless = headless
        self._catalog_ttl_seconds = catalog_ttl_seconds
        self._sessions: dict[int, UserSession] = {}
        # One shared anonymous session powers the "check availability" path —
        # no credentials, single browser, reused across all users.
        self._anonymous_session: UserSession | None = None
        # Manager lock only guards the dict; per-session work runs on its own thread.
        self._lock = threading.Lock()

    def get_session(
        self,
        *,
        user_id: int,
        paris_username: str,
        paris_password: str,
    ) -> UserSession:
        """Return or lazily create the user's persistent session container."""

        with self._lock:
            session = self._sessions.get(user_id)
            if session is None:
                session = UserSession(
                    user_id=user_id,
                    paris_username=paris_username,
                    paris_password=paris_password,
                    client_factory=self._client_factory,
                    captcha_api_key=self._captcha_api_key,
                    headless=self._headless,
                    catalog_ttl_seconds=self._catalog_ttl_seconds,
                )
                self._sessions[user_id] = session
            return session

    def get_anonymous_session(self) -> UserSession:
        """Return the lazily-built anonymous session used for read-only checks."""

        with self._lock:
            if self._anonymous_session is None:
                self._anonymous_session = UserSession(
                    user_id=0,
                    paris_username="",
                    paris_password="",
                    client_factory=self._client_factory,
                    captcha_api_key=self._captcha_api_key,
                    headless=self._headless,
                    catalog_ttl_seconds=self._catalog_ttl_seconds,
                    requires_login=False,
                )
            return self._anonymous_session

    def invalidate(self, user_id: int) -> None:
        """Drop and close one session; a later request will rebuild it."""

        with self._lock:
            session = self._sessions.pop(user_id, None)
        if session is not None:
            session.close()

    def shutdown(self) -> None:
        """Close every persistent browser client during app shutdown."""

        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            anonymous, self._anonymous_session = self._anonymous_session, None
        for session in sessions:
            session.close()
        if anonymous is not None:
            anonymous.close()
