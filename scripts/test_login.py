#!/usr/bin/env python3
"""Manual test script for Paris Tennis login.

Run with: python scripts/test_login.py
"""

import logging
import os
import sys
import time

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.services.paris_tennis import ParisTennisService
from src.utils.browser import browser_session

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_login():
    """Test login flow against the live Paris Tennis site."""
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    logger.info(f"Testing login for: {email}")

    with browser_session(headless=False) as driver:
        service = ParisTennisService(driver=driver)

        logger.info("Starting login...")
        result = service.login(email, password)

        if result:
            logger.info("✓ Login successful!")
            logger.info(f"Current URL: {driver.current_url}")

            # Keep browser open for inspection
            logger.info("Keeping browser open for 30 seconds for inspection...")
            time.sleep(30)
        else:
            logger.error("✗ Login failed!")
            logger.info(f"Current URL: {driver.current_url}")
            driver.save_screenshot("/tmp/login_debug.png")
            logger.info("Screenshot saved to /tmp/login_debug.png")

            # Keep browser open for inspection
            logger.info("Keeping browser open for 60 seconds for debugging...")
            time.sleep(60)

        return result


if __name__ == "__main__":
    success = test_login()
    sys.exit(0 if success else 1)
