"""Unit tests for webapp helper functions with lightweight request stubs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from paris_tennis_api.webapp.main import _get_current_user, _pop_flash, _split_csv
from paris_tennis_api.webapp.store import WebAppStore


def _request_stub(store: WebAppStore, session: dict[str, object]):
    """Build a minimal request-like object exposing session and app.state.store."""

    return SimpleNamespace(
        session=session,
        app=SimpleNamespace(state=SimpleNamespace(store=store)),
    )


def _seed_store(tmp_path: Path) -> WebAppStore:
    """Create a temporary store used by helper tests that require user lookups."""

    store = WebAppStore(tmp_path / "helpers.sqlite3")
    store.initialize()
    return store


def test_split_csv_discards_empty_entries() -> None:
    """CSV parser should normalize whitespace and ignore empty tokens."""

    values = _split_csv(" A , ,B ,, C ")
    assert values == ("A", "B", "C")


def test_pop_flash_returns_none_for_non_dict_payload(tmp_path: Path) -> None:
    """Flash helper should ignore invalid payload types rather than crashing."""

    store = _seed_store(tmp_path)
    request = _request_stub(store, {"flash": "invalid"})
    assert _pop_flash(request) is None


def test_get_current_user_returns_none_for_non_integer_session_id(
    tmp_path: Path,
) -> None:
    """Session values that are not integers should be treated as anonymous."""

    store = _seed_store(tmp_path)
    request = _request_stub(store, {"user_id": "1"})
    assert _get_current_user(request) is None


def test_get_current_user_removes_session_for_missing_user(tmp_path: Path) -> None:
    """Invalid user ids should be removed from session to self-heal stale cookies."""

    store = _seed_store(tmp_path)
    request = _request_stub(store, {"user_id": 999})
    _get_current_user(request)
    assert "user_id" not in request.session


def test_get_current_user_removes_session_for_disabled_user(tmp_path: Path) -> None:
    """Disabled users should be logged out automatically for safety."""

    store = _seed_store(tmp_path)
    user = store.create_user(
        display_name="Disabled",
        paris_username="disabled@example.com",
        paris_password="secret",
        is_admin=True,
    )
    store.update_user_enabled(user_id=user.id, is_enabled=False)
    request = _request_stub(store, {"user_id": user.id})
    _get_current_user(request)
    assert "user_id" not in request.session
