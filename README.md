# RainBot

Because Paris tennis courts are like taxis in the rain: technically available,
emotionally distant, and if you blink you'll miss the last one.

RainBot is an unofficial Python API and web app over `https://tennis.paris.fr/`
that logs in, searches, books, and cancels courts on your behalf — so you can
keep arguing about who actually called "in" on that last forehand instead of
refreshing a municipal booking page at 08:00 sharp.

> **Weather disclaimer:** RainBot cannot cancel rain. It can, however, cancel
> your reservation at 04:17 the night before, when the forecast turns from
> "sunny ☀️" to "moist existential crisis 🌧️". Paris gives you what Paris gives
> you.

## What it does

- **Logs in** to your `tennis.paris.fr` account without you having to rage-type
  your password with one hand while holding a racquet in the other.
- **Searches slots** at every venue — covered, uncovered, and that one court
  where the net is always 6cm too low.
- **Books courts** the instant the booking window opens, which, as any Parisian
  club player knows, is the single most competitive moment in all of organised
  sport.
- **Solves CAPTCHAs** via 2Captcha, because the Mairie de Paris apparently
  believes bots are the real threat to public tennis (and not, say, the rain).
- **Cancels reservations** when the forecast betrays you — gracefully, so
  someone else can get drenched instead.

## Webapp dev workflow

One command, two processes, zero excuses:

```bash
./scripts/dev.py
# or, for the uv purists in the back:
uv run scripts/dev.py
```

Boots FastAPI on `:8000` and Vite on `:5173`, runs `bun install` if
`web/node_modules` is missing (rookie move, but we forgive you), mirrors both
logs into one terminal with `[api]` / `[web]` tags, and forwards `Ctrl+C` to
both children like a well-coached doubles partner. Open
<http://localhost:5173>.

For production: `cd web && bun run build` then `uv run paris-tennis-webapp` —
FastAPI serves the built `web/dist` SPA and falls back to `index.html` for
unknown paths, so refreshing a React Router page doesn't feel like a double
fault.

## Setup

```bash
uv sync
cp .env.example .env
```

Populate `.env` with your credentials and captcha key. Losing this file is
roughly equivalent to forgetting your racquet at the gym: recoverable, but
embarrassing.

## Quick usage

```python
from paris_tennis_api.client import ParisTennisClient
from paris_tennis_api.config import ParisTennisSettings

settings = ParisTennisSettings.from_env()
with ParisTennisClient.from_settings(settings) as client:
    client.login()
    reservation = client.book_first_available(days_in_advance=2)
    client.cancel_current_reservation()  # because it's now raining sideways
```

## CLI usage

RainBot ships a `paris-tennis` CLI with env-backed auth defaults, so your
shell history doesn't become a confession:

- `--username` defaults to `PARIS_TENNIS_USERNAME`, then `PARIS_TENNIS_EMAIL`
- `--password` defaults to `PARIS_TENNIS_PASSWORD`
- `--captcha-api-key` defaults to `CAPTCHA_API_KEY` (required for `book`;
  CAPTCHAs don't solve themselves, much like backhand volleys)

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

Open `http://127.0.0.1:8000`. It's like `tennis.paris.fr`, but the buttons work
and nobody is trying to sell you a carnet at 18h59.

Behavior, in plain French-tennis prose:

- Login uses allow-listed Paris Tennis credentials stored in clear text in
  SQLite. (Yes, clear text. Yes, we know. It's a personal tool, not a bank.)
- Health probe at `/healthz` without auth, for uptime checks and existential
  reassurance.
- First launch exposes a one-time bootstrap form to create the initial admin —
  basically the coin toss.
- Users can save booking searches and toggle them active/inactive, like
  standing orders for serotonin.
- History page shows pending reservations live from Paris Tennis (no stale DB
  cache) plus local booking history recorded when booking through the app.
- Admins can manage allow-listed users and admin role directly in the app, no
  SQL spelunking required.

Useful env vars:

- `PARIS_TENNIS_WEBAPP_DB` (default `data/paris_tennis_webapp.sqlite3`)
- `PARIS_TENNIS_WEBAPP_SESSION_SECRET`
- `PARIS_TENNIS_WEBAPP_CAPTCHA_API_KEY` (fallback: `CAPTCHA_API_KEY`)
- `PARIS_TENNIS_WEBAPP_HEADLESS`, `PARIS_TENNIS_WEBAPP_HOST`,
  `PARIS_TENNIS_WEBAPP_PORT`

## Run tests

Unit tests, fast and dry:

```bash
uv run pytest tests/unit
```

Live end-to-end tests are opt-in, because nobody wants their CI to
accidentally book a court on a random Tuesday at Elisabeth while it's
pouring rain in the 14e:

```bash
PARIS_TENNIS_RUN_LIVE_E2E=1 uv run pytest tests/e2e/test_live_booking_flow.py
PARIS_TENNIS_RUN_LIVE_E2E=1 uv run pytest tests/e2e/test_captcha_flow.py
```

## FAQ

**Is this allowed?**
It scripts a public booking flow on your own account. Use it the way you'd
use any other automation: responsibly, and without hogging every court in the
12e on Sunday mornings.

**Why "RainBot"?**
Because in Paris, booking a tennis court is 30% skill, 70% weather forecast,
and 100% hitting F5 at exactly the right second. The bot does the F5 part.
The rain does the rest.

**Will it help my backhand?**
No. But it will ensure your backhand gets a court to be bad on.
