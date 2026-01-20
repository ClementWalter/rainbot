"""Command-line helpers for RainBot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from src.services.google_sheets import GoogleSheetsService


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
