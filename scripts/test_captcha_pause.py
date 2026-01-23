#!/usr/bin/env python3
"""Test captcha solving and pause for manual inspection.

Run with: uv run python scripts/test_captcha_pause.py
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from src.models.booking_request import (  # noqa: E402
    BookingRequest,
    CourtType,
    DayOfWeek,
)
from src.services.paris_tennis import ParisTennisService  # noqa: E402
from src.utils.browser import create_browser  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_captcha_pause():
    """Test captcha solving and pause for manual inspection."""
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    logger.info(f"Testing captcha for: {email}")

    # Create browser without context manager so it stays open
    driver = create_browser(headless=False)

    try:
        service = ParisTennisService(driver=driver)

        # Login
        logger.info("Starting login...")
        if not service.login(email, password):
            logger.error("Login failed")
            return

        logger.info("Login successful!")

        # Search for courts 6 days from now
        target_date = datetime.now() + timedelta(days=6)
        request = BookingRequest(
            id="captcha-test",
            user_id="test-user",
            day_of_week=DayOfWeek(target_date.weekday()),
            time_start="08:00",
            time_end="22:00",
            facility_preferences=[],
            court_type=CourtType.ANY,
        )

        logger.info(f"Searching for courts on {target_date.strftime('%A %d/%m/%Y')}...")
        slots = service.search_available_courts(request, target_date=target_date)

        if not slots:
            logger.error("No slots found!")
            logger.info("Keeping browser open for 5 minutes...")
            time.sleep(300)
            return

        slot = slots[0]
        logger.info(f"Found slot: {slot.facility_name} - Court {slot.court_number}")

        # Navigate to booking page and solve captcha
        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(driver, 30)

        # Submit reservation form to get to captcha page
        logger.info("Submitting reservation form...")
        service._submit_reservation_form(
            slot, slot.captcha_request_id or service._get_captcha_request_id(), None, None
        )
        service._wait_for_booking_state(wait)

        logger.info("On captcha page, solving captcha...")

        # Solve the captcha
        from src.services.captcha_solver import CaptchaSolverService

        solver = CaptchaSolverService()
        result = solver.solve_captcha_from_page(driver)

        if result and result.success:
            logger.info("=" * 60)
            logger.info("CAPTCHA SOLVED SUCCESSFULLY!")
            logger.info(f"Token length: {len(result.token) if result.token else 0}")
            logger.info("=" * 60)
        else:
            logger.error(
                f"Captcha solving failed: {result.error_message if result else 'No result'}"
            )

        logger.info("")
        logger.info("=" * 60)
        logger.info("BROWSER PAUSED - Inspect console/network now")
        logger.info("Browser will stay open for 5 minutes...")
        logger.info("Close the browser window manually when done.")
        logger.info("=" * 60)

        # Keep alive for 5 minutes
        time.sleep(300)

    except Exception as e:
        logger.error(f"Error: {e}")
        logger.info("Browser will stay open for 2 minutes for debugging...")
        time.sleep(120)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    test_captcha_pause()
