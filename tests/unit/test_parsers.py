"""Unit tests for parser helpers with stable HTML snippets."""

from paris_tennis_api.models import SearchRequest
from paris_tennis_api.parsers import (
    parse_antibot_config,
    parse_captcha_form_fields,
    parse_profile_reservation,
    parse_search_catalog,
    parse_search_result,
)


def test_parse_search_catalog_extracts_venue_name() -> None:
    """The parser should expose venue names for early validation."""

    html = """
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

    catalog = parse_search_catalog(html)
    assert "Alain Mimoun" in catalog.venues


def test_parse_search_result_extracts_captcha_request_id() -> None:
    """Search results must retain captcha request ids for booking step continuity."""

    html = """
    <html>
      <body>
        <form id="formReservation">
          <input name="captchaRequestId" value="abc123" />
        </form>
        <button class="buttonAllOk" equipmentId="327" courtId="3096" dateDeb="2026/04/12 08:00:00" dateFin="2026/04/12 09:00:00" price="12" typePrice="Tarif plein">Réserver</button>
      </body>
    </html>
    """

    result = parse_search_result(html)
    assert result.captcha_request_id == "abc123"


def test_parse_search_result_anonymous_returns_empty_slots() -> None:
    """Anonymous sessions have no captchaRequestId and no tennis-court rows."""

    html = """
    <html>
      <body>
        <div class="date-item selected">
          <div class="date" dateiso="12/04/2026">Sunday 12 April</div>
        </div>
      </body>
    </html>
    """

    result = parse_search_result(html)
    assert result.captcha_request_id == ""
    assert result.slots == ()


def test_parse_search_result_anonymous_extracts_tennis_court_rows_with_hour() -> None:
    """Anonymous pages group courts under hour headings; each slot must carry its hour."""

    # Mirrors the real accordion shape: a panel-title heading above a group
    # of tennis-court rows belonging to that hour.
    html = """
    <html>
      <body>
        <div class="panel">
          <a href="#collapseJulesLadoumègue08h">
            <div class="panel-heading"><h4 class="panel-title">08h</h4></div>
          </a>
          <div class="panel-collapse">
            <div class="row tennis-court">
              <div><span class="court">Court N°4 - Résine - Eclairé</span></div>
              <div>
                <div class="amount">
                  <span class="price">12 €</span>
                  <small class="price-description">Tarif réduit<br>Couvert</small>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="panel">
          <a href="#collapseJulesLadoumègue09h">
            <div class="panel-heading"><h4 class="panel-title">09h</h4></div>
          </a>
          <div class="panel-collapse">
            <div class="row tennis-court">
              <div><span class="court">Court N°5 - Résine - Eclairé</span></div>
              <div>
                <div class="amount">
                  <span class="price">20 €</span>
                  <small class="price-description">Tarif plein<br>Couvert</small>
                </div>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    result = parse_search_result(html)
    first, second = result.slots
    # Each slot must be tagged with the hour heading it was nested under.
    assert (first.date_deb, second.date_deb) == ("08h", "09h")
    assert (first.price_eur, second.price_eur) == ("12 €", "20 €")
    assert "Court N°4" in first.price_label and "Court N°5" in second.price_label


def test_parse_profile_reservation_detects_empty_state() -> None:
    """Empty profile pages should not be treated as active reservations."""

    html = """
    <html>
      <body>
        <div class="none"><span>Vous n’avez pas de réservation en cours.</span></div>
      </body>
    </html>
    """

    summary = parse_profile_reservation(html)
    assert summary.has_active_reservation is False


def test_parse_profile_reservation_extracts_recap_details() -> None:
    """Active reservation pages must surface every recap field for the SPA."""

    html = """
    <html>
      <body>
        <div class="recap">
          <h1 class="title">Récapitulatif</h1>
          <div class="row">
            <div class="col">
              <span class="tennis-name">TENNIS Jules Ladoumègue</span>
              <span class="tennis-address">39 rue des Petits Ponts 75019 Paris</span>
              <span class="tennis-hours">Sunday 19 April 2026 - <span class="hours">De 08h à 09h</span></span>
              <span class="tennis-court hidden-xs">Court n° 04 : Résine - Couvert - Eclairé</span>
            </div>
            <div class="col">
              <span class="entry">1 entrée</span>
              <span class="entry-total">Il vous reste 2 entrées.</span>
              <span class="price-description">Vous pouvez annuler jusqu'au 18/04/2026 à 08h</span>
            </div>
          </div>
        </div>
        <form id="annul"><input name="token" value="cancel-token-xyz" /></form>
      </body>
    </html>
    """

    summary = parse_profile_reservation(html)
    details = summary.details
    assert summary.has_active_reservation is True
    assert details is not None
    # All the structured fields render directly in the SPA card layout —
    # split into two asserts so a single mismatch is easy to read.
    assert (details.venue, details.address, details.court_label) == (
        "TENNIS Jules Ladoumègue",
        "39 rue des Petits Ponts 75019 Paris",
        "Court n° 04 : Résine - Couvert - Eclairé",
    )
    assert (
        details.date_label,
        details.hours_label,
        details.entry_label,
        details.balance_label,
    ) == (
        "Sunday 19 April 2026",
        "De 08h à 09h",
        "1 entrée",
        "Il vous reste 2 entrées.",
    )


def test_parse_captcha_form_fields_extracts_hidden_inputs() -> None:
    """Hidden inputs carry slot data that the booking POST must include."""

    html = """
    <html>
      <body>
        <form id="captchaForm" action="/tennis/jsp/site/Portal.jsp?page=reservation&amp;action=reservation_captcha">
          <input type="hidden" name="equipmentId" value="327" />
          <input type="hidden" name="courtId" value="3096" />
          <input type="hidden" name="dateDeb" value="2026/04/12 08:00:00" />
          <input type="hidden" name="dateFin" value="2026/04/12 09:00:00" />
          <input type="hidden" name="token" value="csrf-abc" />
          <input type="text" name="visible_field" value="ignored" />
          <div id="li-antibot"></div>
          <button type="submit" name="submitControle" value="submit">Réserver</button>
        </form>
      </body>
    </html>
    """

    fields = parse_captcha_form_fields(html)
    assert fields["equipmentId"] == "327"
    assert fields["courtId"] == "3096"
    assert fields["token"] == "csrf-abc"
    assert "visible_field" not in fields


def test_parse_captcha_form_fields_returns_empty_when_no_hidden_inputs() -> None:
    """Pages without hidden inputs should yield an empty dict, not crash."""

    html = "<html><body><form><button>OK</button></form></body></html>"
    assert parse_captcha_form_fields(html) == {}


def test_parse_antibot_config_uses_default_container_id() -> None:
    """Container defaults are critical because many pages pass null in JS config."""

    html = """
    <script>
      LI_ANTIBOT.loadAntibot(["IMAGE","AUDIO","FR","+ACAhl8aUF&v","https://captcha.liveidentity.com/captcha",null,null,"antibot-id","request-id",true]);
    </script>
    """

    config = parse_antibot_config(html)
    assert config.container_id == "li-antibot"


def test_search_request_validation_accepts_catalog_values() -> None:
    """Known values should pass validation without contacting the booking endpoint."""

    html = """
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

    catalog = parse_search_catalog(html)
    request = SearchRequest(
        venue_name="Alain Mimoun",
        date_iso="12/04/2026",
        hour_start=8,
        hour_end=9,
        surface_ids=("1324",),
        in_out_codes=("V",),
    )
    request.validate(catalog)
    assert True
