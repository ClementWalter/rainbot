# Paris Tennis API

Unofficial Python API over `https://tennis.paris.fr/` for login, search, booking, profile access, and cancellation.

The repository now also contains a mobile-first web app built on FastAPI + Jinja templates + SQLite for a low-maintenance local/deployment stack.

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

## Web app usage

Run the full local web stack:

```bash
uv run paris-tennis-webapp --reload
```

Open `http://127.0.0.1:8000`.

Behavior:

- Login uses allow-listed Paris Tennis credentials stored in clear text in SQLite.
- First launch exposes a one-time bootstrap form to create the initial admin.
- Users can save booking searches and toggle them active/inactive.
- History page shows pending reservation live from Paris Tennis (no pending DB cache) plus local booking history recorded when booking through the app.
- Admins can manage allow-listed users and admin role directly in the app.

Useful env vars:

- `PARIS_TENNIS_WEBAPP_DB` (default `data/paris_tennis_webapp.sqlite3`)
- `PARIS_TENNIS_WEBAPP_SESSION_SECRET`
- `PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY` (fallback: `CAPTCHA_API_KEY`)
- `PARIS_TENNIS_WEBAPP_HEADLESS`, `PARIS_TENNIS_WEBAPP_HOST`, `PARIS_TENNIS_WEBAPP_PORT`

## Run tests

Unit tests:

```bash
uv run pytest tests/unit
```

Live end-to-end tests are opt-in to avoid accidental real bookings during
default local/CI runs. Enable them only when you explicitly want to exercise
`tennis.paris.fr`:

```bash
PARIS_TENNIS_RUN_LIVE_E2E=1 uv run pytest tests/e2e/test_live_booking_flow.py
PARIS_TENNIS_RUN_LIVE_E2E=1 uv run pytest tests/e2e/test_captcha_flow.py
```
