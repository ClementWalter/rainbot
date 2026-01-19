# coding=UTF-8
import http.client
import logging
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

from src.schedulers.cron_jobs import booking_job, send_reminder
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


if __name__ == "__main__":
    logging.info("Rainbot started")
    scheduler = BlockingScheduler(timezone=PARIS_TZ)
    scheduler.add_job(
        booking_job, "interval", hours=HOUR, minutes=MINUTE, seconds=SECOND, jitter=JITTER
    )
    # Schedule booking job at 8:00 AM Paris time (every 2 seconds for first 10 seconds)
    for second in range(0, 10, 2):
        scheduler.add_job(
            booking_job, "cron", hour=8, second=second, jitter=JITTER
        )
    # Schedule reminder job at 2:00 AM Paris time daily
    scheduler.add_job(send_reminder, "cron", hour=2)
    scheduler.start()
