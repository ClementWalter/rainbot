#!/usr/bin/env python3
"""Inspect the captcha page HTML structure."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timedelta  # noqa: E402

from src.models.booking_request import (  # noqa: E402
    BookingRequest,
    CourtType,
    DayOfWeek,
)
from src.services.paris_tennis import ParisTennisService  # noqa: E402
from src.utils.browser import browser_session  # noqa: E402

email = os.getenv("PARIS_TENNIS_EMAIL")
password = os.getenv("PARIS_TENNIS_PASSWORD")

with browser_session(headless=False) as driver:
    service = ParisTennisService(driver=driver)
    service.login(email, password)

    # Search for a slot
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

        # Navigate to captcha page
        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(driver, 30)
        service._submit_reservation_form(
            slot, slot.captcha_request_id or service._get_captcha_request_id(), None, None
        )
        service._wait_for_booking_state(wait)

        # Now inspect the page
        print("\n=== Current URL ===")
        print(driver.current_url)

        print("\n=== Looking for captcha elements ===")

        # Check for li-antibot
        try:
            li_antibot = driver.find_element("id", "li-antibot")
            print("Found #li-antibot")
            print(f"  - innerHTML length: {len(li_antibot.get_attribute('innerHTML'))} chars")
        except Exception:
            print("No #li-antibot found")

        # Check for formCaptcha
        try:
            form_captcha = driver.find_element("id", "formCaptcha")
            print("Found #formCaptcha")
            print(f"  - innerHTML preview: {form_captcha.get_attribute('innerHTML')[:500]}...")
        except Exception:
            print("No #formCaptcha found")

        # Check for any img with captcha in src
        imgs = driver.find_elements("css selector", "img")
        print(f"\nFound {len(imgs)} images on page:")
        for i, img in enumerate(imgs):
            src = img.get_attribute("src") or ""
            alt = img.get_attribute("alt") or ""
            if "captcha" in src.lower() or "captcha" in alt.lower() or i < 5:
                print(f"  [{i}] src={src[:80]}... alt={alt}")

        # Get the captcha image specifically
        print("\n=== Captcha image search ===")
        for selector in [
            "#captcha img",
            ".captcha-image img",
            "img[src*='captcha']",
            "#formCaptcha img",
            ".modal img",
            "form img",
        ]:
            try:
                el = driver.find_element("css selector", selector)
                print(f"Found with '{selector}': src={el.get_attribute('src')[:80]}...")
            except Exception:
                print(f"Not found: '{selector}'")

        input("Press Enter to close browser...")
