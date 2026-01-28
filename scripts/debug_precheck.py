#!/usr/bin/env python
"""Debug script to test the full booking flow with pre-check."""

import asyncio
import logging
import sys
from datetime import datetime

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noise from other loggers
logging.getLogger("playwright").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


async def debug_full_flow():
    """Test the full booking flow: pre-check -> search -> login -> book."""
    from src.models.booking_request import BookingRequest, CourtType, DayOfWeek
    from src.services.paris_tennis import FACILITY_CODE_TO_NAME, ParisTennisService
    from src.utils.browser import PlaywrightSession

    # Create test request
    request = BookingRequest(
        id="debug_req",
        user_id="debug_user",
        day_of_week=DayOfWeek.MONDAY,  # lundi
        time_start="08:00",
        time_end="20:00",
        court_type=CourtType.ANY,
        facility_preferences=["497", "92"],  # Jules Ladoumègue, Bertrand Dauvin
        active=True,
    )

    # Calculate target date (next Monday = 2026-02-02)
    target_date = datetime(2026, 2, 2)

    logger.info("=" * 60)
    logger.info("DEBUG FULL BOOKING FLOW")
    logger.info("=" * 60)
    logger.info(f"Target date: {target_date.strftime('%Y-%m-%d')}")
    logger.info(f"Time range: {request.time_start} - {request.time_end}")
    logger.info(f"Facility codes: {request.facility_preferences}")
    facility_names = [FACILITY_CODE_TO_NAME.get(c, c) for c in request.facility_preferences]
    logger.info(f"Facility names: {facility_names}")
    logger.info("=" * 60)

    async with PlaywrightSession(headless=False) as session:
        tennis = ParisTennisService(session.page)

        # STEP 1: Quick availability check (no login)
        logger.info("\n" + "=" * 60)
        logger.info("STEP 1: Quick availability check (check_availability_quick)")
        logger.info("=" * 60)

        has_slots, slot_count = await tennis.check_availability_quick(
            request=request,
            target_date=target_date,
        )

        logger.info(f"Quick check result: has_slots={has_slots}, count={slot_count}")

        if not has_slots:
            logger.info("NO AVAILABILITY - would skip login in production")
            logger.info("\nPress Enter to close browser...")
            input()
            return

        logger.info("AVAILABILITY CONFIRMED - proceeding to full search")

        # STEP 2: Full search to get slot details
        logger.info("\n" + "=" * 60)
        logger.info("STEP 2: Full search (search_available_courts)")
        logger.info("=" * 60)

        available_slots = await tennis.search_available_courts(
            request=request,
            target_date=target_date,
        )

        logger.info(f"\nFound {len(available_slots)} slots matching preferences:")
        for i, slot in enumerate(available_slots[:10]):  # Show first 10
            logger.info(
                f"  {i+1}. {slot.facility_name}, court {slot.court_number}, "
                f"{slot.time_start}-{slot.time_end}"
            )
        if len(available_slots) > 10:
            logger.info(f"  ... and {len(available_slots) - 10} more")

        if not available_slots:
            logger.info("No slots found after full search")
            logger.info("\nPress Enter to close browser...")
            input()
            return

        # STEP 3: Would proceed to login and booking
        logger.info("\n" + "=" * 60)
        logger.info("STEP 3: Login (would happen in production)")
        logger.info("=" * 60)
        logger.info("In production, we would now:")
        logger.info("  1. Click 'Se connecter' on the first slot")
        logger.info("  2. Login with user credentials")
        logger.info("  3. Solve CAPTCHA if needed")
        logger.info("  4. Complete the booking")

        # Demo: click the login button to show it works
        logger.info("\nClicking 'Se connecter' on first slot...")
        login_button = tennis.page.locator("button.btn-darkblue:has-text('Se connecter')").first
        await login_button.click()

        await asyncio.sleep(2)
        logger.info(f"Current URL after click: {tennis.page.url}")

        logger.info("\n" + "=" * 60)
        logger.info("FLOW COMPLETE")
        logger.info("In production, login would happen here with user credentials")
        logger.info("Press Enter to close browser...")
        logger.info("=" * 60)
        input()


if __name__ == "__main__":
    asyncio.run(debug_full_flow())
