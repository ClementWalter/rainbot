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


def test_main_requires_username() -> None:
    """Missing username should fail before the client factory is called."""

    exit_code = main(argv=["--password", "p", "list-courts"], env={})
    assert exit_code == 1


def test_main_requires_password() -> None:
    """Missing password should fail fast for all commands using authenticated session."""

    exit_code = main(argv=["--username", "u", "list-courts"], env={})
    assert exit_code == 1


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
