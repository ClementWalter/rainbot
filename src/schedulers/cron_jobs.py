"""Scheduled jobs for the RainBot booking service.

This module contains the main scheduled tasks:
- booking_job: Attempts to book tennis courts for users with active requests
- send_reminder: Sends reminders to users and partners on match day
"""

import asyncio
import logging
import uuid

from src.models.booking import Booking
from src.models.booking_request import BookingRequest
from src.models.user import User
from src.services.bookings_db import bookings_service
from src.services.google_sheets import sheets_service
from src.services.locks_db import locks_service
from src.services.logs_db import logs_service
from src.services.notification import NotificationService, get_notification_service
from src.services.notifications_db import notifications_service
from src.services.paris_tennis import (
    BookingResult,
    CourtSlot,
    create_paris_tennis_session,
)
from src.services.requests_db import requests_service as requests_db_service
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
    Run the main booking job on a schedule.

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
    asyncio.run(_booking_job_async())


async def _pre_check_availability(
    requests: list[BookingRequest],
) -> list[BookingRequest]:
    """
    Check availability for all requests WITHOUT logging in.

    Uses a single browser session for efficiency.
    Returns only requests that have potential availability.

    This is a cost-saving optimization: we skip login (and CAPTCHA solving)
    when no slots are available. The check is done without authentication
    since the search page is publicly accessible.
    """
    if not requests:
        return []

    results: dict[str, bool] = {}  # request_id -> has_availability

    try:
        async with create_paris_tennis_session() as tennis_service:
            # Group by (target_date, day_of_week) to avoid duplicate checks
            checked_dates: dict[int, bool] = {}  # day_of_week -> has_any_slots

            for request in requests:
                day = request.day_of_week.value

                if day in checked_dates:
                    # Reuse result from same day
                    results[request.id] = checked_dates[day]
                    continue

                # Get target date for logging
                target_date = tennis_service._get_next_booking_date(day)
                day_name = DAY_OF_WEEK_FRENCH.get(day, f"day_{day}")
                facilities_str = (
                    ", ".join(request.facility_preferences)
                    if request.facility_preferences
                    else "all"
                )

                logger.info(
                    f"Pre-check [{request.id[:8]}]: {day_name} {target_date.strftime('%Y-%m-%d')} "
                    f"{request.time_start}-{request.time_end} | facilities: {facilities_str}"
                )

                has_slots, count = await tennis_service.check_availability_quick(request)
                checked_dates[day] = has_slots
                results[request.id] = has_slots

                logger.info(
                    f"Pre-check [{request.id[:8]}] result: has_slots={has_slots}, count={count}"
                )

    except Exception as e:
        logger.warning(f"Pre-check phase failed: {e}, proceeding with all requests")
        return requests  # Fail open

    return [req for req in requests if results.get(req.id, True)]


async def _booking_job_async() -> None:
    """Async implementation of the booking job."""
    # Generate unique job ID for this execution to manage locks
    job_id = str(uuid.uuid4())
    logger.info(f"Starting booking job (job_id: {job_id})")

    try:
        # Get services
        sheets = sheets_service
        notification = get_notification_service()

        # Get all active booking requests from SQLite
        active_requests = requests_db_service.get_active_booking_requests()
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

        if not requests_to_process:
            return

        # Filter out requests without facility preferences (required for pre-check)
        valid_requests = []
        for req in requests_to_process:
            if not req.facility_preferences:
                logger.warning(
                    f"Skipping request {req.id} - no facility preferences " f"(user: {req.user_id})"
                )
            else:
                valid_requests.append(req)

        if not valid_requests:
            logger.info("No valid requests with facility preferences to process")
            return

        requests_to_process = valid_requests

        # === Pre-check phase (no login) ===
        # Check availability WITHOUT login to save on CAPTCHA costs
        requests_with_availability = await _pre_check_availability(requests_to_process)

        if not requests_with_availability:
            logger.info("No availability found for any requests, skipping all logins")
            return

        logger.info(
            f"Pre-check: {len(requests_with_availability)}/{len(requests_to_process)} "
            "requests have potential availability"
        )

        # === Existing logic for requests with availability ===
        requests_by_user: dict[str, list[BookingRequest]] = {}
        for request in requests_with_availability:
            requests_by_user.setdefault(request.user_id, []).append(request)

        for user_id, user_requests in requests_by_user.items():
            user = user_map.get(user_id)
            if not user:
                logger.warning(f"User {user_id} not found for requests")
                continue

            # Try to acquire lock for this user to prevent concurrent processing
            if not locks_service.acquire_user_lock(user.id, job_id):
                logger.info(
                    f"Could not acquire lock for user {user.id}, "
                    "skipping requests (another job is processing)"
                )
                continue

            try:
                # Check if user already has a pending booking (after acquiring lock)
                if bookings_service.has_pending_booking(user.id):
                    logger.info(f"User {user.id} already has a pending booking, skipping requests")
                    continue

                # Process booking requests for this user until one succeeds
                for request in user_requests:
                    logger.info(f"Processing booking request {request.id} for user {user.id}")
                    if await _process_booking_request_async(user, request, notification):
                        logger.info(
                            f"Booking completed for user {user.id}, skipping remaining requests"
                        )
                        break
            finally:
                # Always release the lock when done
                locks_service.release_user_lock(user.id, job_id)

    except Exception as e:
        logger.error(f"Booking job failed with error: {e}", exc_info=True)

    logger.info(f"Booking job completed (job_id: {job_id})")


