"""Additional parser tests for error handling and edge-case extraction paths."""

from __future__ import annotations

import pytest

from paris_tennis_api.exceptions import ValidationError
from paris_tennis_api.parsers import (
    _extract_js_object_after_marker,
    parse_antibot_config,
    parse_search_catalog,
    parse_search_result,
    parse_ticket_availability,
)


def test_extract_js_object_after_marker_requires_marker() -> None:
    """Missing marker should raise so callers can surface actionable parsing errors."""

    with pytest.raises(ValidationError):
        _extract_js_object_after_marker("<html></html>", "var tennis =")


def test_extract_js_object_after_marker_requires_opening_brace() -> None:
    """Markers without object payload should fail instead of returning invalid slices."""

    with pytest.raises(ValidationError):
        _extract_js_object_after_marker("var tennis = missing-brace", "var tennis =")


def test_extract_js_object_after_marker_rejects_unbalanced_braces() -> None:
    """Brace matching should detect malformed JS payloads to avoid partial parsing."""

    with pytest.raises(ValidationError):
        _extract_js_object_after_marker("var tennis = {\"a\": {\"b\": 1}", "var tennis =")


def test_extract_js_object_after_marker_handles_escaped_quotes_in_strings() -> None:
    """Brace matching should ignore escaped quotes while parsing JS string literals."""

    payload = 'var tennis = {"value": "a \\"quoted\\" text", "x": 1};'
    extracted = _extract_js_object_after_marker(payload, "var tennis =")
    assert extracted.endswith("}")


def test_parse_search_catalog_requires_features_collection() -> None:
    """Catalog parser should reject pages with no feature collection payload."""

    html = """
    <html>
      <body>
        <script>var tennis = {"type":"FeatureCollection","features":[]};</script>
      </body>
    </html>
    """
    with pytest.raises(ValidationError):
        parse_search_catalog(html)


def test_parse_search_catalog_requires_at_least_one_named_venue() -> None:
    """Entries without venue id/name should be ignored and lead to explicit failure."""

    html = """
    <html>
      <body>
        <script>
          var tennis = {"type":"FeatureCollection","features":[{"type":"Feature","properties":{"general":{"_id":"","_nomSrtm":""}}}]};
        </script>
      </body>
    </html>
    """
    with pytest.raises(ValidationError):
        parse_search_catalog(html)


def test_parse_search_catalog_accepts_single_feature_payload() -> None:
    """Single-feature payload should be normalized into one-item feature list."""

    html = """
    <html>
      <body>
        <input id="hourRange" value="8-22" />
        <script>
          var tennis = {"type":"Feature","properties":{"general":{"_id":327,"_nomSrtm":"Alain Mimoun"},"available":true,"courts":[{"_airId":3096,"_airNom":"Court 6"}]}};
        </script>
      </body>
    </html>
    """
    catalog = parse_search_catalog(html)
    assert "Alain Mimoun" in catalog.venues


def test_parse_search_result_ignores_buttons_missing_booking_identifiers() -> None:
    """Incomplete slot buttons should be skipped so consumers only see valid offers."""

    html = """
    <html>
      <body>
        <button class="buttonAllOk" equipmentId="327" courtId="" dateDeb="a" dateFin="b">Bad</button>
      </body>
    </html>
    """
    result = parse_search_result(html)
    assert result.slots == ()


def test_parse_ticket_availability_skips_short_and_duplicate_rows() -> None:
    """Ticket parser should ignore malformed rows and deduplicate identical balances."""

    html = """
    <html>
      <body>
        <table>
          <tr><td>Header only</td></tr>
          <tr><td>Heures pleines</td><td>5h</td></tr>
          <tr><td>Heures pleines</td><td>5h</td></tr>
        </table>
      </body>
    </html>
    """
    summary = parse_ticket_availability(html)
    assert len(summary.tickets) == 1


def test_parse_antibot_config_requires_marker() -> None:
    """Parser should fail when LI_ANTIBOT bootstrap call is not present in page."""

    with pytest.raises(ValidationError):
        parse_antibot_config("<html></html>")


def test_parse_antibot_config_requires_minimum_arguments() -> None:
    """Antibot payloads with too few args should raise to prevent invalid solver state."""

    html = """
    <script>
      LI_ANTIBOT.loadAntibot(["IMAGE","AUDIO","FR"]);
    </script>
    """
    with pytest.raises(ValidationError):
        parse_antibot_config(html)
