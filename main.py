# coding=UTF-8
import http.client
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

from src.schedulers.cron_jobs import (
    booking_job,
    cleanup_old_notifications,
    send_reminder,
)
from src.utils.timezone import PARIS_TZ

http.client._MAXHEADERS = 1000  # type: ignore
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("apscheduler").setLevel(logging.ERROR)

# Cron info
HOUR = int(os.getenv("HOUR", 0))
MINUTE = int(os.getenv("MINUTE", 0))
SECOND = int(os.getenv("SECOND", 10))
JITTER = int(os.getenv("JITTER", 0))
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", 8))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", 0))
REMINDER_SECOND = int(os.getenv("REMINDER_SECOND", 0))


def _normalize_interval(hours: int, minutes: int, seconds: int) -> tuple[int, int, int]:
    """Normalize interval values to a positive schedule."""
    if hours < 0 or minutes < 0 or seconds < 0:
        logging.warning("Interval values must be non-negative; clamping to 0.")
    hours = max(hours, 0)
    minutes = max(minutes, 0)
    seconds = max(seconds, 0)
    if hours == 0 and minutes == 0 and seconds == 0:
        logging.warning("Interval cannot be all zeros; defaulting to 10 seconds.")
        seconds = 10
    return hours, minutes, seconds


def build_scheduler(scheduler_factory=BlockingScheduler) -> BlockingScheduler:
    """Create and configure the APScheduler instance."""
    interval_hours, interval_minutes, interval_seconds = _normalize_interval(HOUR, MINUTE, SECOND)
    scheduler = scheduler_factory(timezone=PARIS_TZ)
    scheduler.add_job(
        booking_job,
        "interval",
        hours=interval_hours,
        minutes=interval_minutes,
        seconds=interval_seconds,
        jitter=JITTER,
    )
    # Schedule booking job at 8:00 AM Paris time (every 2 seconds for first 10 seconds)
    for second in range(0, 10, 2):
        scheduler.add_job(
            booking_job,
            "cron",
            hour=8,
            minute=0,
            second=second,
            jitter=JITTER,
        )
    # Schedule reminder job in the morning of match day (configurable)
    scheduler.add_job(
        send_reminder,
        "cron",
        hour=REMINDER_HOUR,
        minute=REMINDER_MINUTE,
        second=REMINDER_SECOND,
    )
    # Schedule cleanup job at 3:00 AM Paris time daily
    scheduler.add_job(cleanup_old_notifications, "cron", hour=3)
    return scheduler


if __name__ == "__main__":
    logging.info("Rainbot started")
    scheduler = build_scheduler()
    scheduler.start()
