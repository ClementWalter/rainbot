"""HTML and JavaScript parsers used by the Paris Tennis API client."""

from __future__ import annotations

import ast
import json
import re

from bs4 import BeautifulSoup

from paris_tennis_api.exceptions import ValidationError
from paris_tennis_api.models import (
    AntiBotConfig,
    ReservationSummary,
    SearchCatalog,
    SearchResult,
    SlotOffer,
    TennisCourt,
    TennisVenue,
    TicketAvailability,
    TicketAvailabilitySummary,
)


def _extract_js_object_after_marker(html: str, marker: str) -> str:
    """Extract a JS object by brace matching so nested payloads stay intact."""

    marker_index = html.find(marker)
    if marker_index < 0:
        raise ValidationError(f"Missing marker '{marker}' in HTML.")
    start = html.find("{", marker_index)
    if start < 0:
        raise ValidationError("Missing opening brace for JS object.")

    depth = 0
    in_string = False
    escaped = False
    quote = ""

    for index in range(start, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue

        if char in {"'", '"'}:
            in_string = True
            quote = char
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return html[start : index + 1]

    raise ValidationError("Unbalanced JS object braces.")


def parse_search_catalog(html: str) -> SearchCatalog:
    """Parse venues, filters, and date options from the search page HTML."""

    soup = BeautifulSoup(html, "lxml")

    object_text = _extract_js_object_after_marker(html, "var tennis =")
    data = json.loads(object_text)
    features = data.get("features")
    if not features and data.get("type") == "Feature":
        features = [data]
    if not features:
        raise ValidationError("Could not parse venue catalog from search page.")

    venues: dict[str, TennisVenue] = {}
    for feature in features:
        properties = feature.get("properties", {})
        general = properties.get("general", {})
        name = str(general.get("_nomSrtm", "")).strip()
        venue_id = str(general.get("_id", "")).strip()
        if not name or not venue_id:
            continue
        courts_payload = properties.get("courts", [])
        courts = tuple(
            TennisCourt(
                court_id=str(court.get("_airId", "")).strip(),
                name=str(court.get("_airNom", "")).strip(),
            )
            for court in courts_payload
            if str(court.get("_airId", "")).strip()
        )
        available_now = bool(properties.get("available", False))
        candidate = TennisVenue(
            venue_id=venue_id,
            name=name,
            available_now=available_now,
            courts=courts,
        )
        existing = venues.get(name)
        # Prefer currently available entries when duplicates exist for the same name.
        if existing is None or (candidate.available_now and not existing.available_now):
            venues[name] = candidate

    date_options = tuple(
        element.get("dateiso") or element.get("dateIso")
        for element in soup.select(".date[dateiso], .date[dateIso]")
        if (element.get("dateiso") or element.get("dateIso"))
    )

    surface_options: dict[str, str] = {}
    for checkbox in soup.select("input[name='selCoating'][value]"):
        option_id = str(checkbox.get("value", "")).strip()
        label = checkbox.find_parent("label")
        display = ""
        if label:
            span = label.find("span")
            display = (
                span.get_text(" ", strip=True)
                if span
                else label.get_text(" ", strip=True)
            )
        surface_options[option_id] = display

    in_out_options: dict[str, str] = {}
    for checkbox in soup.select("input[name='selInOut'][value]"):
        option_id = str(checkbox.get("value", "")).strip()
        label = checkbox.find_parent("label")
        display = ""
        if label:
            span = label.find("span")
            display = (
                span.get_text(" ", strip=True)
                if span
                else label.get_text(" ", strip=True)
            )
        in_out_options[option_id] = display

    hour_range = "8-22"
    hour_input = soup.select_one("#hourRange")
    if hour_input and hour_input.get("value"):
        hour_range = str(hour_input.get("value"))
    match = re.match(r"^(\d{1,2})-(\d{1,2})$", hour_range.strip())
    min_hour = int(match.group(1)) if match else 8
    max_hour = int(match.group(2)) if match else 22

    if not venues:
        raise ValidationError("No venues found in search catalog.")

    return SearchCatalog(
        venues=venues,
        date_options=date_options,
        surface_options=surface_options,
        in_out_options=in_out_options,
        min_hour=min_hour,
        max_hour=max_hour,
    )


def parse_search_result(html: str) -> SearchResult:
    """Parse reservable slots and reservation captcha request id from result HTML.

    Anonymous sessions see availability but no bookable buttons.  The parser
    returns an empty slot list and blank ``captcha_request_id`` in that case
    instead of raising.
    """

    soup = BeautifulSoup(html, "lxml")

    # captchaRequestId only exists for authenticated sessions.
    captcha_field = soup.select_one(
        "form#formReservation input[name='captchaRequestId']"
    )
    captcha_request_id = (
        str(captcha_field.get("value", "")).strip() if captcha_field else ""
    )

    # Bookable slot buttons are only rendered for logged-in users.
    slots: list[SlotOffer] = []
    for button in soup.select("button.buttonAllOk"):
        equipment_id = str(button.get("equipmentid", "")).strip()
        court_id = str(button.get("courtid", "")).strip()
        date_deb = str(button.get("datedeb", "")).strip()
        date_fin = str(button.get("datefin", "")).strip()
        if not all([equipment_id, court_id, date_deb, date_fin]):
            continue
        slots.append(
            SlotOffer(
                equipment_id=equipment_id,
                court_id=court_id,
                date_deb=date_deb,
                date_fin=date_fin,
                price_eur=str(button.get("price", "")).strip(),
                price_label=str(button.get("typeprice", "")).strip(),
            )
        )

    return SearchResult(
        slots=tuple(slots),
        captcha_request_id=captcha_request_id,
    )


def parse_profile_reservation(html: str) -> ReservationSummary:
    """Parse current reservation state and cancellation token from profile HTML."""

    soup = BeautifulSoup(html, "lxml")
    raw_text = soup.get_text(" ", strip=True)
    no_reservation = "pas de réservation en cours" in raw_text.lower()
    cancellation_input = soup.select_one("form#annul input[name='token']")
    cancellation_token = (
        str(cancellation_input.get("value", "")).strip() if cancellation_input else ""
    )
    has_active_reservation = bool(cancellation_token) and not no_reservation
    return ReservationSummary(
        has_active_reservation=has_active_reservation,
        cancellation_token=cancellation_token,
        raw_text=raw_text,
    )


def parse_ticket_availability(html: str) -> TicketAvailabilitySummary:
    """Parse ticket balances from the profile ticket tab.

    The page structure changes over time, so the parser keeps flexible row
    extraction and only keeps rows that look like balance lines.
    """

    soup = BeautifulSoup(html, "lxml")
    raw_text = soup.get_text(" ", strip=True)

    tickets: list[TicketAvailability] = []
    seen: set[tuple[str, str]] = set()
    for row in soup.select("table tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.select("th, td")
            if cell.get_text(" ", strip=True)
        ]
        if len(cells) < 2:
            continue

        label = cells[0]
        remaining = cells[-1]
        if not re.search(r"\d", remaining):
            continue

        key = (label, remaining)
        if key in seen:
            continue
        seen.add(key)
        tickets.append(TicketAvailability(label=label, remaining=remaining))

    return TicketAvailabilitySummary(tickets=tuple(tickets), raw_text=raw_text)


def parse_captcha_form_fields(html: str) -> dict[str, str]:
    """Extract hidden input fields from the captcha form so the booking POST includes them."""

    soup = BeautifulSoup(html, "lxml")
    fields: dict[str, str] = {}
    for hidden_input in soup.select("form input[type='hidden']"):
        name = str(hidden_input.get("name", "")).strip()
        value = str(hidden_input.get("value", "")).strip()
        if name:
            fields[name] = value
    return fields


def parse_antibot_config(html: str) -> AntiBotConfig:
    """Extract LI_ANTIBOT config values needed to resolve reservation captcha."""

    match = re.search(r"LI_ANTIBOT\.loadAntibot\(\[(.*?)\]\)", html, re.S)
    if match is None:
        raise ValidationError("Could not find LI_ANTIBOT configuration.")

    raw_args = f"[{match.group(1)}]"
    raw_args = re.sub(r"\bnull\b", "None", raw_args)
    raw_args = re.sub(r"\btrue\b", "True", raw_args)
    raw_args = re.sub(r"\bfalse\b", "False", raw_args)
    parsed = ast.literal_eval(raw_args)

    if len(parsed) < 9:
        raise ValidationError("Invalid LI_ANTIBOT configuration payload.")

    return AntiBotConfig(
        method=str(parsed[0]),
        fallback_method=str(parsed[1]),
        locale=str(parsed[2]),
        sp_key=str(parsed[3]),
        base_url=str(parsed[4]).rstrip("/"),
        container_id=str(parsed[5] or "li-antibot"),
        custom_css_url=str(parsed[6]) if parsed[6] else None,
        antibot_id=str(parsed[7]) if parsed[7] else None,
        request_id=str(parsed[8]) if parsed[8] else None,
    )
