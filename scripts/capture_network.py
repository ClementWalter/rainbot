#!/usr/bin/env python3
"""Capture network traffic during manual captcha solving to compare with automated flow."""

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from selenium import webdriver  # noqa: E402
from selenium.webdriver.chrome.service import Service  # noqa: E402
from webdriver_manager.chrome import ChromeDriverManager  # noqa: E402

from src.models.booking_request import (  # noqa: E402
    BookingRequest,
    CourtType,
    DayOfWeek,
)
from src.services.paris_tennis import ParisTennisService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def create_browser_with_logging():
    """Create a browser with network logging enabled."""
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    # Enable performance logging
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(10)

    return driver


def get_network_logs(driver):
    """Extract network logs from the browser."""
    logs = driver.get_log("performance")
    network_events = []

    for entry in logs:
        try:
            message = json.loads(entry["message"])["message"]
            if message["method"] in ["Network.requestWillBeSent", "Network.responseReceived"]:
                network_events.append(message)
        except (json.JSONDecodeError, KeyError):
            continue

    return network_events


def main():
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    logger.info("Creating browser with network logging...")
    driver = create_browser_with_logging()

    try:
        service = ParisTennisService(driver=driver)
        service.login(email, password)

        target_date = datetime.now() + timedelta(days=6)
        request = BookingRequest(
            id="test",
            user_id="test",
            day_of_week=DayOfWeek(target_date.weekday()),
            time_start="08:00",
            time_end="22:00",
            facility_preferences=[],
            court_type=CourtType.ANY,
        )

        slots = service.search_available_courts(request, target_date=target_date)
        if not slots:
            logger.error("No slots!")
            return

        slot = slots[0]
        logger.info(f"Using slot: {slot.facility_name}")

        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(driver, 30)

        service._submit_reservation_form(
            slot, slot.captcha_request_id or service._get_captcha_request_id(), None, None
        )
        service._wait_for_booking_state(wait)

        logger.info("=" * 60)
        logger.info("NOW MANUALLY SOLVE THE CAPTCHA AND SUBMIT THE FORM")
        logger.info("I'll capture all network requests...")
        logger.info("=" * 60)

        # Wait for user to complete the flow manually
        start_url = driver.current_url
        logger.info(f"Starting URL: {start_url}")

        # Monitor for URL changes and capture logs
        all_events = []
        for _i in range(120):  # 2 minutes
            time.sleep(1)
            events = get_network_logs(driver)
            if events:
                for event in events:
                    if event["method"] == "Network.requestWillBeSent":
                        req = event["params"]["request"]
                        url = req["url"]
                        if "tennis.paris.fr" in url or "liveidentity" in url:
                            logger.info(f"REQUEST: {req['method']} {url}")
                            if req.get("postData"):
                                logger.info(f"  Body: {req['postData'][:200]}...")
                            all_events.append({"type": "request", "data": event["params"]})

                    elif event["method"] == "Network.responseReceived":
                        resp = event["params"]["response"]
                        url = resp["url"]
                        if "tennis.paris.fr" in url or "liveidentity" in url:
                            logger.info(f"RESPONSE: {resp['status']} {url}")
                            all_events.append({"type": "response", "data": event["params"]})

            current_url = driver.current_url
            if current_url != start_url:
                logger.info(f"URL changed to: {current_url}")
                start_url = current_url

            # Check if we reached payment page
            if "methode_paiement" in driver.current_url:
                logger.info("SUCCESS! Reached payment page!")
                break

        # Save all events to file
        with open("/tmp/network_capture.json", "w") as f:
            json.dump(all_events, f, indent=2, default=str)
        logger.info("Saved network capture to /tmp/network_capture.json")

        logger.info("Browser staying open for inspection...")
        time.sleep(300)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
