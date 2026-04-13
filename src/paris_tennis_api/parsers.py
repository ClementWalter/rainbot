"""HTML and JavaScript parsers used by the Paris Tennis API client."""

from __future__ import annotations

import ast
import json
import re

from bs4 import BeautifulSoup

from paris_tennis_api.exceptions import ValidationError
from paris_tennis_api.models import (
    AntiBotConfig,
    ReservationDetails,
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

    Authenticated pages render bookable ``button.buttonAllOk`` elements with
    every identifier the booking form needs.  Anonymous pages swap that
    button for a "Se connecter" call-to-action but still render one
    ``div.row.tennis-court`` per available court — we parse that as a
    read-only slot so callers can see what's available without logging in.
    """

    soup = BeautifulSoup(html, "lxml")

    # captchaRequestId only exists for authenticated sessions.
    captcha_field = soup.select_one(
        "form#formReservation input[name='captchaRequestId']"
    )
    captcha_request_id = (
        str(captcha_field.get("value", "")).strip() if captcha_field else ""
    )

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

    if not slots:
        # Anonymous fallback: no bookable buttons, but each available court
        # is still rendered as a ``div.row.tennis-court`` card, grouped by
        # hour under an accordion heading like ``<h4 class="panel-title">08h</h4>``.
        # Walk the document in source order so each row picks up the last
        # hour header seen above it.
        current_hour = ""
        for element in soup.find_all(["h4", "div"]):
            classes = element.get("class") or []
            if element.name == "h4" and "panel-title" in classes:
                current_hour = element.get_text(" ", strip=True)
                continue
            if element.name != "div" or "tennis-court" not in classes:
                continue
            court_el = element.select_one("span.court")
            price_el = element.select_one("span.price")
            desc_el = element.select_one("small.price-description")
            court_label = court_el.get_text(" ", strip=True) if court_el else ""
            price_eur = price_el.get_text(" ", strip=True) if price_el else ""
            price_description = (
                desc_el.get_text(" ", strip=True) if desc_el else ""
            )
            if not (court_label or price_eur):
                continue
            label = " — ".join(
                part for part in (court_label, price_description) if part
            )
            slots.append(
                SlotOffer(
                    equipment_id="",
                    court_id="",
                    # Anonymous HTML only exposes the hour label (e.g. "08h"),
                    # not a full datetime; we still surface it via date_deb
                    # so the CLI can render start times without a new field.
                    date_deb=current_hour,
                    date_fin="",
                    price_eur=price_eur,
                    price_label=label,
                )
            )

    return SearchResult(
        slots=tuple(slots),
        captcha_request_id=captcha_request_id,
    )


def parse_profile_reservation(html: str) -> ReservationSummary:
    """Parse current reservation state, structured details, and cancel token.

    When the page renders a ``div.recap`` block we extract every visible
    field (venue, address, date, hours, court, ticket counts, cancel
    deadline) so the SPA can lay it out cleanly.  ``raw_text`` is also kept
    (trimmed of navigation noise) as a fallback for older pages or pages we
    don't recognize.
    """

    soup = BeautifulSoup(html, "lxml")
    raw_text = soup.get_text(" ", strip=True)
    no_reservation = "pas de réservation en cours" in raw_text.lower()
    cancellation_input = soup.select_one("form#annul input[name='token']")
    cancellation_token = (
        str(cancellation_input.get("value", "")).strip() if cancellation_input else ""
    )
    has_active_reservation = bool(cancellation_token) and not no_reservation

    details = _parse_reservation_recap(soup)
    trimmed = _trim_profile_navigation(raw_text)
    return ReservationSummary(
        has_active_reservation=has_active_reservation,
        cancellation_token=cancellation_token,
        raw_text=trimmed,
        details=details,
    )


def _parse_reservation_recap(soup: BeautifulSoup) -> ReservationDetails | None:
    """Read fields from the ``div.recap`` block when an active booking exists."""

    recap = soup.select_one("div.recap")
    if recap is None:
        return None

    hours_label = _text(recap.select_one(".tennis-hours .hours"))
    full_hours_line = _text(recap.select_one(".tennis-hours"))
    # The .tennis-hours element contains both the long date prefix and the
    # nested .hours span.  Strip the hours text out to recover the date.
    date_label = (
        full_hours_line.replace(hours_label, "").rstrip(" -").strip()
        if hours_label
        else full_hours_line
    )

    return ReservationDetails(
        venue=_text(recap.select_one(".tennis-name")),
        address=_text(recap.select_one(".tennis-address")),
        date_label=date_label,
        hours_label=hours_label,
        # Prefer the desktop single-line span; the mobile <ul> alternative
        # exists for layout but carries the same fragments.
        court_label=_text(recap.select_one("span.tennis-court")),
        entry_label=_text(recap.select_one(".entry")),
        balance_label=_text(recap.select_one(".entry-total")),
        cancel_deadline=_text(recap.select_one(".price-description")),
    )


def _text(node: object) -> str:
    """Return whitespace-collapsed text or empty string when the node is missing."""

    if node is None:
        return ""
    return getattr(node, "get_text")(" ", strip=True)


def _trim_profile_navigation(raw_text: str) -> str:
    """Strip the repeated nav/tab/header noise from the profile text dump."""

    markers = ("Crédit d'absence", "Nombre d'heures", "Vous ", "Réservation")
    earliest: int | None = None
    for marker in markers:
        index = raw_text.find(marker)
        if index >= 0 and (earliest is None or index < earliest):
            earliest = index
    if earliest is None or earliest == 0:
        return raw_text
    return raw_text[earliest:].strip()


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
