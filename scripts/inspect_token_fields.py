#!/usr/bin/env python3
"""Inspect li-antibot token fields after captcha validation."""

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


def inspect_token_fields():
    """Inspect token fields before and after captcha."""
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    driver = create_browser(headless=False)

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
            logger.error("No slots found!")
            return

        slot = slots[0]
        logger.info(f"Found slot: {slot.facility_name}")

        from selenium.webdriver.support.ui import WebDriverWait

        wait = WebDriverWait(driver, 30)
        service._submit_reservation_form(
            slot, slot.captcha_request_id or service._get_captcha_request_id(), None, None
        )
        service._wait_for_booking_state(wait)

        # Inspect fields BEFORE captcha solve
        logger.info("=" * 60)
        logger.info("BEFORE CAPTCHA SOLVE:")
        result = driver.execute_script("""
            const token = document.getElementById('li-antibot-token');
            const code = document.getElementById('li-antibot-token-code');
            const form = document.getElementById('formCaptcha');
            const inputs = form ? Array.from(form.querySelectorAll('input')).map(i => ({
                name: i.name,
                id: i.id,
                type: i.type,
                value: i.value ? i.value.substring(0, 50) + '...' : ''
            })) : [];
            return {
                token: token ? token.value : 'NOT FOUND',
                code: code ? code.value : 'NOT FOUND',
                formInputs: inputs
            };
        """)
        logger.info(f"Token: {result['token'][:50] if result['token'] else 'empty'}...")
        logger.info(f"Code: {result['code']}")
        logger.info(f"Form inputs: {result['formInputs']}")

        # Solve the captcha
        from src.services.captcha_solver import CaptchaSolverService

        solver = CaptchaSolverService()
        captcha_result = solver.solve_captcha_from_page(driver)

        if captcha_result and captcha_result.success:
            logger.info("Captcha solved!")
        else:
            logger.error(f"Captcha failed: {captcha_result}")

        # Inspect fields AFTER captcha solve
        time.sleep(1)
        logger.info("=" * 60)
        logger.info("AFTER CAPTCHA SOLVE:")
        result = driver.execute_script("""
            const token = document.getElementById('li-antibot-token');
            const code = document.getElementById('li-antibot-token-code');
            const form = document.getElementById('formCaptcha');
            const inputs = form ? Array.from(form.querySelectorAll('input')).map(i => ({
                name: i.name,
                id: i.id,
                type: i.type,
                value: i.value ? i.value.substring(0, 50) + '...' : ''
            })) : [];
            return {
                token: token ? token.value : 'NOT FOUND',
                code: code ? code.value : 'NOT FOUND',
                formInputs: inputs
            };
        """)
        logger.info(f"Token: {result['token'][:50] if result['token'] else 'empty'}...")
        logger.info(f"Code: {result['code']}")
        logger.info(f"Form inputs: {result['formInputs']}")
        logger.info("=" * 60)

        logger.info("Browser staying open for 5 minutes...")
        time.sleep(300)

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()
        time.sleep(120)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    inspect_token_fields()
