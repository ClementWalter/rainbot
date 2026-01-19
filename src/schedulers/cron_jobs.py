"""Scheduled jobs for the RainBot booking service.

This module contains the main scheduled tasks:
- booking_job: Attempts to book tennis courts for users with active requests
- send_remainder: Sends reminders to users and partners on match day
"""

import logging

logger = logging.getLogger(__name__)


def booking_job() -> None:
    """
    Main booking job that runs on a schedule.

    This job:
    1. Fetches all active booking requests from the data source
    2. For each eligible user (paid subscription, active request):
       a. Searches for available courts matching their preferences
       b. Attempts to book the first matching court
       c. Handles CAPTCHA verification
       d. Sends confirmation notification on success
    """
    logger.info("Starting booking job")

    # TODO: Implement the following steps:
    # 1. Load active booking requests from Google Sheets
    # 2. Filter for eligible users (paid subscription, active status)
    # 3. For each request:
    #    - Check if user already has a pending booking
    #    - Search for available courts matching preferences
    #    - Attempt booking with CAPTCHA solving
    #    - Send notification on success/failure

    logger.info("Booking job completed")


def send_remainder() -> None:
    """
    Send match day reminders to users and their partners.

    This job runs daily (typically in the morning) and:
    1. Finds all bookings scheduled for today
    2. Sends reminder notifications to both the user and their partner
    """
    logger.info("Starting send reminder job")

    # TODO: Implement the following steps:
    # 1. Load today's bookings from the data source
    # 2. For each booking:
    #    - Send reminder to the user
    #    - Send reminder to the partner (if partner email/phone available)

    logger.info("Send reminder job completed")
