#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "playwright>=1.53.0",
#   "python-dotenv>=1.0.1",
#   "requests>=2.32.3",
#   "beautifulsoup4>=4.12.3",
#   "lxml>=5.2.2",
# ]
# ///
"""Run the live booking flow once: login, book, verify, cancel, verify."""

from __future__ import annotations

import logging

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.config import ParisTennisSettings


def main() -> None:
    """Execute a full real-world flow so local changes can be validated end-to-end."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    settings = ParisTennisSettings.from_env()
    with ParisTennisClient.from_settings(settings) as client:
        client.login()
        # We proactively cancel stale reservations to keep repeated local runs deterministic.
        client.cancel_current_reservation()
        booked = client.book_first_available(days_in_advance=2)
        logger.info("Booked slot at venue '%s'.", booked.venue_name)
        canceled = client.cancel_current_reservation()
        logger.info("Reservation canceled: %s", canceled)


if __name__ == "__main__":
    main()
