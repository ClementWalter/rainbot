"""Booking history export utilities."""

import csv
from datetime import date, datetime
from io import StringIO
from typing import Iterable

from src.models.booking import Booking
from src.models.booking_request import normalize_time

BOOKING_HISTORY_FIELDS = [
    "date",
    "time_start",
    "time_end",
    "facility_name",
    "facility_address",
    "court_number",
    "partner_name",
    "partner_email",
    "confirmation_id",
]


def _booking_sort_key(booking: Booking) -> tuple[str, str]:
    date_value = booking.date
    if isinstance(date_value, datetime):
        date_key = date_value.date().isoformat()
    elif isinstance(date_value, date):
        date_key = date_value.isoformat()
    else:
        date_key = str(date_value)

    time_key = normalize_time(booking.time_start or "") or "00:00"
    return (date_key, time_key)


def booking_to_history_row(booking: Booking) -> dict[str, str]:
    """Convert a Booking into a CSV-friendly row."""
    date_value = booking.date
    if isinstance(date_value, datetime):
        date_str = date_value.date().isoformat()
    elif isinstance(date_value, date):
        date_str = date_value.isoformat()
    else:
        date_str = str(date_value)

    return {
        "date": date_str,
        "time_start": booking.time_start or "",
        "time_end": booking.time_end or "",
        "facility_name": booking.facility_name or "",
        "facility_address": booking.facility_address or "",
        "court_number": booking.court_number or "",
        "partner_name": booking.partner_name or "",
        "partner_email": booking.partner_email or "",
        "confirmation_id": booking.confirmation_id or "",
    }


def export_booking_history_csv(
    bookings: Iterable[Booking],
    sort_desc: bool = True,
) -> str:
    """
    Export booking history as CSV.

    Args:
        bookings: Booking records to export.
        sort_desc: Sort by most recent date/time first when True.

    Returns:
        CSV string with headers and rows.

    """
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=BOOKING_HISTORY_FIELDS,
        lineterminator="\n",
    )
    writer.writeheader()

    sorted_bookings = sorted(bookings, key=_booking_sort_key, reverse=sort_desc)
    for booking in sorted_bookings:
        writer.writerow(booking_to_history_row(booking))

    return output.getvalue()
