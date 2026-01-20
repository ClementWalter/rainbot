"""Tests for booking history export utilities."""

import csv
from datetime import datetime
from io import StringIO

from src.models.booking import Booking
from src.services.booking_history import (
    BOOKING_HISTORY_FIELDS,
    export_booking_history_csv,
)


def _make_booking(
    booking_id: str,
    date_value: datetime,
    time_start: str,
    time_end: str,
    facility_name: str = "Tennis Center",
    facility_address: str | None = "123 Court St",
    court_number: str = "1",
    partner_name: str | None = "Partner",
    partner_email: str | None = "partner@example.com",
    confirmation_id: str | None = "CONF-123",
) -> Booking:
    return Booking(
        id=booking_id,
        user_id="user-1",
        request_id="req-1",
        facility_name=facility_name,
        facility_code="FAC-1",
        court_number=court_number,
        date=date_value,
        time_start=time_start,
        time_end=time_end,
        partner_name=partner_name,
        partner_email=partner_email,
        confirmation_id=confirmation_id,
        facility_address=facility_address,
    )


def test_export_booking_history_csv_sorts_desc():
    bookings = [
        _make_booking("book-1", datetime(2025, 1, 20, 0, 0), "09:00", "10:00"),
        _make_booking("book-2", datetime(2025, 1, 22, 0, 0), "18:00", "19:00"),
        _make_booking("book-3", datetime(2025, 1, 20, 0, 0), "08:00", "09:00"),
    ]

    csv_text = export_booking_history_csv(bookings)
    reader = csv.DictReader(StringIO(csv_text))
    rows = list(reader)

    assert reader.fieldnames == BOOKING_HISTORY_FIELDS
    assert [row["date"] for row in rows] == [
        "2025-01-22",
        "2025-01-20",
        "2025-01-20",
    ]
    assert [row["time_start"] for row in rows] == ["18:00", "09:00", "08:00"]


def test_export_booking_history_csv_handles_empty_fields():
    booking = _make_booking(
        "book-1",
        datetime(2025, 1, 20, 0, 0),
        "09:00",
        "10:00",
        facility_address=None,
        partner_name=None,
        partner_email=None,
        confirmation_id=None,
    )

    csv_text = export_booking_history_csv([booking], sort_desc=False)
    reader = csv.DictReader(StringIO(csv_text))
    rows = list(reader)

    assert len(rows) == 1
    row = rows[0]
    assert row["facility_address"] == ""
    assert row["partner_name"] == ""
    assert row["partner_email"] == ""
    assert row["confirmation_id"] == ""
