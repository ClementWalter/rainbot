"""Unit tests for the webapp SQLite persistence layer."""

from __future__ import annotations

from pathlib import Path

from paris_tennis_api.models import SlotOffer
from paris_tennis_api.webapp.store import WebAppStore


def _build_store(tmp_path: Path) -> WebAppStore:
    """Create one isolated store per test to keep data independent and deterministic."""

    store = WebAppStore(tmp_path / "webapp.sqlite3")
    store.initialize()
    return store


def test_store_authenticates_only_allowlisted_enabled_user(tmp_path: Path) -> None:
    """Credentials should authenticate only when user exists in the allow-list."""

    store = _build_store(tmp_path)
    store.create_user(
        display_name="Alice",
        paris_username="alice@example.com",
        paris_password="top-secret",
        is_admin=True,
    )
    loaded = store.get_user_by_credentials(
        paris_username="alice@example.com",
        paris_password="top-secret",
    )
    assert (loaded is not None, loaded.display_name, loaded.is_admin) == (
        True,
        "Alice",
        True,
    )


def test_store_toggle_saved_search_changes_active_state(tmp_path: Path) -> None:
    """Saved search toggles should flip active flag for alarm-like control."""

    store = _build_store(tmp_path)
    user = store.create_user(
        display_name="Bob",
        paris_username="bob@example.com",
        paris_password="pwd",
        is_admin=False,
    )
    search = store.create_saved_search(
        user_id=user.id,
        label="Morning",
        venue_name="Alain Mimoun",
        date_iso="12/04/2026",
        hour_start=8,
        hour_end=10,
        surface_ids=("1324",),
        in_out_codes=("V",),
        slot_index=1,
    )
    toggled = store.toggle_saved_search(user_id=user.id, search_id=search.id)
    assert toggled.is_active is False


def test_store_records_booking_history_from_slot_offer(tmp_path: Path) -> None:
    """Booking history should persist slot details for the user timeline page."""

    store = _build_store(tmp_path)
    user = store.create_user(
        display_name="Carla",
        paris_username="carla@example.com",
        paris_password="pwd",
        is_admin=False,
    )
    search = store.create_saved_search(
        user_id=user.id,
        label="Evening",
        venue_name="Mimoun",
        date_iso="12/04/2026",
        hour_start=18,
        hour_end=20,
        surface_ids=("1324",),
        in_out_codes=("V",),
        slot_index=1,
    )
    store.add_booking_record(
        user_id=user.id,
        search_id=search.id,
        venue_name="Mimoun",
        slot=SlotOffer(
            equipment_id="eq-1",
            court_id="court-1",
            date_deb="2026/04/12 18:00:00",
            date_fin="2026/04/12 19:00:00",
            price_eur="12",
            price_label="Tarif plein",
        ),
    )
    records = store.list_booking_history(user_id=user.id)
    assert records[0].equipment_id == "eq-1"
