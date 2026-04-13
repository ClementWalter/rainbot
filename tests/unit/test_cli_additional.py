"""Additional CLI tests for validation and error-path coverage."""

from __future__ import annotations

import argparse

from paris_tennis_api.cli import main
from paris_tennis_api.models import ReservationSummary, SearchCatalog, SearchResult


class _FakeClient:
    """Tiny fake client for commands that do not need real browser interactions."""

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def login(self) -> None:
        return None

    def get_search_catalog(self) -> SearchCatalog:
        return SearchCatalog(
            venues={},
            date_options=(),
            surface_options={},
            in_out_options={},
            min_hour=8,
            max_hour=22,
        )

    def search_slots(self, request) -> SearchResult:
        _ = request
        return SearchResult(slots=(), captcha_request_id="")

    def get_current_reservation(self) -> ReservationSummary:
        return ReservationSummary(
            has_active_reservation=False,
            cancellation_token="",
            raw_text="none",
        )

    def cancel_current_reservation(self) -> bool:
        return False

    def get_available_tickets(self):
        class _Tickets:
            tickets = ()

        return _Tickets()


def test_main_requires_username_for_authenticated_commands() -> None:
    """Missing username should fail for commands that hit the profile/booking API."""

    exit_code = main(argv=["--password", "p", "cancel"], env={})
    assert exit_code == 1


def test_main_requires_password_for_authenticated_commands() -> None:
    """Missing password should fail for commands that hit the profile/booking API."""

    exit_code = main(argv=["--username", "u", "cancel"], env={})
    assert exit_code == 1


def test_main_allows_anonymous_list_courts_without_credentials() -> None:
    """list-courts is a public read, so missing credentials must not block it."""

    fake = _FakeClient()
    exit_code = main(
        argv=["list-courts"],
        env={},
        client_factory=lambda **_: fake,
    )
    assert exit_code == 0


def test_main_allows_anonymous_search_slots_without_credentials() -> None:
    """search-slots is a public read, so missing credentials must not block it."""

    fake = _FakeClient()
    exit_code = main(
        argv=["search-slots", "--venue", "Alain Mimoun", "--date", "12/04/2026"],
        env={},
        client_factory=lambda **_: fake,
    )
    assert exit_code == 0


def test_main_does_not_call_login_for_anonymous_commands() -> None:
    """Anonymous commands must skip login() so they can run without credentials."""

    fake = _FakeClient()
    login_calls = {"count": 0}

    def _login() -> None:
        login_calls["count"] += 1

    fake.login = _login  # type: ignore[method-assign]
    main(argv=["list-courts"], env={}, client_factory=lambda **_: fake)
    assert login_calls["count"] == 0


def test_search_slots_login_flag_requires_credentials() -> None:
    """--login must flip the credential validator on for the otherwise-anonymous command."""

    exit_code = main(
        argv=[
            "search-slots",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
            "--login",
        ],
        env={},
    )
    assert exit_code == 1


def test_search_slots_login_flag_authenticates_before_searching() -> None:
    """--login must call client.login() before running the search."""

    fake = _FakeClient()
    login_calls = {"count": 0}

    def _login() -> None:
        login_calls["count"] += 1

    fake.login = _login  # type: ignore[method-assign]
    main(
        argv=[
            "--username",
            "u",
            "--password",
            "p",
            "search-slots",
            "--venue",
            "Alain Mimoun",
            "--date",
            "12/04/2026",
            "--login",
        ],
        env={},
        client_factory=lambda **_: fake,
    )
    assert login_calls["count"] == 1


def test_main_returns_error_for_unknown_command(monkeypatch) -> None:
    """Defensive fallback should keep unknown parser output from crashing the CLI."""

    namespace = argparse.Namespace(
        username="u",
        password="p",
        captcha_api_key="k",
        headless=True,
        verbose=False,
        command="unknown",
    )

    class _Parser:
        def parse_args(self, argv):
            _ = argv
            return namespace

    monkeypatch.setattr("paris_tennis_api.cli.build_parser", lambda env=None: _Parser())
    exit_code = main(argv=[], client_factory=lambda **kwargs: _FakeClient())
    assert exit_code == 1