async def _process_booking_request_async(
    user: User,
    request: BookingRequest,
    notification: NotificationService,
) -> bool:
    """
    Process a single booking request for a user.

    Args:
        user: The user making the booking
        request: The booking request to process
        notification: Notification service for sending emails

    Returns:
        True if a booking was successfully completed, False otherwise.

    """
    try:
        # Log what we're about to book
        target_date = None  # Will be computed by tennis_service
        day_name = DAY_OF_WEEK_FRENCH.get(request.day_of_week.value, request.day_of_week.name)
        facilities_str = (
            ", ".join(request.facility_preferences) if request.facility_preferences else "any"
        )
        logger.info(
            f"Processing [{request.id[:8]}] for {user.email}: "
            f"{day_name} {request.time_start}-{request.time_end} | "
            f"facilities: {facilities_str} | court_type: {request.court_type.value}"
        )

        async with create_paris_tennis_session() as tennis_service:
            # Compute target date for logging
            target_date = tennis_service._get_next_booking_date(request.day_of_week.value)
            logger.info(
                f"Logging in for {user.email} to book {target_date.strftime('%Y-%m-%d')} "
                f"({day_name} {request.time_start}-{request.time_end})"
            )
            login_success = await tennis_service.login(
                user.paris_tennis_email, user.paris_tennis_password
            )

            if not login_success:
                logger.error(f"Login failed for user {user.email}")
                logs_service.log_error(
                    user.id,
                    "Connexion au site Paris Tennis echouee",
                    request_id=request.id,
                )
                notification.send_booking_failure_notification(
                    user,
                    "Impossible de se connecter au site Paris Tennis. "
                    "Veuillez vérifier vos identifiants.",
                )
                return False

            # Search for available courts
            logger.info(
                f"Searching courts: {target_date.strftime('%Y-%m-%d')} "
                f"{request.time_start}-{request.time_end} | facilities: {facilities_str}"
            )
            available_slots = await tennis_service.search_available_courts(request)

            if not available_slots:
                logger.info(
                    f"No slots found for {target_date.strftime('%Y-%m-%d')} "
                    f"{request.time_start}-{request.time_end}"
                )
                logs_service.log_info(
                    user.id,
                    "Aucun creneau disponible trouve",
                    request_id=request.id,
                )
                # Send informational notification to user (only once per target date)
                # Get the target date for this booking request
                target_date = tennis_service._get_next_booking_date(request.day_of_week.value)
                target_date_str = target_date.strftime("%Y-%m-%d")

                # Check if we already sent a notification for this request/date
                if not notifications_service.was_no_slots_notification_sent(
                    request.id, target_date_str
                ):
                    day_name = DAY_OF_WEEK_FRENCH.get(
                        request.day_of_week.value, request.day_of_week.name.lower()
                    )
                    time_range = f"{request.time_start} - {request.time_end}"
                    notification_result = notification.send_no_slots_notification(
                        user,
                        day_of_week=day_name,
                        time_range=time_range,
                        facility_names=request.facility_preferences or None,
                    )
                    if getattr(notification_result, "success", False):
                        # Mark that we sent this notification
                        notifications_service.mark_no_slots_notification_sent(
                            request.id, target_date_str
                        )
                    else:
                        logger.warning(
                            "Failed to send no slots notification for request %s: %s",
                            request.id,
                            getattr(notification_result, "error_message", "unknown error"),
                        )
                else:
                    logger.debug(
                        f"No slots notification already sent for request {request.id}, "
                        f"date {target_date_str}"
                    )
                return False

            logger.info(f"Found {len(available_slots)} available slots")
            logs_service.log_info(
                user.id,
                f"{len(available_slots)} creneau(x) disponible(s) trouve(s)",
                request_id=request.id,
            )

            # Try to book the first available slot
            for slot in available_slots:
                logger.info(
                    f"Attempting to book: {slot.facility_name} "
                    f"court {slot.court_number} at {slot.time_start}"
                )

                result = await tennis_service.book_court(
                    slot,
                    partner_name=request.partner_name,
                    partner_email=request.partner_email,
                    player_name=user.name,
                    player_email=user.email,
                )

                if result.success:
                    logger.info(f"Booking successful! Confirmation: {result.confirmation_id}")
                    logs_service.log_success(
                        user.id,
                        f"Reservation confirmee: {slot.facility_name} a {slot.time_start}",
                        request_id=request.id,
                        facility_name=slot.facility_name,
                        details={
                            "confirmation_id": result.confirmation_id,
                            "court": slot.court_number,
                        },
                    )

                    # Create booking record
                    booking = _create_booking_from_result(user, request, slot, result)

                    # Save to SQLite database
                    if bookings_service.add_booking(booking):
                        logger.info(f"Booking {booking.id} saved to database")
                    else:
                        logger.error(f"Failed to save booking {booking.id} to database")

                    # Decrement carnet balance if tracked for the user
                    if user.carnet_balance is not None:
                        new_balance = max(user.carnet_balance - 1, 0)
                        if sheets_service.update_user_carnet_balance(user.id, new_balance):
                            user.carnet_balance = new_balance
                        else:
                            logger.warning(
                                "Failed to update carnet balance for user %s after booking",
                                user.id,
                            )

                    # Send confirmation notification
                    notification.send_booking_confirmation(user, booking)
                    if booking.partner_email:
                        notification.send_partner_booking_confirmation(user, booking)
                    return True

                logger.warning(f"Booking failed for slot: {result.error_message}")

            # All slots failed
            logger.warning(f"Failed to book any available slot for request {request.id}")
            notification.send_booking_failure_notification(
                user,
                "Tous les créneaux disponibles ont été réservés par d'autres utilisateurs.",
                facility_name=available_slots[0].facility_name if available_slots else None,
            )
            return False

    except Exception as e:
        logger.error(f"Error processing booking request {request.id}: {e}", exc_info=True)
        try:
            notification.send_booking_failure_notification(
                user,
                f"Une erreur technique s'est produite: {str(e)}",
            )
        except Exception as notify_error:
            logger.error(f"Failed to send failure notification: {notify_error}")
        return False

    return False


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

    This job runs periodically to remove outdated records from SQLite.
    """
    logger.info("Starting cleanup old notifications job")

    try:
        deleted_count = notifications_service.cleanup_old_notifications(days_to_keep=7)
        logger.info(f"Cleanup completed: removed {deleted_count} old notification records")
        # Also cleanup expired locks
        locks_service.cleanup_expired_locks()
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
        notification = get_notification_service()

        # Check if notification service is configured
        if not notification.is_configured():
            logger.warning("Notification service not configured, skipping reminders")
            return

        # Get today's bookings from SQLite
        todays_bookings = bookings_service.get_todays_bookings()
        logger.info(f"Found {len(todays_bookings)} bookings for today")

        if not todays_bookings:
            logger.info("No bookings scheduled for today")
            return

        # Get all users for lookups (still from Google Sheets)
        all_users = sheets_service.get_all_users()
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
