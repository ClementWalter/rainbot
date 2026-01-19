"""Tests to verify the basic project structure."""

import pytest


def test_import_src():
    """Verify src package can be imported."""
    import src

    assert src is not None


def test_import_schedulers():
    """Verify schedulers module can be imported."""
    from src.schedulers import booking_job, send_remainder

    assert booking_job is not None
    assert send_remainder is not None


def test_import_config():
    """Verify config module can be imported."""
    from src.config.settings import Settings, load_settings

    assert Settings is not None
    assert load_settings is not None


def test_booking_job_runs():
    """Verify booking_job function can be called."""
    from src.schedulers.cron_jobs import booking_job

    # Should not raise an exception
    booking_job()


def test_send_remainder_runs():
    """Verify send_remainder function can be called."""
    from src.schedulers.cron_jobs import send_remainder

    # Should not raise an exception
    send_remainder()


def test_settings_loads():
    """Verify settings can be loaded from environment."""
    from src.config.settings import load_settings

    settings = load_settings()
    assert settings is not None
    assert settings.scheduler is not None
    assert settings.captcha is not None
