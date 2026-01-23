#!/usr/bin/env python3
"""Test script to verify captcha solving during booking flow.

This test:
1. Logs in
2. Searches for any available court 6 days from now
3. Attempts to book the first slot found
4. Focuses on whether we can pass the captcha page

Run with: python scripts/test_captcha.py
"""

import logging
import os
import sys
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.models.booking_request import (  # noqa: E402
    BookingRequest,
    CourtType,
    DayOfWeek,
)
from src.services.paris_tennis import ParisTennisService  # noqa: E402
from src.utils.browser import browser_session  # noqa: E402

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_captcha():
    """Test captcha solving by attempting a booking."""
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    logger.info(f"Testing captcha for: {email}")

    with browser_session(headless=False) as driver:
        service = ParisTennisService(driver=driver)

        # Login first
        logger.info("Starting login...")
        login_result = service.login(email, password)
        if not login_result:
            logger.error("Login failed, aborting captcha test")
            return False

        logger.info("Login successful!")

        # Search for courts 6 days from now (any time, any facility)
        target_date = datetime.now() + timedelta(days=6)
        day_of_week = DayOfWeek(target_date.weekday())

        request = BookingRequest(
            id="captcha-test",
            user_id="test-user",
            day_of_week=day_of_week,
            time_start="08:00",
            time_end="22:00",  # Full day range
            facility_preferences=[],  # Any facility
            court_type=CourtType.ANY,
        )

        logger.info(f"Searching for courts on {target_date.strftime('%A %d/%m/%Y')}...")
        slots = service.search_available_courts(request, target_date=target_date)

        if not slots:
            logger.error("No slots found! Cannot test captcha without a slot to book.")
            driver.save_screenshot("/tmp/captcha_no_slots.png")
            return False

        logger.info(f"Found {len(slots)} slots. Taking first one for captcha test.")
        slot = slots[0]
        logger.info(
            f"Testing with: {slot.facility_name} - Court {slot.court_number} "
            f"at {slot.time_start}-{slot.time_end}"
        )

        # Attempt to book - this will trigger the captcha flow
        logger.info("Starting booking flow (captcha test)...")
        logger.info("=" * 60)
        logger.info("CAPTCHA TEST: Attempting to reach and pass captcha page")
        logger.info("=" * 60)

        result = service.book_court(
            slot,
            partner_name="Test Partner",
            player_name="Test Player",
            player_email=email,
            partner_email=email,
        )

        # Take screenshot of final state
        driver.save_screenshot("/tmp/captcha_test_result.png")
        logger.info("Screenshot saved to /tmp/captcha_test_result.png")

        if result.success:
            logger.info("=" * 60)
            logger.info("CAPTCHA TEST PASSED! Booking successful.")
            logger.info(f"Confirmation ID: {result.confirmation_id}")
            logger.info("=" * 60)
            return True
        else:
            logger.error("=" * 60)
            logger.error(f"CAPTCHA TEST FAILED: {result.error_message}")
            logger.error("=" * 60)

            # Check current URL to see where we got stuck
            current_url = driver.current_url
            logger.info(f"Current URL: {current_url}")

            if "captcha" in current_url.lower():
                logger.error("STUCK ON CAPTCHA PAGE - captcha solving failed")
            elif "reservation" in current_url.lower():
                logger.info("Got past captcha but failed at reservation step")

            return False


if __name__ == "__main__":
    success = test_captcha()
    sys.exit(0 if success else 1)
