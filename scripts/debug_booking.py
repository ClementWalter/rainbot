#!/usr/bin/env python3
"""Debug script to understand why booking isn't happening."""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Enable verbose logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(module)s: %(message)s",
)

from src.models.booking_request import DayOfWeek
from src.services.google_sheets import sheets_service
from src.services.paris_tennis import create_paris_tennis_session
from src.services.requests_db import requests_service
from src.utils.timezone import now_paris, today_paris


def print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


async def debug_booking():
    print_section("CURRENT TIME")
    now = now_paris()
    print(f"Paris time: {now}")
    print(f"Today: {today_paris()}")
    print(f"Day of week: {now.weekday()} ({DayOfWeek(now.weekday()).name})")

    print_section("ACTIVE BOOKING REQUESTS")
    requests = requests_service.get_active_booking_requests()
    if not requests:
        print("❌ No active booking requests found!")
        return

    for req in requests:
        print(f"\n  Request: {req.id}")
        print(f"    User: {req.user_id}")
        print(f"    Day: {req.day_of_week.name} ({req.day_of_week.value})")
        print(f"    Time: {req.time_start} - {req.time_end}")
        print(f"    Facilities: {req.facility_preferences}")
        print(f"    Court type: {req.court_type}")
        print(f"    Active: {req.active}")

    print_section("ELIGIBLE USERS")
    eligible = sheets_service.get_eligible_users()
    if not eligible:
        print("❌ No eligible users found!")
    else:
        for user in eligible:
            print(f"\n  User: {user.id}")
            print(f"    Email: {user.email}")
            print(f"    Subscription: {user.subscription_active}")
            print(f"    Carnet balance: {user.carnet_balance}")
            print(f"    Is eligible: {user.is_eligible()}")

    print_section("PENDING BOOKINGS CHECK")
    for user in eligible:
        has_pending = sheets_service.has_pending_booking(user.id)
        status = "⚠️ HAS PENDING" if has_pending else "✅ No pending"
        print(f"  {user.id}: {status}")

        if has_pending:
            bookings = sheets_service.get_bookings_for_user(user.id)
            today = today_paris()
            for b in bookings:
                if b.date.date() >= today:
                    print(f"    → {b.date.date()} {b.time_start}-{b.time_end} at {b.facility_name}")

    print_section("TESTING AVAILABILITY CHECK")
    # Find a request to test
    test_request = requests[0]
    print(f"Testing request: {test_request.id}")
    print(f"  Day: {test_request.day_of_week.name}")
    print(f"  Facilities: {test_request.facility_preferences}")

    async with create_paris_tennis_session() as tennis:
        # Calculate target date
        target_date = tennis._get_next_booking_date(test_request.day_of_week.value)
        print(f"  Target date: {target_date.strftime('%Y-%m-%d')} ({target_date.strftime('%A')})")

        # Test quick check
        print("\n  Running quick availability check...")
        has_slots, count = await tennis.check_availability_quick(test_request)
        print(f"  Result: has_slots={has_slots}, count={count}")

        if has_slots:
            print("\n  ✅ Availability found! Running full search...")
            slots = await tennis.search_available_courts(test_request)
            print(f"  Found {len(slots)} slots:")
            for slot in slots[:5]:  # Show first 5
                print(f"    - {slot.facility_name} court {slot.court_number}: {slot.time_start}")
        else:
            print("\n  ❌ No availability found in quick check")

    print_section("SUMMARY")
    # Check what might be blocking
    issues = []

    if not requests:
        issues.append("No active booking requests")

    if not eligible:
        issues.append("No eligible users")

    for req in requests:
        if req.user_id not in {u.id for u in eligible}:
            issues.append(f"Request {req.id} user {req.user_id} is not eligible")

    for user in eligible:
        if sheets_service.has_pending_booking(user.id):
            issues.append(f"User {user.id} has pending booking (blocks new bookings)")

    if issues:
        print("⚠️ Potential issues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("✅ No obvious issues found. Check VPS logs for runtime errors.")


if __name__ == "__main__":
    asyncio.run(debug_booking())
