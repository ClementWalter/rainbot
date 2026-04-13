"""Additional unit tests for store branches not covered by the core happy-path suite."""

from __future__ import annotations

import sqlite3
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


def test_initialize_backfills_weekday_from_legacy_date_iso(tmp_path: Path) -> None:
    """Legacy rows should preserve original weekday instead of defaulting to Monday."""

    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                paris_username TEXT NOT NULL UNIQUE,
                paris_password TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0, 1)),
                is_enabled INTEGER NOT NULL DEFAULT 1 CHECK(is_enabled IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                venue_name TEXT NOT NULL DEFAULT '',
                date_iso TEXT NOT NULL DEFAULT '',
                hour_start INTEGER NOT NULL,
                hour_end INTEGER NOT NULL,
                surface_ids TEXT NOT NULL DEFAULT '[]',
                in_out_codes TEXT NOT NULL DEFAULT '[]',
                slot_index INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE booking_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                search_id INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
                venue_name TEXT NOT NULL,
                court_id TEXT NOT NULL,
                equipment_id TEXT NOT NULL,
                date_deb TEXT NOT NULL,
                date_fin TEXT NOT NULL,
                price_eur TEXT NOT NULL,
                price_label TEXT NOT NULL,
                booked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        connection.execute(
            """
            INSERT INTO users(display_name, paris_username, paris_password, is_admin, is_enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Legacy User", "legacy@example.com", "secret", 0, 1),
        )
        connection.execute(
            """
            INSERT INTO saved_searches(
                user_id,
                label,
                venue_name,
                date_iso,
                hour_start,
                hour_end,
                surface_ids,
                in_out_codes,
                slot_index,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Legacy Sunday",
                "Alain Mimoun",
                "12/04/2026",
                8,
                10,
                "[]",
                '["V"]',
                3,
                1,
            ),
        )
        connection.commit()

    store = WebAppStore(database_path)
    store.initialize()
    migrated = store.list_saved_searches(user_id=1)[0]
    assert migrated.weekday == "sunday"
