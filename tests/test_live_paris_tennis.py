"""Live integration tests for Paris Tennis website.

These tests run against the real tennis.paris.fr website to validate
the automation flow. They require:
- CAPTCHA_API_KEY environment variable (for 2captcha)
- Valid Paris Tennis credentials

Run with: pytest tests/test_live_paris_tennis.py -v -s -m live
"""

import os

import pytest
from dotenv import load_dotenv

from src.services.paris_tennis import ParisTennisService
from src.utils.browser import PlaywrightSession

# Load environment variables
load_dotenv()

# Mark all tests as live tests (skipped by default unless -m live is passed)
pytestmark = [pytest.mark.live, pytest.mark.asyncio]


class TestLiveLogin:
    """Test login flow against the live site."""

    @pytest.fixture
    def credentials(self):
        """Get Paris Tennis credentials from environment."""
        email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
        password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")
        if not email or not password:
            pytest.skip("Paris Tennis credentials not configured")
        return email, password

    async def test_login_live(self, credentials):
        """Test that login works against the live site."""
        email, password = credentials

        async with PlaywrightSession(headless=False) as session:
            service = ParisTennisService(page=session.page)

            # Navigate to login page and attempt login
            result = await service.login(email, password)

            if not result:
                # Take a screenshot for debugging
                await session.page.screenshot(path="/tmp/login_failed.png")
                print("Login failed. Screenshot saved to /tmp/login_failed.png")
                print(f"Current URL: {session.page.url}")
                print(f"Page title: {await session.page.title()}")

            assert result, f"Login failed for {email}"


class TestLiveSearch:
    """Test availability search against the live site."""

    @pytest.fixture
    def credentials(self):
        """Get Paris Tennis credentials from environment."""
        email = os.getenv("PARIS_TENNIS_EMAIL", "clement0walter@gmail.com")
        password = os.getenv("PARIS_TENNIS_PASSWORD", "Rainbot456")
        if not email or not password:
            pytest.skip("Paris Tennis credentials not configured")
        return email, password

    async def test_search_available_courts_live(self, credentials):
        """Test that search returns results from the live site."""
        from datetime import datetime, timedelta

        from src.models.booking_request import BookingRequest, CourtType, DayOfWeek

        email, password = credentials

        async with PlaywrightSession(headless=False) as session:
            service = ParisTennisService(page=session.page)

            # Login first
            login_result = await service.login(email, password)
            if not login_result:
                await session.page.screenshot(path="/tmp/search_login_failed.png")
                pytest.skip("Could not log in")

            # Create a booking request for testing
            # Search for tomorrow or next available day
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

            # Search for available courts
            slots = await service.search_available_courts(request, target_date=tomorrow)

            print(f"\nFound {len(slots)} available slots:")
            for slot in slots[:5]:  # Show first 5
                print(
                    f"  - {slot.facility_name}: {slot.time_start}-{slot.time_end} "
                    f"(Court {slot.court_number})"
                )

            # We may or may not find slots, but the search should not error
            # Just verify we got a list back
            assert isinstance(slots, list)
