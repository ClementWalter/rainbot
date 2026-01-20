"""Tests for CLI helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src import cli


def test_cli_export_booking_history_stdout(capsys):
    """Test exporting booking history to stdout."""
    with patch("src.cli.GoogleSheetsService") as mock_service_cls:
        mock_service = MagicMock()
        mock_service.export_booking_history_csv.return_value = "csv-data"
        mock_service_cls.return_value = mock_service

        exit_code = cli.main(["export-booking-history", "--user-id", "user-123"])

    assert exit_code == 0
    mock_service.export_booking_history_csv.assert_called_once_with(
        user_id="user-123",
        sort_desc=True,
    )
    assert capsys.readouterr().out == "csv-data"


def test_cli_export_booking_history_output_file(tmp_path):
    """Test exporting booking history to a file."""
    output_path = tmp_path / "history.csv"
    with patch("src.cli.GoogleSheetsService") as mock_service_cls:
        mock_service = MagicMock()
        mock_service.export_booking_history_csv.return_value = "csv-data"
        mock_service_cls.return_value = mock_service

        exit_code = cli.main(
            [
                "export-booking-history",
                "--output",
                str(output_path),
                "--ascending",
            ]
        )

    assert exit_code == 0
    mock_service.export_booking_history_csv.assert_called_once_with(
        user_id=None,
        sort_desc=False,
    )
    assert output_path.read_text(encoding="utf-8") == "csv-data"


def test_cli_no_command_returns_help(capsys):
    """Test CLI with no command returns help exit code."""
    exit_code = cli.main([])

    assert exit_code == 2
    assert "export-booking-history" in capsys.readouterr().out


def test_cli_email_booking_history_success():
    """Test emailing booking history to a user."""
    with patch("src.cli.GoogleSheetsService") as mock_service_cls:
        with patch("src.cli.get_notification_service") as mock_notification_cls:
            mock_service = MagicMock()
            mock_user = MagicMock()
            mock_service.get_user_by_id.return_value = mock_user
            mock_service.get_bookings_for_user.return_value = ["booking"]
            mock_service_cls.return_value = mock_service

            mock_notification = MagicMock()
            mock_notification.is_configured.return_value = True
            mock_notification.send_booking_history.return_value = MagicMock(success=True)
            mock_notification_cls.return_value = mock_notification

            exit_code = cli.main(
                [
                    "email-booking-history",
                    "--user-id",
                    "user-123",
                    "--ascending",
                ]
            )

    assert exit_code == 0
    mock_service.get_user_by_id.assert_called_once_with("user-123")
    mock_service.get_bookings_for_user.assert_called_once_with("user-123")
    mock_notification.send_booking_history.assert_called_once_with(
        mock_user,
        ["booking"],
        sort_desc=False,
    )
