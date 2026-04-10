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

## Run tests

Unit tests:

```bash
uv run pytest tests/unit
```

Live end-to-end test (books then cancels):

```bash
uv run pytest tests/e2e/test_live_booking_flow.py
```
