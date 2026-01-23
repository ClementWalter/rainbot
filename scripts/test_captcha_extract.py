#!/usr/bin/env python3
"""Test extracting captcha image from iframe."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timedelta  # noqa: E402

from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

from src.models.booking_request import (  # noqa: E402
    BookingRequest,
    CourtType,
    DayOfWeek,
)
from src.services.paris_tennis import ParisTennisService  # noqa: E402
from src.utils.browser import browser_session  # noqa: E402

email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

with browser_session(headless=False) as driver:
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

    if slots:
        slot = slots[0]
        print(f"Found slot: {slot.facility_name}")

        wait = WebDriverWait(driver, 30)
        service._submit_reservation_form(
            slot, slot.captcha_request_id or service._get_captcha_request_id(), None, None
        )
        service._wait_for_booking_state(wait)
        time.sleep(2)

        print(f"URL: {driver.current_url}")

        # Method 1: Try to take screenshot of iframe element
        print("\n=== Method 1: Screenshot of iframe ===")
        try:
            iframe = driver.find_element("css selector", "#li-antibot iframe")
            iframe_screenshot = iframe.screenshot_as_base64
            print(f"Got iframe screenshot, base64 length: {len(iframe_screenshot)}")

            # Save to file for inspection
            import base64

            with open("/tmp/captcha_iframe.png", "wb") as f:
                f.write(base64.b64decode(iframe_screenshot))
            print("Saved to /tmp/captcha_iframe.png")
        except Exception as e:
            print(f"Failed: {e}")

        # Method 2: Switch to iframe and find img element
        print("\n=== Method 2: Switch to iframe ===")
        try:
            iframe = driver.find_element("css selector", "#li-antibot iframe")
            driver.switch_to.frame(iframe)

            # Now we're in the iframe context
            img = driver.find_element("css selector", "img")
            img_src = img.get_attribute("src")
            print(f"Image src: {img_src}")

            # Try screenshot of img element
            img_screenshot = img.screenshot_as_base64
            print(f"Got img screenshot, base64 length: {len(img_screenshot)}")

            import base64

            with open("/tmp/captcha_img.png", "wb") as f:
                f.write(base64.b64decode(img_screenshot))
            print("Saved to /tmp/captcha_img.png")

            # Switch back to main content
            driver.switch_to.default_content()
        except Exception as e:
            print(f"Failed: {e}")
            driver.switch_to.default_content()
    else:
        print("No slots found")
