"""Typed exceptions used by the Paris Tennis API client."""


class ParisTennisError(RuntimeError):
    """Base error for every API-level failure."""


class ValidationError(ParisTennisError):
    """Raised when local validation fails before any booking request is sent."""


class AuthenticationError(ParisTennisError):
    """Raised when login fails or the session is no longer authenticated."""


class BookingError(ParisTennisError):
    """Raised when booking-related operations fail."""


class CaptchaError(ParisTennisError):
    """Raised when captcha solving fails or returns an invalid token."""
