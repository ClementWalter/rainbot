#!/usr/bin/env python3
"""Debug what happens to li-antibot fields during captcha validation."""

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
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

        # Check initial state
        logger.info("=" * 60)
        logger.info("BEFORE CAPTCHA SOLVE:")
        check_fields(driver)

        # Watch the fields while solving manually
        logger.info("=" * 60)
        logger.info("SOLVE THE CAPTCHA MANUALLY and watch the fields...")
        logger.info("Monitoring for 60 seconds...")

        for i in range(60):
            time.sleep(1)
            token, code = get_field_values(driver)
            if token or code:
                logger.info(
                    f"[{i}s] token={token[:30] if token else 'empty'}... code={code or 'empty'}"
                )

        logger.info("=" * 60)
        logger.info("FINAL STATE:")
        check_fields(driver)

        logger.info("Browser staying open...")
        time.sleep(300)

    finally:
        driver.quit()


def get_field_values(driver):
    try:
        result = driver.execute_script("""
            const token = document.getElementById('li-antibot-token');
            const code = document.getElementById('li-antibot-token-code');
            return [
                token ? token.value : null,
                code ? code.value : null
            ];
        """)
        return result[0], result[1]
    except Exception:
        return None, None


def check_fields(driver):
    result = driver.execute_script("""
        const container = document.getElementById('li-antibot');
        const tokenInput = document.getElementById('li-antibot-token');
        const codeInput = document.getElementById('li-antibot-token-code');
        const form = document.getElementById('formCaptcha');

        let allInputs = [];
        if (form) {
            allInputs = Array.from(form.querySelectorAll('input')).map(i => ({
                id: i.id,
                name: i.name,
                type: i.type,
                value: i.value ? i.value.substring(0, 50) : ''
            }));
        }

        return {
            containerExists: !!container,
            tokenInputExists: !!tokenInput,
            tokenValue: tokenInput ? tokenInput.value : null,
            codeInputExists: !!codeInput,
            codeValue: codeInput ? codeInput.value : null,
            formExists: !!form,
            allInputs: allInputs
        };
    """)

    logger.info(f"Container exists: {result['containerExists']}")
    logger.info(
        f"Token input exists: {result['tokenInputExists']}, value: {result['tokenValue'][:50] if result['tokenValue'] else 'empty'}..."
    )
    logger.info(
        f"Code input exists: {result['codeInputExists']}, value: {result['codeValue'] or 'empty'}"
    )
    logger.info(f"Form exists: {result['formExists']}")
    logger.info(f"All form inputs: {result['allInputs']}")


if __name__ == "__main__":
    main()
