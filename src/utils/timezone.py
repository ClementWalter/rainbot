"""Timezone utilities for RainBot.

All date/time operations should use Paris timezone since the service
is for Paris municipal tennis facilities.
"""

from datetime import date, datetime

import pytz

# Paris timezone constant
PARIS_TZ = pytz.timezone("Europe/Paris")


def now_paris() -> datetime:
    """
    Get the current datetime in Paris timezone.

    Returns:
        Timezone-aware datetime in Europe/Paris timezone

    """
    return datetime.now(PARIS_TZ)


def today_paris() -> date:
    """
    Get today's date in Paris timezone.

    Returns:
        Date object for today in Paris timezone

    """
    return now_paris().date()


def today_weekday_paris() -> int:
    """
    Get today's day of week in Paris timezone.

    Returns:
        Integer day of week (0=Monday, 6=Sunday)

    """
    return now_paris().weekday()
