"""Scheduled jobs for the RainBot booking service.

This module contains the main scheduled tasks:
- booking_job: Attempts to book tennis courts for users with active requests
- send_reminder: Sends reminders to users and partners on match day
"""

import logging
import uuid

from src.models.booking import Booking
from src.models.booking_request import BookingRequest
from src.models.user import User
from src.services.google_sheets import GoogleSheetsService, sheets_service
from src.services.notification import NotificationService, get_notification_service
from src.services.paris_tennis import (
    BookingResult,
    CourtSlot,
    create_paris_tennis_session,
)
from src.utils.timezone import now_paris

logger = logging.getLogger(__name__)

# French day of week names
DAY_OF_WEEK_FRENCH = {
    0: "lundi",
    1: "mardi",
    2: "mercredi",
    3: "jeudi",
    4: "vendredi",
    5: "samedi",
    6: "dimanche",
}


def booking_job() -> None:
    """
    Main booking job that runs on a schedule.

    This job:
    1. Fetches all active booking requests from the data source
    2. For each eligible user (paid subscription, active request):
       a. Acquires a lock to prevent concurrent processing
       b. Checks if user already has a pending booking
       c. Searches for available courts matching their preferences
       d. Attempts to book the first matching court
       e. Handles CAPTCHA verification
       f. Sends confirmation notification on success
       g. Releases the lock
    """
    # Generate unique job ID for this execution to manage locks
    job_id = str(uuid.uuid4())
    logger.info(f"Starting booking job (job_id: {job_id})")

    try:
        # Get services
        sheets = sheets_service
        notification = get_notification_service()

        # Get all active booking requests
        active_requests = sheets.get_active_booking_requests()
        logger.info(f"Found {len(active_requests)} active booking requests")

        if not active_requests:
            logger.info("No active booking requests to process")
            return

        # Get all eligible users
        eligible_users = sheets.get_eligible_users()
        eligible_user_ids = {user.id for user in eligible_users}
        user_map = {user.id: user for user in eligible_users}
        logger.info(f"Found {len(eligible_users)} eligible users")

        # Filter requests to only those from eligible users
        requests_to_process = [req for req in active_requests if req.user_id in eligible_user_ids]
        logger.info(f"Processing {len(requests_to_process)} requests from eligible users")

        for request in requests_to_process:
            user = user_map.get(request.user_id)
            if not user:
                logger.warning(f"User {request.user_id} not found for request {request.id}")
                continue

            # Try to acquire lock for this user to prevent concurrent processing
            if not sheets.acquire_user_lock(user.id, job_id):
                logger.info(
                    f"Could not acquire lock for user {user.id}, "
                    f"skipping request {request.id} (another job is processing)"
                )
                continue

            try:
                # Check if user already has a pending booking (after acquiring lock)
                if sheets.has_pending_booking(user.id):
                    logger.info(
                        f"User {user.id} already has a pending booking, skipping request {request.id}"
                    )
                    continue

                # Process this booking request
                logger.info(f"Processing booking request {request.id} for user {user.id}")
                _process_booking_request(user, request, sheets, notification)
            finally:
                # Always release the lock when done
                sheets.release_user_lock(user.id, job_id)

    except Exception as e:
        logger.error(f"Booking job failed with error: {e}", exc_info=True)

    logger.info(f"Booking job completed (job_id: {job_id})")


def _process_booking_request(
    user: User,
    request: BookingRequest,
    sheets: GoogleSheetsService,
    notification: NotificationService,
) -> None:
    """
    Process a single booking request for a user.

    Args:
        user: The user making the booking
        request: The booking request to process
        sheets: Google Sheets service for data persistence
        notification: Notification service for sending emails
    """
    try:
        with create_paris_tennis_session() as tennis_service:
            # Login to Paris Tennis
            logger.info(f"Logging in for user {user.email}")
            login_success = tennis_service.login(
                user.paris_tennis_email, user.paris_tennis_password
            )

            if not login_success:
                logger.error(f"Login failed for user {user.email}")
                notification.send_booking_failure_notification(
                    user,
                    "Impossible de se connecter au site Paris Tennis. "
                    "Veuillez vérifier vos identifiants.",
                )
                return

            # Search for available courts
            logger.info(f"Searching for courts matching request {request.id}")
            available_slots = tennis_service.search_available_courts(request)

            if not available_slots:
                logger.info(f"No available slots found for request {request.id}")
                # Send informational notification to user (only once per target date)
                # Get the target date for this booking request
                target_date = tennis_service._get_next_booking_date(request.day_of_week.value)
                target_date_str = target_date.strftime("%Y-%m-%d")

                # Check if we already sent a notification for this request/date
                if not sheets.was_no_slots_notification_sent(request.id, target_date_str):
                    day_name = DAY_OF_WEEK_FRENCH.get(
                        request.day_of_week.value, request.day_of_week.name.lower()
                    )
                    time_range = f"{request.time_start} - {request.time_end}"
                    notification.send_no_slots_notification(
                        user,
                        day_of_week=day_name,
                        time_range=time_range,
                        facility_names=request.facility_preferences or None,
                    )
                    # Mark that we sent this notification
                    sheets.mark_no_slots_notification_sent(request.id, target_date_str)
                else:
                    logger.debug(
                        f"No slots notification already sent for request {request.id}, "
                        f"date {target_date_str}"
                    )
                return

            logger.info(f"Found {len(available_slots)} available slots")

            # Try to book the first available slot
            for slot in available_slots:
                logger.info(
                    f"Attempting to book: {slot.facility_name} "
                    f"court {slot.court_number} at {slot.time_start}"
                )

                result = tennis_service.book_court(slot, request.partner_name)

                if result.success:
                    logger.info(f"Booking successful! Confirmation: {result.confirmation_id}")

                    # Create booking record
                    booking = _create_booking_from_result(user, request, slot, result)

                    # Save to Google Sheets
                    if sheets.add_booking(booking):
                        logger.info(f"Booking {booking.id} saved to spreadsheet")
                    else:
                        logger.error(f"Failed to save booking {booking.id} to spreadsheet")

                    # Send confirmation notification
                    notification.send_booking_confirmation(user, booking)
                    return

                logger.warning(f"Booking failed for slot: {result.error_message}")

            # All slots failed
            logger.warning(f"Failed to book any available slot for request {request.id}")
            notification.send_booking_failure_notification(
                user,
                "Tous les créneaux disponibles ont été réservés par d'autres utilisateurs.",
                facility_name=available_slots[0].facility_name if available_slots else None,
            )

    except Exception as e:
        logger.error(f"Error processing booking request {request.id}: {e}", exc_info=True)
        try:
            notification.send_booking_failure_notification(
                user,
                f"Une erreur technique s'est produite: {str(e)}",
            )
        except Exception as notify_error:
            logger.error(f"Failed to send failure notification: {notify_error}")


