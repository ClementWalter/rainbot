"""Notification service for sending booking confirmations and reminders.

This module provides email notification functionality for RainBot,
including booking confirmations and match day reminders.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.config.settings import settings
from src.models.booking import Booking
from src.models.user import User

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""

    success: bool
    error_message: Optional[str] = None


class NotificationService:
    """
    Service for sending email notifications.

    Supports:
    - Booking confirmation emails to users
    - Match day reminders to users and their partners
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        from_email: Optional[str] = None,
    ):
        """
        Initialize the notification service.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP authentication username
            smtp_password: SMTP authentication password
            from_email: Email address to send from
        """
        self.smtp_host = smtp_host or settings.notification.smtp_host
        self.smtp_port = smtp_port or settings.notification.smtp_port or 587
        self.smtp_user = smtp_user or settings.notification.smtp_user
        self.smtp_password = smtp_password or settings.notification.smtp_password
        self.from_email = from_email or settings.notification.from_email

    def is_configured(self) -> bool:
        """Check if the notification service is properly configured."""
        return all([
            self.smtp_host,
            self.smtp_port,
            self.smtp_user,
            self.smtp_password,
            self.from_email,
        ])

    def _create_smtp_connection(self) -> smtplib.SMTP:
        """Create and authenticate SMTP connection."""
        smtp = smtplib.SMTP(self.smtp_host, self.smtp_port)
        smtp.starttls()
        smtp.login(self.smtp_user, self.smtp_password)
        return smtp

    def _send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
    ) -> NotificationResult:
        """
        Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            body_html: HTML body content
            body_text: Plain text body (optional, derived from HTML if not provided)

        Returns:
            NotificationResult with success status
        """
        if not self.is_configured():
            logger.error("Notification service not configured")
            return NotificationResult(
                success=False,
                error_message="SMTP settings not configured",
            )

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = to_email

            # Plain text version
            if body_text is None:
                # Strip HTML tags for plain text version
                import re
                body_text = re.sub(r"<[^>]+>", "", body_html)
                body_text = re.sub(r"\s+", " ", body_text).strip()

            msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            with self._create_smtp_connection() as smtp:
                smtp.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return NotificationResult(success=True)

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return NotificationResult(
                success=False,
                error_message="SMTP authentication failed",
            )
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return NotificationResult(
                success=False,
                error_message=f"SMTP error: {e}",
            )
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return NotificationResult(
                success=False,
                error_message=str(e),
            )

    def send_booking_confirmation(
        self,
        user: User,
        booking: Booking,
    ) -> NotificationResult:
        """
        Send a booking confirmation email to the user.

        Args:
            user: The user who made the booking
            booking: The completed booking details

        Returns:
            NotificationResult with success status
        """
        subject = f"🎾 RainBot - Réservation confirmée pour le {booking.date.strftime('%d/%m/%Y')}"

        greeting = f"Bonjour {user.name}" if user.name else "Bonjour"

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #2e7d32;">✅ Réservation confirmée !</h2>

            <p>{greeting},</p>

            <p>Votre réservation de tennis a été effectuée avec succès.</p>

            <div style="background-color: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #1976d2;">📋 Détails de la réservation</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;"><strong>Date :</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;">{booking.date.strftime('%A %d %B %Y')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;"><strong>Horaire :</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;">{booking.time_start} - {booking.time_end}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;"><strong>Centre :</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;">{booking.facility_name}</td>
                    </tr>
                    {f'<tr><td style="padding: 8px 0; border-bottom: 1px solid #ddd;"><strong>Adresse :</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #ddd;">{booking.facility_address}</td></tr>' if booking.facility_address else ''}
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;"><strong>Court :</strong></td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #ddd;">{booking.court_number}</td>
                    </tr>
                    {f'<tr><td style="padding: 8px 0; border-bottom: 1px solid #ddd;"><strong>Partenaire :</strong></td><td style="padding: 8px 0; border-bottom: 1px solid #ddd;">{booking.partner_name}</td></tr>' if booking.partner_name else ''}
                    {f'<tr><td style="padding: 8px 0;"><strong>N° de confirmation :</strong></td><td style="padding: 8px 0;">{booking.confirmation_id}</td></tr>' if booking.confirmation_id else ''}
                </table>
            </div>

            <p style="color: #666;">N'oubliez pas d'apporter votre raquette et de l'eau ! 🎾💧</p>

            <p>À bientôt sur les courts,<br>
            <strong>L'équipe RainBot</strong></p>

            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            <p style="color: #999; font-size: 12px;">
                Cet email a été envoyé automatiquement par RainBot.
            </p>
        </body>
        </html>
        """

        logger.info(f"Sending booking confirmation to {user.email}")
        return self._send_email(user.email, subject, body_html)

    def send_match_day_reminder(
        self,
        recipient_email: str,
        recipient_name: Optional[str],
        booking: Booking,
        is_partner: bool = False,
        player_name: Optional[str] = None,
    ) -> NotificationResult:
        """
        Send a match day reminder email.

        Args:
            recipient_email: Email address to send to
            recipient_name: Name of the recipient (for personalization)
            booking: The booking details
            is_partner: Whether this is being sent to the partner
            player_name: Name of the user who made the booking (used when sending to partner)

        Returns:
            NotificationResult with success status
        """
        subject = f"🎾 Rappel : Tennis aujourd'hui à {booking.time_start}"

        greeting = f"Bonjour {recipient_name}" if recipient_name else "Bonjour"

        if is_partner:
            # When sending to the partner, show who they're playing with (the user who booked)
            playing_with = player_name or "votre partenaire"
            intro_text = f"Vous avez un match de tennis prévu aujourd'hui avec {playing_with}."
        else:
            partner_info = f" avec {booking.partner_name}" if booking.partner_name else ""
            intro_text = f"Vous avez un match de tennis prévu aujourd'hui{partner_info}."

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #ff9800;">⏰ Rappel - Match aujourd'hui !</h2>

            <p>{greeting},</p>

            <p>{intro_text}</p>

            <div style="background-color: #fff3e0; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ff9800;">
                <h3 style="margin-top: 0; color: #e65100;">📍 Votre réservation</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0;"><strong>🕐 Horaire :</strong></td>
                        <td style="padding: 8px 0; font-size: 18px; font-weight: bold;">{booking.time_start} - {booking.time_end}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0;"><strong>📍 Centre :</strong></td>
                        <td style="padding: 8px 0;">{booking.facility_name}</td>
                    </tr>
                    {f'<tr><td style="padding: 8px 0;"><strong>🗺️ Adresse :</strong></td><td style="padding: 8px 0;">{booking.facility_address}</td></tr>' if booking.facility_address else ''}
                    <tr>
                        <td style="padding: 8px 0;"><strong>🎾 Court :</strong></td>
                        <td style="padding: 8px 0;">{booking.court_number}</td>
                    </tr>
                </table>
            </div>

            <div style="background-color: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;"><strong>📝 Checklist :</strong></p>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    <li>Raquette 🎾</li>
                    <li>Tenue de sport 👟</li>
                    <li>Bouteille d'eau 💧</li>
                    <li>Serviette</li>
                </ul>
            </div>

            <p>Bon match ! 🏆</p>

            <p>Sportivement,<br>
            <strong>L'équipe RainBot</strong></p>

            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            <p style="color: #999; font-size: 12px;">
                Cet email a été envoyé automatiquement par RainBot.
            </p>
        </body>
        </html>
        """

        logger.info(f"Sending match day reminder to {recipient_email}")
        return self._send_email(recipient_email, subject, body_html)

    def send_booking_failure_notification(
        self,
        user: User,
        error_message: str,
        facility_name: Optional[str] = None,
        requested_date: Optional[str] = None,
    ) -> NotificationResult:
        """
        Send a notification when booking fails.

        Args:
            user: The user whose booking failed
            error_message: Description of what went wrong
            facility_name: The facility that was attempted
            requested_date: The date that was requested

        Returns:
            NotificationResult with success status
        """
        subject = "🎾 RainBot - Échec de réservation"

        greeting = f"Bonjour {user.name}" if user.name else "Bonjour"

        details = ""
        if facility_name:
            details += f"<li>Centre demandé : {facility_name}</li>"
        if requested_date:
            details += f"<li>Date demandée : {requested_date}</li>"

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #d32f2f;">❌ Réservation non effectuée</h2>

            <p>{greeting},</p>

            <p>Malheureusement, nous n'avons pas pu effectuer votre réservation de tennis.</p>

            <div style="background-color: #ffebee; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #d32f2f;">
                <p style="margin: 0 0 10px 0;"><strong>Raison :</strong></p>
                <p style="margin: 0; color: #c62828;">{error_message}</p>
            </div>

            {f'<div style="background-color: #f5f5f5; padding: 15px; border-radius: 8px; margin: 20px 0;"><p style="margin: 0 0 10px 0;"><strong>Détails de la demande :</strong></p><ul style="margin: 0; padding-left: 20px;">{details}</ul></div>' if details else ''}

            <p>Le système réessayera automatiquement lors de la prochaine exécution.</p>

            <p>Cordialement,<br>
            <strong>L'équipe RainBot</strong></p>

            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            <p style="color: #999; font-size: 12px;">
                Cet email a été envoyé automatiquement par RainBot.
            </p>
        </body>
        </html>
        """

        logger.info(f"Sending booking failure notification to {user.email}")
        return self._send_email(user.email, subject, body_html)

    def send_no_slots_notification(
        self,
        user: User,
        day_of_week: str,
        time_range: str,
        facility_names: Optional[list[str]] = None,
    ) -> NotificationResult:
        """
        Send a notification when no slots are available.

        This is an informational notification (not an error) that tells
        the user the system searched but no matching slots were found.

        Args:
            user: The user whose booking request had no matching slots
            day_of_week: The day of week being searched (e.g., "lundi")
            time_range: The time range being searched (e.g., "18:00 - 20:00")
            facility_names: Optional list of facility names that were searched

        Returns:
            NotificationResult with success status
        """
        subject = "🎾 RainBot - Aucun créneau disponible"

        greeting = f"Bonjour {user.name}" if user.name else "Bonjour"

        facilities_text = ""
        if facility_names:
            facilities_list = ", ".join(facility_names)
            facilities_text = f"<li>Centres recherchés : {facilities_list}</li>"

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: #1976d2;">📭 Aucun créneau disponible</h2>

            <p>{greeting},</p>

            <p>Nous avons recherché un court de tennis pour vous, mais aucun créneau
            correspondant à vos critères n'était disponible.</p>

            <div style="background-color: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #1976d2;">
                <p style="margin: 0 0 10px 0;"><strong>Critères de recherche :</strong></p>
                <ul style="margin: 0; padding-left: 20px;">
                    <li>Jour : {day_of_week}</li>
                    <li>Créneau horaire : {time_range}</li>
                    {facilities_text}
                </ul>
            </div>

            <p>🔄 <strong>Pas d'inquiétude !</strong> Le système continuera à chercher
            automatiquement et vous préviendra dès qu'une réservation sera effectuée.</p>

            <p style="color: #666; font-size: 14px;">
            💡 <em>Conseil : Les créneaux se libèrent souvent quelques jours avant la date.
            Restez patient !</em>
            </p>

            <p>Sportivement,<br>
            <strong>L'équipe RainBot</strong></p>

            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            <p style="color: #999; font-size: 12px;">
                Cet email a été envoyé automatiquement par RainBot.
            </p>
        </body>
        </html>
        """

        logger.info(f"Sending no slots notification to {user.email}")
        return self._send_email(user.email, subject, body_html)


# Global service instance (lazy initialization)
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get the global notification service instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
