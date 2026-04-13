"""Tests for module-level `__main__` guards to cover script entrypoints."""

from __future__ import annotations

import runpy
import sys

import pytest


def _run_as_main(module_name: str) -> None:
    """Execute a submodule as if invoked via ``python -m`` without the runpy warning.

    ``runpy.run_module(..., run_name="__main__")`` emits a RuntimeWarning when the
    target module is already cached in ``sys.modules`` — other tests often import
    these modules to patch their symbols, so by the time we get here the cache
    is populated.  Popping the entry replicates the clean state ``python -m``
    would see and keeps the test quiet without suppressing real warnings.
    """

    sys.modules.pop(module_name, None)
    runpy.run_module(module_name, run_name="__main__")


def test_cli_module_main_guard_exits_with_validation_error(monkeypatch) -> None:
    """Running CLI module as script should execute `__main__` guard and exit cleanly."""

    class _FakeClient:
        def __init__(self, **_: object) -> None:
            return None

        def __enter__(self) -> "_FakeClient":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def login(self) -> None:
            return None

        def get_search_catalog(self):
            return type("Catalog", (), {"venues": {}})()

    monkeypatch.setattr("paris_tennis_api.client.ParisTennisClient", _FakeClient)
    monkeypatch.setattr(
        "sys.argv",
        ["paris-tennis", "--username", "u", "--password", "p", "list-courts"],
    )
    with pytest.raises(SystemExit) as exc:
        _run_as_main("paris_tennis_api.cli")
    assert exc.value.code == 0


def test_webapp_server_module_main_guard_exits_after_main(monkeypatch) -> None:
    """Running webapp server module as script should invoke main guard path."""

    monkeypatch.setattr("sys.argv", ["paris-tennis-webapp", "--host", "127.0.0.1"])
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    with pytest.raises(SystemExit) as exc:
        _run_as_main("paris_tennis_api.webapp.server")
    assert exc.value.code == 0
