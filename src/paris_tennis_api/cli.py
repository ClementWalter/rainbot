"""Command-line interface for the Paris Tennis API client workflows."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence

from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.exceptions import BookingError, ParisTennisError, ValidationError
from paris_tennis_api.models import SearchCatalog, SearchRequest, SlotOffer

LOGGER = logging.getLogger(__name__)


def _first_env_value(env: Mapping[str, str], *names: str) -> str:
    """Return the first non-empty env var so CLI credentials stay backward compatible."""

    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


def _headless_from_env(value: str) -> bool:
    """Convert environment strings to bool with the same semantics as settings loader."""

    return value.strip().lower() not in {"0", "false", "no"}


def build_parser(*, env: Mapping[str, str] | None = None) -> argparse.ArgumentParser:
    """Create parser with env-backed defaults for credentials and runtime settings."""

    env_map = os.environ if env is None else env

    parser = argparse.ArgumentParser(
        prog="paris-tennis",
        description="CLI wrapper around the Paris Tennis booking API.",
    )
    parser.add_argument(
        "--username",
        default=_first_env_value(
            env_map, "PARIS_TENNIS_USERNAME", "PARIS_TENNIS_EMAIL"
        ),
        help="Login username (defaults to PARIS_TENNIS_USERNAME then PARIS_TENNIS_EMAIL).",
    )
    parser.add_argument(
        "--password",
        default=env_map.get("PARIS_TENNIS_PASSWORD", ""),
        help="Login password (defaults to PARIS_TENNIS_PASSWORD).",
    )
    parser.add_argument(
        "--captcha-api-key",
        default=env_map.get("CAPTCHA_API_KEY", ""),
        help="2captcha API key (defaults to CAPTCHA_API_KEY). Required for booking.",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=_headless_from_env(env_map.get("PARIS_TENNIS_HEADLESS", "true")),
        help="Run browser in headless mode (defaults to PARIS_TENNIS_HEADLESS=true).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logs.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list-courts",
        help="List available venues and courts.",
    )

    search_parser = subparsers.add_parser(
        "search-slots",
        help="Search bookable slots for one venue and date.",
    )
    _add_search_arguments(search_parser)

    book_parser = subparsers.add_parser(
        "book",
        help="Search slots and book one result by index.",
    )
    _add_search_arguments(book_parser)
    book_parser.add_argument(
        "--slot-index",
        type=int,
        default=1,
        help="1-based index of the slot to book in search results (default: 1).",
    )

    subparsers.add_parser(
        "cancel",
        help="Cancel the current reservation if one is active.",
    )

    subparsers.add_parser(
        "tickets",
        help="Show available ticket balances from your profile.",
    )

    return parser


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    """Keep search/book argument shape identical so both commands stay predictable."""

    parser.add_argument(
        "--venue", required=True, help="Exact venue name from list-courts."
    )
    parser.add_argument("--date", required=True, help="Date in DD/MM/YYYY format.")
    parser.add_argument(
        "--hour-start",
        type=int,
        default=None,
        help="Start hour (inclusive). Defaults to catalog minimum.",
    )
    parser.add_argument(
        "--hour-end",
        type=int,
        default=None,
        help="End hour (exclusive). Defaults to catalog maximum.",
    )
    parser.add_argument(
        "--surface-id",
        action="append",
        default=None,
        dest="surface_ids",
        help="Filter by surface ID. Repeat option to include multiple values.",
    )
    parser.add_argument(
        "--in-out-code",
        action="append",
        default=None,
        dest="in_out_codes",
        help="Filter by in/out code. Repeat option to include multiple values.",
    )


def _configure_logging(verbose: bool) -> None:
    """Route CLI output through logging so automation can change verbosity globally."""

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)


def _validate_common_credentials(args: argparse.Namespace) -> None:
    """Fail early with explicit guidance instead of browser errors later in the flow."""

    if not args.username:
        raise ValidationError(
            "Missing username. Use --username or set PARIS_TENNIS_USERNAME/PARIS_TENNIS_EMAIL."
        )
    if not args.password:
        raise ValidationError(
            "Missing password. Use --password or set PARIS_TENNIS_PASSWORD."
        )
    if args.command == "book" and not args.captcha_api_key:
        raise ValidationError(
            "Missing captcha API key. Use --captcha-api-key or set CAPTCHA_API_KEY."
        )


def _build_search_request(
    args: argparse.Namespace, catalog: SearchCatalog
) -> SearchRequest:
    """Default optional filters from live catalog so command users can keep flags minimal."""

    return SearchRequest(
        venue_name=args.venue,
        date_iso=args.date,
        hour_start=args.hour_start if args.hour_start is not None else catalog.min_hour,
        hour_end=args.hour_end if args.hour_end is not None else catalog.max_hour,
        surface_ids=tuple(args.surface_ids or catalog.surface_options.keys()),
        in_out_codes=tuple(args.in_out_codes or catalog.in_out_options.keys()),
    )


def _log_slot(index: int, slot: SlotOffer) -> None:
    """Centralize slot formatting so search and booking output stay aligned."""

    LOGGER.info(
        "[%d] court=%s equipment=%s start=%s end=%s price=%s (%s)",
        index,
        slot.court_id,
        slot.equipment_id,
        slot.date_deb,
        slot.date_fin,
        slot.price_eur,
        slot.price_label,
    )


def _handle_list_courts(client: ParisTennisClient) -> int:
    """List all venues and courts from the live search catalog."""

    catalog = client.get_search_catalog()
    for venue_name in sorted(catalog.venues):
        venue = catalog.venues[venue_name]
        status = "available now" if venue.available_now else "not available now"
        LOGGER.info("%s (%s)", venue.name, status)
        if not venue.courts:
            LOGGER.info("  - no courts listed")
            continue
        for court in venue.courts:
            LOGGER.info("  - [%s] %s", court.court_id, court.name)
    return 0


def _handle_search_slots(client: ParisTennisClient, args: argparse.Namespace) -> int:
    """Search slots and display all matching offers."""

    catalog = client.get_search_catalog()
    request = _build_search_request(args, catalog)
    result = client.search_slots(request)

    LOGGER.info("Found %d slot(s).", len(result.slots))
    for index, slot in enumerate(result.slots, start=1):
        _log_slot(index=index, slot=slot)

    if result.captcha_request_id:
        LOGGER.info("captchaRequestId=%s", result.captcha_request_id)
    return 0


def _handle_book(client: ParisTennisClient, args: argparse.Namespace) -> int:
    """Search slots and book the selected index in one run without local persistence."""

    catalog = client.get_search_catalog()
    request = _build_search_request(args, catalog)
    result = client.search_slots(request)

    if not result.slots:
        raise BookingError("No slots available for the provided filters.")
    if not result.captcha_request_id:
        raise BookingError(
            "Search did not return captchaRequestId; booking is not possible."
        )

    selected_index = args.slot_index - 1
    if selected_index < 0 or selected_index >= len(result.slots):
        raise ValidationError(f"slot-index must be between 1 and {len(result.slots)}.")

    slot = result.slots[selected_index]
    _log_slot(index=args.slot_index, slot=slot)
    client.book_slot(slot=slot, captcha_request_id=result.captcha_request_id)

    current = client.get_current_reservation()
    if not current.has_active_reservation:
        raise BookingError("Reservation did not appear in profile after booking.")

    LOGGER.info("Booking completed and reservation is active.")
    return 0


def _handle_cancel(client: ParisTennisClient) -> int:
    """Cancel one active reservation and report whether anything changed."""

    canceled = client.cancel_current_reservation()
    if canceled:
        LOGGER.info("Reservation canceled.")
    else:
        LOGGER.info("No active reservation to cancel.")
    return 0


def _handle_tickets(client: ParisTennisClient) -> int:
    """Display available ticket balances from the dedicated profile tab."""

    summary = client.get_available_tickets()
    if not summary.tickets:
        LOGGER.info("No ticket balances parsed from profile tab.")
        return 0

    for ticket in summary.tickets:
        LOGGER.info("%s: %s", ticket.label, ticket.remaining)
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory=ParisTennisClient,
) -> int:
    """Run CLI command and return POSIX-compatible exit code."""

    parser = build_parser(env=env)
    args = parser.parse_args(argv)
    _configure_logging(verbose=args.verbose)

    try:
        _validate_common_credentials(args)
        with client_factory(
            email=args.username,
            password=args.password,
            captcha_api_key=args.captcha_api_key,
            headless=args.headless,
        ) as client:
            client.login()
            if args.command == "list-courts":
                return _handle_list_courts(client)
            if args.command == "search-slots":
                return _handle_search_slots(client, args)
            if args.command == "book":
                return _handle_book(client, args)
            if args.command == "cancel":
                return _handle_cancel(client)
            if args.command == "tickets":
                return _handle_tickets(client)
            raise ValidationError(f"Unsupported command '{args.command}'.")
    except ParisTennisError as error:
        LOGGER.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
