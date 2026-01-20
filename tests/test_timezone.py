"""Tests for timezone utilities."""

from datetime import date, datetime

import pytest
import pytz

from src.utils.timezone import (
    PARIS_TZ,
    now_paris,
    today_paris,
    today_weekday_paris,
)


class TestParisTz:
    """Tests for PARIS_TZ constant."""

    def test_paris_tz_is_timezone(self):
        """Test that PARIS_TZ is a valid pytz timezone."""
        assert PARIS_TZ is not None
        assert PARIS_TZ.zone == "Europe/Paris"

    def test_paris_tz_can_localize(self):
        """Test that PARIS_TZ can localize datetimes."""
        naive_dt = datetime(2024, 1, 15, 10, 30, 0)
        localized = PARIS_TZ.localize(naive_dt)
        assert localized.tzinfo is not None


class TestNowParis:
    """Tests for now_paris function."""

    def test_now_paris_returns_datetime(self):
        """Test that now_paris returns a datetime object."""
        result = now_paris()
        assert isinstance(result, datetime)

    def test_now_paris_is_timezone_aware(self):
        """Test that now_paris returns a timezone-aware datetime."""
        result = now_paris()
        assert result.tzinfo is not None

    def test_now_paris_is_paris_timezone(self):
        """Test that now_paris returns datetime in Paris timezone."""
        result = now_paris()
        # The tzinfo should be either Europe/Paris or a DST variant
        assert (
            "Europe/Paris" in str(result.tzinfo)
            or "CET" in str(result.tzinfo)
            or "CEST" in str(result.tzinfo)
        )

    def test_now_paris_returns_recent_time(self):
        """Test that now_paris returns a time close to the current time."""
        import time

        before = time.time()
        result = now_paris()
        after = time.time()

        # Convert result to Unix timestamp for comparison
        result_timestamp = result.timestamp()

        # Should be within a few seconds of the current time
        epsilon = 0.01
        assert before - epsilon <= result_timestamp <= after + 1 + epsilon


class TestTodayParis:
    """Tests for today_paris function."""

    def test_today_paris_returns_date(self):
        """Test that today_paris returns a date object."""
        result = today_paris()
        assert isinstance(result, date)

    def test_today_paris_matches_now_paris_date(self):
        """Test that today_paris matches the date from now_paris."""
        now = now_paris()
        today = today_paris()
        assert today == now.date()


class TestTodayWeekdayParis:
    """Tests for today_weekday_paris function."""

    def test_today_weekday_paris_returns_int(self):
        """Test that today_weekday_paris returns an integer."""
        result = today_weekday_paris()
        assert isinstance(result, int)

    def test_today_weekday_paris_in_valid_range(self):
        """Test that today_weekday_paris returns 0-6."""
        result = today_weekday_paris()
        assert 0 <= result <= 6

    def test_today_weekday_paris_matches_now_paris_weekday(self):
        """Test that today_weekday_paris matches the weekday from now_paris."""
        now = now_paris()
        weekday = today_weekday_paris()
        assert weekday == now.weekday()


class TestTimezoneEdgeCases:
    """Tests for timezone edge cases."""

    def test_handles_utc_server_time(self):
        """Test that Paris time is correctly calculated regardless of server timezone."""
        # Get current Paris time
        paris_time = now_paris()
        utc_time = datetime.now(pytz.UTC)

        # Paris should be 1-2 hours ahead of UTC (depending on DST)
        diff_hours = (paris_time.hour - utc_time.hour) % 24
        assert diff_hours in [1, 2, 23]  # 23 = -1 when wrapping around midnight

    def test_winter_time_offset(self):
        """Test Paris winter time (CET = UTC+1)."""
        # January 15, 2024 12:00 UTC should be 13:00 Paris
        utc_winter = pytz.UTC.localize(datetime(2024, 1, 15, 12, 0, 0))
        paris_winter = utc_winter.astimezone(PARIS_TZ)
        assert paris_winter.hour == 13

    def test_summer_time_offset(self):
        """Test Paris summer time (CEST = UTC+2)."""
        # July 15, 2024 12:00 UTC should be 14:00 Paris
        utc_summer = pytz.UTC.localize(datetime(2024, 7, 15, 12, 0, 0))
        paris_summer = utc_summer.astimezone(PARIS_TZ)
        assert paris_summer.hour == 14

    def test_dst_transition_spring(self):
        """Test DST transition in spring (last Sunday of March)."""
        # March 31, 2024 was DST transition day
        # 1:30 AM becomes 3:30 AM
        before_dst = PARIS_TZ.localize(datetime(2024, 3, 31, 1, 30, 0))
        after_dst = PARIS_TZ.localize(datetime(2024, 3, 31, 3, 30, 0))

        # Check UTC offset changed
        assert before_dst.utcoffset().total_seconds() == 3600  # +1 hour
        assert after_dst.utcoffset().total_seconds() == 7200  # +2 hours

    def test_dst_transition_fall(self):
        """Test DST transition in fall (last Sunday of October)."""
        # October 27, 2024 was DST transition day
        # 3:00 AM becomes 2:00 AM
        before_dst = PARIS_TZ.localize(datetime(2024, 10, 27, 2, 30, 0), is_dst=True)
        after_dst = PARIS_TZ.localize(datetime(2024, 10, 27, 2, 30, 0), is_dst=False)

        # Check UTC offset changed
        assert before_dst.utcoffset().total_seconds() == 7200  # +2 hours (CEST)
        assert after_dst.utcoffset().total_seconds() == 3600  # +1 hour (CET)
