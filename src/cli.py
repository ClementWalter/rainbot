"""Command-line helpers for RainBot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from src.services.google_sheets import GoogleSheetsService
from src.services.notification import get_notification_service


def export_booking_history(args: argparse.Namespace) -> int:
    """Export booking history as CSV to stdout or a file."""
    service = GoogleSheetsService()
    csv_text = service.export_booking_history_csv(
        user_id=args.user_id,
        sort_desc=not args.ascending,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(csv_text, encoding="utf-8")
    else:
        sys.stdout.write(csv_text)

    return 0


def email_booking_history(args: argparse.Namespace) -> int:
    """Email booking history to a user."""
    service = GoogleSheetsService()
    notification = get_notification_service()

    if not notification.is_configured():
        sys.stderr.write("Notification service not configured.\n")
        return 1

    user = service.get_user_by_id(args.user_id)
    if not user:
        sys.stderr.write(f"User not found: {args.user_id}\n")
        return 1

    bookings = service.get_bookings_for_user(args.user_id)
    result = notification.send_booking_history(
        user,
        bookings,
        sort_desc=not args.ascending,
    )

    if result.success:
        return 0

    sys.stderr.write(f"Failed to send booking history: {result.error_message or 'unknown error'}\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="rainbot",
        description="RainBot command-line utilities.",
    )
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser(
        "export-booking-history",
        help="Export booking history as CSV.",
    )
    export_parser.add_argument(
        "--user-id",
        help="Optional user ID to filter bookings (default: all users).",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        help="Write CSV output to a file instead of stdout.",
    )
    export_parser.add_argument(
        "--ascending",
        action="store_true",
        help="Sort bookings oldest first (default: newest first).",
    )
    export_parser.set_defaults(func=export_booking_history)

    email_parser = subparsers.add_parser(
        "email-booking-history",
        help="Email booking history to a user.",
    )
    email_parser.add_argument(
        "--user-id",
        required=True,
        help="User ID to email booking history for.",
    )
    email_parser.add_argument(
        "--ascending",
        action="store_true",
        help="Sort bookings oldest first (default: newest first).",
    )
    email_parser.set_defaults(func=email_booking_history)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 2

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
