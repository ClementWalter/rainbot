"""Live end-to-end test: login, book, verify in profile, cancel, verify again."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.config import ParisTennisSettings
from paris_tennis_api.exceptions import AuthenticationError, BookingError


def _run_live_booking_flow() -> bool:
    """Run the real booking lifecycle against tennis.paris.fr."""

    settings = ParisTennisSettings.from_env()
    with ParisTennisClient.from_settings(settings) as client:
        client.login()
        # We clear stale reservations first so each run verifies one fresh booking cycle.
        client.cancel_current_reservation()
        client.book_first_available(days_in_advance=2)
        active_after_booking = client.get_current_reservation().has_active_reservation
        canceled = client.cancel_current_reservation()
        active_after_cancellation = (
            client.get_current_reservation().has_active_reservation
        )
    return bool(active_after_booking and canceled and not active_after_cancellation)


@pytest.mark.e2e
def test_live_booking_flow() -> None:
    """The API should complete a full booking lifecycle on the live platform."""

    load_dotenv(".env")
    required = [
        os.getenv("PARIS_TENNIS_EMAIL"),
        os.getenv("PARIS_TENNIS_PASSWORD"),
        os.getenv("CAPTCHA_API_KEY"),
    ]
    if not all(required):
        pytest.skip("Live credentials are not configured in .env.")
    try:
        result = _run_live_booking_flow()
    except (AuthenticationError, BookingError) as error:
        if "HTTP 403" in str(error):
            pytest.skip(f"Live auth/booking gateway denied access: {error}")
        raise
    assert result is True
