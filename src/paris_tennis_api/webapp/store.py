"""SQLite persistence layer for the local Paris Tennis web application."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from paris_tennis_api.models import SlotOffer


@dataclass(frozen=True, slots=True)
class AllowedUser:
    """User record kept in the allow-list table for app authentication."""

    id: int
    display_name: str
    paris_username: str
    paris_password: str
    is_admin: bool
    is_enabled: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class SavedSearch:
    """Saved search criteria used by users as on/off booking alarms."""

    id: int
    user_id: int
    label: str
    venue_name: str
    date_iso: str
    hour_start: int
    hour_end: int
    surface_ids: tuple[str, ...]
    in_out_codes: tuple[str, ...]
    slot_index: int
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class BookingRecord:
    """Immutable booking history entry captured after successful webapp bookings."""

    id: int
    user_id: int
    search_id: int
    venue_name: str
    court_id: str
    equipment_id: str
    date_deb: str
    date_fin: str
    price_eur: str
    price_label: str
    booked_at: str


class WebAppStore:
    """Repository-like wrapper around SQLite so handlers stay simple and explicit."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open short-lived connections so concurrent requests do not share cursors."""

        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create tables if needed so first run works without migration tooling."""

        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    paris_username TEXT NOT NULL UNIQUE,
                    paris_password TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0, 1)),
                    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK(is_enabled IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    label TEXT NOT NULL,
                    venue_name TEXT NOT NULL,
                    date_iso TEXT NOT NULL,
                    hour_start INTEGER NOT NULL,
                    hour_end INTEGER NOT NULL,
                    surface_ids TEXT NOT NULL,
                    in_out_codes TEXT NOT NULL,
                    slot_index INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS booking_history (
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
            connection.commit()

    def count_users(self) -> int:
        """Return total users to decide whether bootstrap admin setup is needed."""

        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        return int(row["total"])

    def count_admin_users(self) -> int:
        """Count enabled admins so the UI can avoid locking itself out."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM users WHERE is_admin = 1 AND is_enabled = 1"
            ).fetchone()
        return int(row["total"])

    def create_user(
        self,
        *,
        display_name: str,
        paris_username: str,
        paris_password: str,
        is_admin: bool,
        is_enabled: bool = True,
    ) -> AllowedUser:
        """Insert one allow-listed user with explicit admin flag."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(display_name, paris_username, paris_password, is_admin, is_enabled)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    display_name.strip(),
                    paris_username.strip(),
                    paris_password,
                    int(is_admin),
                    int(is_enabled),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._row_to_user(row)

    def list_users(self) -> tuple[AllowedUser, ...]:
        """Return all users for admin management screens."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return tuple(self._row_to_user(row) for row in rows)

    def get_user(self, user_id: int) -> AllowedUser | None:
        """Get one user by primary key for session resolution."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_credentials(
        self, *, paris_username: str, paris_password: str
    ) -> AllowedUser | None:
        """Authenticate against the local allow-list with clear credentials by design."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM users
                WHERE paris_username = ? AND paris_password = ? AND is_enabled = 1
                """,
                (paris_username.strip(), paris_password),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def update_user_admin(self, *, user_id: int, is_admin: bool) -> AllowedUser | None:
        """Flip admin role directly in storage so access checks are immediate."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?", (int(is_admin), user_id)
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def update_user_enabled(
        self, *, user_id: int, is_enabled: bool
    ) -> AllowedUser | None:
        """Enable or disable logins without deleting the account record."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET is_enabled = ? WHERE id = ?",
                (int(is_enabled), user_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._row_to_user(row) if row else None

    def create_saved_search(
        self,
        *,
        user_id: int,
        label: str,
        venue_name: str,
        date_iso: str,
        hour_start: int,
        hour_end: int,
        surface_ids: tuple[str, ...],
        in_out_codes: tuple[str, ...],
        slot_index: int,
    ) -> SavedSearch:
        """Create one saved-search alarm bound to a single user."""

        with self._connect() as connection:
            cursor = connection.execute(
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
                    slot_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    label.strip(),
                    venue_name.strip(),
                    date_iso.strip(),
                    hour_start,
                    hour_end,
                    self._serialize_collection(surface_ids),
                    self._serialize_collection(in_out_codes),
                    slot_index,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM saved_searches WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._row_to_saved_search(row)

    def list_saved_searches(self, *, user_id: int) -> tuple[SavedSearch, ...]:
        """List searches owned by one user for dashboard rendering."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM saved_searches
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return tuple(self._row_to_saved_search(row) for row in rows)

    def get_saved_search(self, *, user_id: int, search_id: int) -> SavedSearch | None:
        """Fetch one saved search while enforcing user ownership."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM saved_searches WHERE id = ? AND user_id = ?",
                (search_id, user_id),
            ).fetchone()
        return self._row_to_saved_search(row) if row else None

    def toggle_saved_search(
        self, *, user_id: int, search_id: int
    ) -> SavedSearch | None:
        """Toggle active flag atomically for alarm-like behavior in the UI."""

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE saved_searches
                SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (search_id, user_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM saved_searches WHERE id = ? AND user_id = ?",
                (search_id, user_id),
            ).fetchone()
        return self._row_to_saved_search(row) if row else None

    def delete_saved_search(self, *, user_id: int, search_id: int) -> None:
        """Delete a search when users no longer want that alarm definition."""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM saved_searches WHERE id = ? AND user_id = ?",
                (search_id, user_id),
            )
            connection.commit()

    def add_booking_record(
        self,
        *,
        user_id: int,
        search_id: int,
        venue_name: str,
        slot: SlotOffer,
    ) -> BookingRecord:
        """Persist booking history so users keep local auditability over actions."""

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO booking_history(
                    user_id,
                    search_id,
                    venue_name,
                    court_id,
                    equipment_id,
                    date_deb,
                    date_fin,
                    price_eur,
                    price_label
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    search_id,
                    venue_name,
                    slot.court_id,
                    slot.equipment_id,
                    slot.date_deb,
                    slot.date_fin,
                    slot.price_eur,
                    slot.price_label,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM booking_history WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._row_to_booking_record(row)

    def list_booking_history(self, *, user_id: int) -> tuple[BookingRecord, ...]:
        """List booking events created by this webapp only."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM booking_history
                WHERE user_id = ?
                ORDER BY booked_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return tuple(self._row_to_booking_record(row) for row in rows)

    @staticmethod
    def _serialize_collection(values: tuple[str, ...]) -> str:
        """Store tuples as JSON text to keep schema migration-free."""

        return json.dumps(list(values))

    @staticmethod
    def _deserialize_collection(payload: str) -> tuple[str, ...]:
        """Decode JSON list storage back to tuple representation used by models."""

        parsed = json.loads(payload)
        return tuple(str(item) for item in parsed)

    def _row_to_user(self, row: sqlite3.Row) -> AllowedUser:
        return AllowedUser(
            id=int(row["id"]),
            display_name=str(row["display_name"]),
            paris_username=str(row["paris_username"]),
            paris_password=str(row["paris_password"]),
            is_admin=bool(row["is_admin"]),
            is_enabled=bool(row["is_enabled"]),
            created_at=str(row["created_at"]),
        )

    def _row_to_saved_search(self, row: sqlite3.Row) -> SavedSearch:
        return SavedSearch(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            label=str(row["label"]),
            venue_name=str(row["venue_name"]),
            date_iso=str(row["date_iso"]),
            hour_start=int(row["hour_start"]),
            hour_end=int(row["hour_end"]),
            surface_ids=self._deserialize_collection(str(row["surface_ids"])),
            in_out_codes=self._deserialize_collection(str(row["in_out_codes"])),
            slot_index=int(row["slot_index"]),
            is_active=bool(row["is_active"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _row_to_booking_record(self, row: sqlite3.Row) -> BookingRecord:
        return BookingRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            search_id=int(row["search_id"]),
            venue_name=str(row["venue_name"]),
            court_id=str(row["court_id"]),
            equipment_id=str(row["equipment_id"]),
            date_deb=str(row["date_deb"]),
            date_fin=str(row["date_fin"]),
            price_eur=str(row["price_eur"]),
            price_label=str(row["price_label"]),
            booked_at=str(row["booked_at"]),
        )
