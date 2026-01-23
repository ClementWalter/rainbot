# coding=UTF-8
import http.client
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

from src.schedulers.cron_jobs import (  # noqa: E402
    booking_job,
    cleanup_old_notifications,
    send_reminder,
)
from src.utils.timezone import PARIS_TZ  # noqa: E402

http.client._MAXHEADERS = 1000  # type: ignore
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("apscheduler").setLevel(logging.ERROR)
# Enable DEBUG for captcha solver to debug hanging issues
logging.getLogger("src.services.captcha_solver").setLevel(logging.DEBUG)

# Scheduler configuration
JITTER = int(os.getenv("JITTER", 0))
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", 8))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", 0))
REMINDER_SECOND = int(os.getenv("REMINDER_SECOND", 0))


def build_scheduler(scheduler_factory=BlockingScheduler) -> BlockingScheduler:
    """Create and configure the APScheduler instance.

    Two polling strategies:
    1. Normal polling: every 30 seconds to check availability
    2. Intensive polling around 8am Paris time: every 2 seconds from 7:59:50 to 8:00:30
       (this is when the booking window opens for slots 6 days ahead)
    """
    scheduler = scheduler_factory(timezone=PARIS_TZ)

    # Strategy 1: Normal polling every 30 seconds
    scheduler.add_job(
        booking_job,
        "interval",
        seconds=30,
        jitter=JITTER,
    )

    # Strategy 2: Intensive polling around 8:00 AM Paris time
    # From 7:59:50 to 8:00:30 (every 2 seconds = 20 polling attempts)

    # 7:59:50 to 7:59:58 (5 jobs at seconds 50, 52, 54, 56, 58)
    for second in range(50, 60, 2):
        scheduler.add_job(
            booking_job,
            "cron",
            hour=7,
            minute=59,
            second=second,
        )

    # 8:00:00 to 8:00:30 (16 jobs at seconds 0, 2, 4, ..., 30)
    for second in range(0, 32, 2):
        scheduler.add_job(
            booking_job,
            "cron",
            hour=8,
            minute=0,
            second=second,
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
