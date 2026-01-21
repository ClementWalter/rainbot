#!/usr/bin/env python3
"""Manual test script for Paris Tennis court search.

Run with: python scripts/test_search.py
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.models.booking_request import BookingRequest, CourtType, DayOfWeek
from src.services.paris_tennis import ParisTennisService
from src.utils.browser import browser_session

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_search():
    """Test search flow against the live Paris Tennis site."""
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    logger.info(f"Testing search for: {email}")

    with browser_session(headless=False) as driver:
        service = ParisTennisService(driver=driver)

        # Login first
        logger.info("Starting login...")
        login_result = service.login(email, password)
        if not login_result:
            logger.error("Login failed, aborting search test")
            return False

        logger.info("✓ Login successful!")

        # Create a booking request for tomorrow
        tomorrow = datetime.now() + timedelta(days=1)
        day_of_week = DayOfWeek(tomorrow.weekday())

        request = BookingRequest(
            id="test-request",
            user_id="test-user",
            day_of_week=day_of_week,
            time_start="10:00",
            time_end="20:00",
            facility_preferences=[],  # Any facility
            court_type=CourtType.ANY,
        )

        logger.info(f"Searching for courts on {tomorrow.strftime('%A %d/%m/%Y')}...")
        logger.info(f"Time range: {request.time_start} - {request.time_end}")

        # Search for available courts
        slots = service.search_available_courts(request, target_date=tomorrow)

        if slots:
            logger.info(f"\n✓ Found {len(slots)} available slots:")
            for i, slot in enumerate(slots[:10]):  # Show first 10
                logger.info(
                    f"  {i+1}. {slot.facility_name}: {slot.time_start}-{slot.time_end} "
                    f"(Court {slot.court_number}) - {slot.court_type.value}"
                )
                if slot.facility_address:
                    logger.info(f"      Address: {slot.facility_address}")
        else:
            logger.warning("✗ No slots found!")
            driver.save_screenshot("/tmp/search_no_slots.png")
            logger.info("Screenshot saved to /tmp/search_no_slots.png")

        # Keep browser open for inspection
        logger.info("\nKeeping browser open for 30 seconds for inspection...")
        time.sleep(30)

        return len(slots) > 0


if __name__ == "__main__":
    success = test_search()
    sys.exit(0 if success else 1)
