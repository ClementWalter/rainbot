"""SQLite persistence layer for the local Paris Tennis web application."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from paris_tennis_api.models import SlotOffer

WEEKDAY_VALUES = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


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
    venue_names: tuple[str, ...]
    court_ids: tuple[str, ...]
    weekday: str
    hour_start: int
    hour_end: int
    in_out_codes: tuple[str, ...]
    slot_index: int
    is_active: bool
    created_at: str
    updated_at: str
    # Scheduler bookkeeping — populated by the background tick loop.
    last_attempt_at: str = ""
    last_success_at: str = ""
    last_target_date: str = ""
    failure_count: int = 0

    @property
    def venue_name(self) -> str:
        """Keep legacy accessors for routes/tests that still reference one venue string."""

        return self.venue_names[0] if self.venue_names else ""

    @property
    def date_iso(self) -> str:
        """Expose weekday via historical attribute name for compatibility with old templates."""

        return self.weekday

    @property
    def surface_ids(self) -> tuple[str, ...]:
        """Surface filters were removed from UI; keep stable empty tuple for compatibility."""

        return ()


@dataclass(frozen=True, slots=True)
class SchedulerRun:
    """One execution of the background scheduler tick.

    `summary` is JSON text — kept opaque at the store layer so the
    scheduler can evolve its payload shape without schema migrations.
    """

    id: int
    started_at: str
    finished_at: str
    summary_json: str


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
                    venue_name TEXT NOT NULL DEFAULT '',
                    date_iso TEXT NOT NULL DEFAULT '',
                    hour_start INTEGER NOT NULL,
                    hour_end INTEGER NOT NULL,
                    surface_ids TEXT NOT NULL DEFAULT '[]',
                    in_out_codes TEXT NOT NULL DEFAULT '[]',
                    slot_index INTEGER NOT NULL DEFAULT 1,
                    venue_names TEXT NOT NULL DEFAULT '[]',
                    court_ids TEXT NOT NULL DEFAULT '[]',
                    weekday TEXT NOT NULL DEFAULT 'monday',
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

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS scheduler_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '{}'
                );
                """)
            self._migrate_saved_searches_table(connection)
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
        hour_start: int,
        hour_end: int,
        venue_names: tuple[str, ...] | None = None,
        court_ids: tuple[str, ...] | None = None,
        weekday: str = "",
        in_out_codes: tuple[str, ...] | None = None,
        venue_name: str = "",
        date_iso: str = "",
        surface_ids: tuple[str, ...] | None = None,
        slot_index: int = 1,
    ) -> SavedSearch:
        """Create one saved-search alarm bound to a single user."""

        normalized_venue_names = venue_names or tuple()
        if not normalized_venue_names and venue_name.strip():
            normalized_venue_names = (venue_name.strip(),)
        normalized_court_ids = court_ids or tuple()
        normalized_weekday = weekday.strip().lower() if weekday.strip() else ""
        if not normalized_weekday:
            normalized_weekday = _weekday_from_date_iso(date_iso)
        normalized_in_out_codes = in_out_codes or tuple()
        normalized_slot_index = slot_index
        _ = surface_ids
        primary_venue = normalized_venue_names[0] if normalized_venue_names else ""
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
                    slot_index,
                    venue_names,
                    court_ids,
                    weekday
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    label.strip(),
                    primary_venue.strip(),
                    normalized_weekday,
                    hour_start,
                    hour_end,
                    self._serialize_collection(tuple()),
                    self._serialize_collection(normalized_in_out_codes),
                    normalized_slot_index,
                    self._serialize_collection(normalized_venue_names),
                    self._serialize_collection(normalized_court_ids),
                    normalized_weekday,
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

    def set_saved_search_active(
        self, *, user_id: int, search_id: int, is_active: bool
    ) -> SavedSearch | None:
        """Set active flag explicitly so radio-based controls map to deterministic state."""

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE saved_searches
                SET is_active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (int(is_active), search_id, user_id),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM saved_searches WHERE id = ? AND user_id = ?",
                (search_id, user_id),
            ).fetchone()
        return self._row_to_saved_search(row) if row else None

    def update_saved_search(
        self,
        *,
        user_id: int,
        search_id: int,
        label: str | None = None,
        venue_names: tuple[str, ...] | None = None,
        weekday: str | None = None,
        hour_start: int | None = None,
        hour_end: int | None = None,
        in_out_codes: tuple[str, ...] | None = None,
    ) -> "SavedSearch | None":
        """Patch any subset of editable fields, returning the updated row.

        Caller is responsible for validating values (venue/weekday/hours) —
        this method only assembles SQL.  Unspecified keys are left untouched.
        """

        assignments: dict[str, object] = {}
        if label is not None:
            assignments["label"] = label.strip()
        if venue_names is not None:
            assignments["venue_names"] = self._serialize_collection(venue_names)
            # Keep legacy `venue_name` column in sync so older parsers/tests
            # still find a primary venue without crashing.
            assignments["venue_name"] = venue_names[0] if venue_names else ""
        if weekday is not None:
            assignments["weekday"] = weekday
            assignments["date_iso"] = weekday  # legacy column kept in sync
        if hour_start is not None:
            assignments["hour_start"] = hour_start
        if hour_end is not None:
            assignments["hour_end"] = hour_end
        if in_out_codes is not None:
            assignments["in_out_codes"] = self._serialize_collection(in_out_codes)

        if not assignments:
            return self.get_saved_search(user_id=user_id, search_id=search_id)

        set_clause = ", ".join(f"{key} = ?" for key in assignments)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE saved_searches SET {set_clause}, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (*assignments.values(), search_id, user_id),
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
        columns = set(row.keys())
        if "venue_names" in columns:
            venue_names = self._deserialize_collection(str(row["venue_names"]))
        else:
            venue_names = tuple()
        if not venue_names:
            legacy_venue = str(row["venue_name"]) if "venue_name" in columns else ""
            if legacy_venue:
                venue_names = (legacy_venue,)

        if "court_ids" in columns:
            court_ids = self._deserialize_collection(str(row["court_ids"]))
        else:
            court_ids = tuple()

        weekday = str(row["weekday"]).strip().lower() if "weekday" in columns else ""
        if weekday not in WEEKDAY_VALUES:
            legacy_date = str(row["date_iso"]) if "date_iso" in columns else ""
            inferred_weekday = _try_weekday_from_legacy_date_iso(legacy_date)
            weekday = inferred_weekday or _weekday_from_date_iso(legacy_date)

        return SavedSearch(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            label=str(row["label"]),
            venue_names=venue_names,
            court_ids=court_ids,
            weekday=weekday,
            hour_start=int(row["hour_start"]),
            hour_end=int(row["hour_end"]),
            in_out_codes=self._deserialize_collection(str(row["in_out_codes"])),
            slot_index=int(row["slot_index"]),
            is_active=bool(row["is_active"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_attempt_at=str(row["last_attempt_at"]) if "last_attempt_at" in columns else "",
            last_success_at=str(row["last_success_at"]) if "last_success_at" in columns else "",
            last_target_date=str(row["last_target_date"]) if "last_target_date" in columns else "",
            failure_count=int(row["failure_count"]) if "failure_count" in columns else 0,
        )

    # ------------------------------------------------------------------
    # App settings (k/v) — used by the scheduler for runtime configuration
    # so admins can tune intervals without restarting the server.
    # ------------------------------------------------------------------

    def get_app_setting(self, key: str, default: str = "") -> str:
        """Read one setting value, returning ``default`` for unknown keys."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def set_app_setting(self, key: str, value: str) -> None:
        """Upsert one setting; ``updated_at`` is refreshed on every write."""

        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = CURRENT_TIMESTAMP",
                (key, value),
            )
            connection.commit()

    def list_app_settings(self) -> dict[str, str]:
        """Return all settings as a flat dict for the admin API."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM app_settings"
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    # ------------------------------------------------------------------
    # Scheduler runs — append-only log of background-tick outcomes.
    # ------------------------------------------------------------------

    def insert_scheduler_run(self, *, started_at: str) -> int:
        """Open a new tick row; the scheduler fills the summary on completion."""

        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO scheduler_runs(started_at) VALUES (?)",
                (started_at,),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def finish_scheduler_run(
        self, *, run_id: int, finished_at: str, summary_json: str
    ) -> None:
        """Stamp the tick row with its end time + serialized outcome summary."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE scheduler_runs SET finished_at = ?, summary = ? "
                "WHERE id = ?",
                (finished_at, summary_json, run_id),
            )
            connection.commit()

    def list_scheduler_runs(self, *, limit: int = 50) -> tuple[SchedulerRun, ...]:
        """Return the most recent tick entries for the admin log view."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scheduler_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(
            SchedulerRun(
                id=int(row["id"]),
                started_at=str(row["started_at"]),
                finished_at=str(row["finished_at"] or ""),
                summary_json=str(row["summary"] or "{}"),
            )
            for row in rows
        )

    # ------------------------------------------------------------------
    # Scheduler ↔ saved-search bookkeeping.
    # ------------------------------------------------------------------

    def list_active_saved_searches(self) -> tuple[SavedSearch, ...]:
        """All active searches across all users — input to the scheduler tick."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM saved_searches WHERE is_active = 1 "
                "ORDER BY user_id ASC, id ASC"
            ).fetchall()
        return tuple(self._row_to_saved_search(row) for row in rows)

    def record_search_attempt(
        self,
        *,
        search_id: int,
        target_date: str,
        success: bool,
        attempt_at: str,
        deactivate: bool,
    ) -> None:
        """Update bookkeeping after one tick attempted to act on a search.

        On success we reset failure_count and stamp success_at + the date we
        just booked.  On failure we increment failure_count.  The caller
        decides whether to flip is_active off via ``deactivate`` so the
        scheduler keeps both auto-deactivate-on-success (2a) and
        deactivate-after-N-failures policies in one place.
        """

        with self._connect() as connection:
            if success:
                connection.execute(
                    "UPDATE saved_searches SET last_attempt_at = ?, "
                    "last_success_at = ?, last_target_date = ?, "
                    "failure_count = 0, "
                    "is_active = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (
                        attempt_at,
                        attempt_at,
                        target_date,
                        0 if deactivate else 1,
                        search_id,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE saved_searches SET last_attempt_at = ?, "
                    "failure_count = failure_count + 1, "
                    "is_active = CASE WHEN ? THEN 0 ELSE is_active END, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (attempt_at, 1 if deactivate else 0, search_id),
                )
            connection.commit()

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

    def _migrate_saved_searches_table(self, connection: sqlite3.Connection) -> None:
        """Add new saved-search columns in place so existing local DBs remain usable."""

        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(saved_searches)").fetchall()
        }
        migrations = (
            ("venue_names", "ALTER TABLE saved_searches ADD COLUMN venue_names TEXT NOT NULL DEFAULT '[]'"),
            ("court_ids", "ALTER TABLE saved_searches ADD COLUMN court_ids TEXT NOT NULL DEFAULT '[]'"),
            ("weekday", "ALTER TABLE saved_searches ADD COLUMN weekday TEXT NOT NULL DEFAULT 'monday'"),
            # Scheduler bookkeeping — populated by the background tick loop.
            ("last_attempt_at", "ALTER TABLE saved_searches ADD COLUMN last_attempt_at TEXT NOT NULL DEFAULT ''"),
            ("last_success_at", "ALTER TABLE saved_searches ADD COLUMN last_success_at TEXT NOT NULL DEFAULT ''"),
            ("last_target_date", "ALTER TABLE saved_searches ADD COLUMN last_target_date TEXT NOT NULL DEFAULT ''"),
            ("failure_count", "ALTER TABLE saved_searches ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0"),
        )
        for column_name, sql in migrations:
            if column_name not in columns:
                connection.execute(sql)

        # Backfill old rows once so runtime booking can rely on the new fields.
        connection.execute(
            """
            UPDATE saved_searches
            SET venue_names = json_array(venue_name)
            WHERE venue_name != ''
              AND (venue_names = '[]' OR venue_names = '')
            """
        )
        # Slot index is no longer user-controlled; normalize legacy values to first slot.
        connection.execute(
            """
            UPDATE saved_searches
            SET slot_index = 1
            WHERE slot_index != 1
            """
        )
        rows = connection.execute(
            "SELECT id, date_iso, weekday FROM saved_searches"
        ).fetchall()
        for row in rows:
            inferred_weekday = _try_weekday_from_legacy_date_iso(str(row["date_iso"]))
            if inferred_weekday is None:
                continue
            current_weekday = str(row["weekday"]).strip().lower()
            if current_weekday not in WEEKDAY_VALUES or current_weekday == "monday":
                # Legacy rows added before weekday support were defaulted to Monday.
                # We restore the real weekday from the historical DD/MM/YYYY value.
                connection.execute(
                    """
                    UPDATE saved_searches
                    SET weekday = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (inferred_weekday, int(row["id"])),
                )


def _weekday_from_date_iso(value: str) -> str:
    """Infer weekday from legacy DD/MM/YYYY payloads to preserve old saved-search rows."""

    try:
        parsed = dt.datetime.strptime(value.strip(), "%d/%m/%Y")
    except ValueError:
        return "monday"
    return parsed.strftime("%A").lower()


def _try_weekday_from_legacy_date_iso(value: str) -> str | None:
    """Parse legacy DD/MM/YYYY date strings and return weekday, else None."""

    try:
        parsed = dt.datetime.strptime(value.strip(), "%d/%m/%Y")
    except ValueError:
        return None
    return parsed.strftime("%A").lower()
