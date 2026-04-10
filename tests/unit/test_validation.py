"""Unit tests for local search validation guardrails."""

import pytest

from paris_tennis_api.exceptions import ValidationError
from paris_tennis_api.models import SearchRequest
from paris_tennis_api.parsers import parse_search_catalog


@pytest.fixture
def catalog_html() -> str:
    """Provide a compact but representative catalog fixture."""

    return """
    <html>
      <body>
        <input id="hourRange" value="8-22" />
        <div class="date" dateIso="12/04/2026"></div>
        <label><input name="selCoating" value="1324"/><span>Béton poreux</span></label>
        <label><input name="selInOut" value="V"/><span>Couvert</span></label>
        <script>
          var tennis = {"type":"FeatureColletion","features":[{"type":"Feature","properties":{"general":{"_id":327,"_nomSrtm":"Alain Mimoun"},"available":true,"courts":[{"_airId":3096,"_airNom":"Court 6"}]}}]};
        </script>
      </body>
    </html>
    """


def test_validation_rejects_unknown_venue(catalog_html: str) -> None:
    """Unknown venue names should fail before any request is sent."""

    catalog = parse_search_catalog(catalog_html)
    request = SearchRequest(
        venue_name="Unknown",
        date_iso="12/04/2026",
        hour_start=8,
        hour_end=9,
        surface_ids=("1324",),
        in_out_codes=("V",),
    )
    with pytest.raises(ValidationError) as exc:
        request.validate(catalog)
    assert "Unknown venue" in str(exc.value)


def test_validation_rejects_unknown_date(catalog_html: str) -> None:
    """Invalid date options should fail local validation."""

    catalog = parse_search_catalog(catalog_html)
    request = SearchRequest(
        venue_name="Alain Mimoun",
        date_iso="13/04/2026",
        hour_start=8,
        hour_end=9,
        surface_ids=("1324",),
        in_out_codes=("V",),
    )
    with pytest.raises(ValidationError) as exc:
        request.validate(catalog)
    assert "Unknown date" in str(exc.value)


def test_validation_rejects_invalid_hour_range(catalog_html: str) -> None:
    """Inverted or out-of-range hours should be blocked early."""

    catalog = parse_search_catalog(catalog_html)
    request = SearchRequest(
        venue_name="Alain Mimoun",
        date_iso="12/04/2026",
        hour_start=9,
        hour_end=8,
        surface_ids=("1324",),
        in_out_codes=("V",),
    )
    with pytest.raises(ValidationError) as exc:
        request.validate(catalog)
    assert "Invalid hour range" in str(exc.value)
