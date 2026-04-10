# Paris Tennis API

Unofficial Python API over `https://tennis.paris.fr/` for login, search, booking, profile access, and cancellation.

## Setup

```bash
uv sync
cp .env.example .env
```

Populate `.env` with your credentials and captcha key.

## Quick usage

```python
from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.config import ParisTennisSettings

settings = ParisTennisSettings.from_env()
with ParisTennisClient.from_settings(settings) as client:
    client.login()
    reservation = client.book_first_available(days_in_advance=2)
    client.cancel_current_reservation()
```

## CLI usage

The package now ships a `paris-tennis` CLI with env-backed auth defaults:

- `--username` defaults to `PARIS_TENNIS_USERNAME`, then `PARIS_TENNIS_EMAIL`
- `--password` defaults to `PARIS_TENNIS_PASSWORD`
- `--captcha-api-key` defaults to `CAPTCHA_API_KEY` (required for `book`)

```bash
uv run paris-tennis --username "$PARIS_TENNIS_EMAIL" --password "$PARIS_TENNIS_PASSWORD" list-courts
uv run paris-tennis --username "$PARIS_TENNIS_EMAIL" --password "$PARIS_TENNIS_PASSWORD" search-slots --venue "Alain Mimoun" --date "12/04/2026"
uv run paris-tennis --username "$PARIS_TENNIS_EMAIL" --password "$PARIS_TENNIS_PASSWORD" --captcha-api-key "$CAPTCHA_API_KEY" book --venue "Alain Mimoun" --date "12/04/2026" --slot-index 1
uv run paris-tennis --username "$PARIS_TENNIS_EMAIL" --password "$PARIS_TENNIS_PASSWORD" cancel
uv run paris-tennis --username "$PARIS_TENNIS_EMAIL" --password "$PARIS_TENNIS_PASSWORD" tickets
```

## Run tests

Unit tests:

```bash
uv run pytest tests/unit
```

Live end-to-end test (books then cancels):

```bash
uv run pytest tests/e2e/test_live_booking_flow.py
```
