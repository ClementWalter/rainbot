"""Additional unit tests for store branches not covered by the core happy-path suite."""

from __future__ import annotations

from pathlib import Path

from paris_tennis_api.webapp.store import WebAppStore


def _build_store(tmp_path: Path) -> WebAppStore:
    """Build one initialized sqlite store bound to the current test temp directory."""

    store = WebAppStore(tmp_path / "webapp.sqlite3")
    store.initialize()
    return store


def test_count_admin_users_only_counts_enabled_admins(tmp_path: Path) -> None:
    """Admin count should ignore disabled users to enforce last-active-admin safeguards."""

    store = _build_store(tmp_path)
    store.create_user(
        display_name="Admin A",
        paris_username="a@example.com",
        paris_password="secret",
        is_admin=True,
        is_enabled=True,
    )
    store.create_user(
        display_name="Admin B",
        paris_username="b@example.com",
        paris_password="secret",
        is_admin=True,
        is_enabled=False,
    )
    assert store.count_admin_users() == 1


def test_list_users_returns_rows_in_creation_order(tmp_path: Path) -> None:
    """Stable user ordering keeps admin pages deterministic and predictable."""

    store = _build_store(tmp_path)
    store.create_user(
        display_name="First",
        paris_username="first@example.com",
        paris_password="secret",
        is_admin=False,
    )
    store.create_user(
        display_name="Second",
        paris_username="second@example.com",
        paris_password="secret",
        is_admin=False,
    )
    users = store.list_users()
    assert users[0].display_name == "First"


def test_get_user_returns_none_for_unknown_id(tmp_path: Path) -> None:
    """Missing user ids should return None so route handlers can show explicit errors."""

    store = _build_store(tmp_path)
    assert store.get_user(9999) is None


def test_update_user_admin_returns_updated_user(tmp_path: Path) -> None:
    """Admin toggles should return fresh row state for immediate UI feedback."""

    store = _build_store(tmp_path)
    user = store.create_user(
        display_name="Role",
        paris_username="role@example.com",
        paris_password="secret",
        is_admin=False,
    )
    updated = store.update_user_admin(user_id=user.id, is_admin=True)
    assert updated.is_admin is True


def test_update_user_enabled_returns_updated_user(tmp_path: Path) -> None:
    """Enable/disable operations should return the final stored status."""

    store = _build_store(tmp_path)
    user = store.create_user(
        display_name="Enabled",
        paris_username="enabled@example.com",
        paris_password="secret",
        is_admin=False,
    )
    updated = store.update_user_enabled(user_id=user.id, is_enabled=False)
    assert updated.is_enabled is False
