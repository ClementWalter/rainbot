"""Unit tests for ticket availability parsing helpers."""

from paris_tennis_api.models import TicketAvailability
from paris_tennis_api.parsers import parse_ticket_availability


def test_parse_ticket_availability_extracts_balance_rows() -> None:
    """Only rows with numeric remaining balances should be returned as tickets."""

    html = """
    <html>
      <body>
        <table>
          <tr><th>Carnet</th><th>Reste</th></tr>
          <tr><td>Heures pleines</td><td>5h</td></tr>
          <tr><td>Message</td><td>Aucun achat en attente</td></tr>
        </table>
      </body>
    </html>
    """

    summary = parse_ticket_availability(html)
    assert summary.tickets == (
        TicketAvailability(label="Heures pleines", remaining="5h"),
    )


def test_parse_ticket_availability_returns_empty_tuple_without_rows() -> None:
    """Pages without numeric table balances should produce an empty ticket list."""

    html = "<html><body><div>Aucun carnet disponible.</div></body></html>"
    summary = parse_ticket_availability(html)
    assert summary.tickets == ()
