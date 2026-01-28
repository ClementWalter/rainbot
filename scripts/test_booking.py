#!/usr/bin/env python3
"""Test booking script for Paris Tennis.

This script attempts to book a tennis court slot 6 days from now.
The booking can be cancelled afterwards.

Usage:
    uv run python scripts/test_booking.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

# Load environment variables FIRST before any other imports
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models.booking_request import (  # noqa: E402
    BookingRequest,
    CourtType,
    DayOfWeek,
)
from src.services.paris_tennis import ParisTennisService  # noqa: E402
from src.utils.browser import PlaywrightSession  # noqa: E402


async def main():
    """Test booking flow."""
    email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
    password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")

    if not email or not password:
        print("Error: PARIS_TENNIS_EMAIL and PARIS_TENNIS_PASSWORD required")
        sys.exit(1)

    # Calculate target date (6 days from now)
    target_date = datetime.now() + timedelta(days=6)
    day_of_week = DayOfWeek(target_date.weekday())

    print(f"Target date: {target_date.strftime('%Y-%m-%d')} ({target_date.strftime('%A')})")

    async with PlaywrightSession(headless=False) as session:
        service = ParisTennisService(page=session.page)

        # Login
        print(f"\nLogging in as {email}...")
        if not await service.login(email, password):
            print("Login failed!")
            await session.page.screenshot(path="/tmp/booking_login_failed.png")
            return

        print("Login successful!")

        # Create booking request for any court, any time during business hours
        request = BookingRequest(
            id="test-booking",
            user_id="test-user",
            day_of_week=day_of_week,
            time_start="09:00",
            time_end="21:00",
            facility_preferences=[],  # Any facility
            court_type=CourtType.ANY,
        )

        # Search for available slots
        print(f"\nSearching for available courts on {target_date.strftime('%Y-%m-%d')}...")
        slots = await service.search_available_courts(request, target_date=target_date)

        if not slots:
            print("No available slots found!")
            await session.page.screenshot(path="/tmp/booking_no_slots.png")
            return

        print(f"\nFound {len(slots)} available slots:")
        for i, slot in enumerate(slots[:10]):  # Show first 10
            print(
                f"  {i+1}. {slot.facility_name}: {slot.time_start}-{slot.time_end} "
                f"(Court {slot.court_number})"
            )

        # Pick the first slot to book
        slot_to_book = slots[0]
        print(f"\nAttempting to book: {slot_to_book.facility_name} at {slot_to_book.time_start}")
        print(f"  Equipment ID: {slot_to_book.equipment_id}")
        print(f"  Court ID: {slot_to_book.court_id}")
        print(f"  Reservation start: {slot_to_book.reservation_start}")

        # Attempt booking
        print("Starting booking process...")
        result = await service.book_court(
            slot=slot_to_book,
            player_name="Clement Walter",
            player_email=email,
        )

        # Debug: check page state after booking attempt
        print(f"  Final URL: {session.page.url}")
        print(f"  Final title: {await session.page.title()}")

        if result.success:
            print("\n✓ Booking successful!")
            print(f"  Confirmation ID: {result.confirmation_id}")
            print(f"  Facility: {slot_to_book.facility_name}")
            print(f"  Time: {slot_to_book.time_start}-{slot_to_book.time_end}")
            print(f"  Date: {target_date.strftime('%Y-%m-%d')}")
            print("\n  You can cancel this booking from your Paris Tennis account.")
        else:
            print(f"\n✗ Booking failed: {result.error_message}")
            await session.page.screenshot(path="/tmp/booking_failed.png")
            print("  Screenshot saved to /tmp/booking_failed.png")

        # Wait a moment so user can see the result
        print("\nBrowser will close in 5 seconds...")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