def _create_booking_from_result(
    user: User,
    request: BookingRequest,
    slot: CourtSlot,
    result: BookingResult,
) -> Booking:
    """
    Create a Booking object from a successful booking result.

    Args:
        user: The user who made the booking
        request: The booking request
        slot: The court slot that was booked
        result: The booking result with confirmation

    Returns:
        Booking object ready to be saved
    """
    return Booking(
        id=str(uuid.uuid4()),
        user_id=user.id,
        request_id=request.id,
        facility_name=slot.facility_name,
        facility_code=slot.facility_code,
        court_number=slot.court_number,
        date=slot.date,
        time_start=slot.time_start,
        time_end=slot.time_end,
        partner_name=request.partner_name,
        partner_email=request.partner_email,
        confirmation_id=result.confirmation_id,
        facility_address=slot.facility_address,
        created_at=now_paris(),
    )


def cleanup_old_notifications() -> None:
    """
    Clean up old no-slots notification tracking records.

    This job runs periodically to remove outdated records from the
    NoSlotsNotifications sheet, keeping the spreadsheet manageable.
    """
    logger.info("Starting cleanup old notifications job")

    try:
        sheets = sheets_service
        deleted_count = sheets.cleanup_old_no_slots_notifications(days_to_keep=7)
        logger.info(f"Cleanup completed: removed {deleted_count} old notification records")
    except Exception as e:
        logger.error(f"Cleanup job failed with error: {e}", exc_info=True)

    logger.info("Cleanup old notifications job completed")


def send_reminder() -> None:
    """
    Send match day reminders to users and their partners.

    This job runs daily (typically in the morning) and:
    1. Finds all bookings scheduled for today
    2. Sends reminder notifications to both the user and their partner
    """
    logger.info("Starting send reminder job")

    try:
        # Get services
        sheets = sheets_service
        notification = get_notification_service()

        # Check if notification service is configured
        if not notification.is_configured():
            logger.warning("Notification service not configured, skipping reminders")
            return

        # Get today's bookings
        todays_bookings = sheets.get_todays_bookings()
        logger.info(f"Found {len(todays_bookings)} bookings for today")

        if not todays_bookings:
            logger.info("No bookings scheduled for today")
            return

        # Get all users for lookups
        all_users = sheets.get_all_users()
        user_map = {user.id: user for user in all_users}

        for booking in todays_bookings:
            user = user_map.get(booking.user_id)
            if not user:
                logger.warning(f"User {booking.user_id} not found for booking {booking.id}")
                continue

            # Send reminder to the user
            logger.info(f"Sending reminder to user {user.email} for booking {booking.id}")
            user_result = notification.send_match_day_reminder(
                recipient_email=user.email,
                recipient_name=user.name,
                booking=booking,
                is_partner=False,
            )

            if user_result.success:
                logger.info(f"User reminder sent successfully to {user.email}")
            else:
                logger.error(f"Failed to send user reminder: {user_result.error_message}")

            # Send reminder to the partner if email is available
            # partner_email is stored on the booking to ensure reminders work
            # even if the booking request is modified or deleted after booking
            if booking.partner_email:
                logger.info(
                    f"Sending reminder to partner {booking.partner_email} for booking {booking.id}"
                )
                partner_result = notification.send_match_day_reminder(
                    recipient_email=booking.partner_email,
                    recipient_name=booking.partner_name,
                    booking=booking,
                    is_partner=True,
                    player_name=user.name,
                )

                if partner_result.success:
                    logger.info(f"Partner reminder sent successfully to {booking.partner_email}")
                else:
                    logger.error(f"Failed to send partner reminder: {partner_result.error_message}")
            else:
                logger.debug(
                    f"No partner email for booking {booking.id}, skipping partner reminder"
                )

    except Exception as e:
        logger.error(f"Send reminder job failed with error: {e}", exc_info=True)

    logger.info("Send reminder job completed")
