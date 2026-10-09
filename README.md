# Telegram Referral Competition Bot

A Telegram bot for a referral competition where every participant receives the same owner-provided Come.apk link. Telegram deep links record who invited each bot user; a referral is counted only after an admin approves the referred participant's screenshot.

## What is implemented

- Telegram `/start` registration and unique participant invite codes.
- Immutable, one-referrer-per-Telegram-user attribution with self-referral and duplicate protection.
- The same `COME_REFERRAL_LINK` for every participant.
- PostgreSQL persistence through SQLAlchemy 2.x and Alembic migrations.
- Screenshot upload checks for file type, image decode, dimensions, blank images, exact SHA-256 duplicates, and perceptual similarity.
- Optional OCR when the Tesseract executable is installed. OCR and image checks are screening signals, never proof.
- Admin review via Telegram commands and Approve/Reject buttons.
- Referral counts, ranks, leaderboard tie-breaking, competition lock/end, winner selection, CSV export, and audit logs.
- FastAPI `/healthz` endpoint; the bot polls Telegram from the same single running process.

## Verification limitation

No official Come.apk API contract or webhook format has been provided, so direct compatibility with Come.apk is unconfirmed. The bot now offers an optional signed inbound webhook contract for use only if Come.apk supports the required fields and signature, or through an authorized relay. Until it is configured with a trusted sender, manual admin review remains available. The bot does not scrape Come.apk or bypass login, CAPTCHA, or access controls. A rejected screenshot leaves the Telegram referral pending so the participant can submit corrected evidence. When the contest is ended, unresolved referrals are cancelled and excluded.

The `MockComeAPI` adapter is for development fixtures only and is not selected by the production bot. `AuthorizedComeAPI` is intentionally not wired to guessed endpoints; implement it only after receiving the provider's official API documentation and permission.

### Signed webhook contract

`POST /webhooks/come` accepts a bot-defined JSON contract; it is not claimed to be Come.apk's native webhook format. The route stays disabled until `COME_WEBHOOK_SECRET` is set in Replit Secrets. The sender must be trusted and authorized to report Come.apk registrations, and must supply a reliable mapping to the participant's Telegram account. A shared Come.apk link alone does not provide that mapping.

Required headers:

- `X-Come-Timestamp`: Unix timestamp in seconds, within five minutes of receipt.
- `X-Come-Signature`: lowercase or uppercase hex HMAC-SHA256 of `<timestamp>.<raw request body>`, using `COME_WEBHOOK_SECRET`.

Example event:

```json
{
  "event_id": "provider-event-123",
  "event_type": "registration.verified",
  "campaign_id": "the configured Come.apk campaign ID",
  "telegram_user_id": 123456789,
  "come_user_id": "come-account-456"
}
```

The campaign ID must match `COME_WEBHOOK_CAMPAIGN_ID`. Events are size-limited, signature-checked, and only approve a participant with a pending Telegram referral. Duplicate Come.apk account IDs are rejected, and repeated delivery does not count the referral twice. Configure the sender with the public HTTPS URL ending in `/webhooks/come`; never put the webhook secret in chat or source control. If Come.apk cannot emit this data and signature, a provider-authorized relay must do the mapping and signing.

## Requirements

- Python 3.12 or later
- Telegram bot token from BotFather
- PostgreSQL `DATABASE_URL`
- Fixed HTTPS Come.apk referral link
- At least one competition admin's numeric Telegram ID

Dependencies are listed in `requirements.txt`. Install them with:

```bash
python -m pip install -r requirements.txt
```

## Configuration

Use Replit Secrets for credentials. Never commit `.env` or paste secrets into source.

Required values:

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token from BotFather (secret) |
| `DATABASE_URL` | PostgreSQL connection string (Replit injects this for the built-in database) |
| `COME_REFERRAL_LINK` | Owner's one fixed HTTPS Come.apk referral link |

Optional settings:

| Variable | Default |
| --- | --- |
| `ADMIN_TELEGRAM_IDS` | Empty; add extra comma-separated admin Telegram IDs |
| `BOT_OWNER_TELEGRAM_ID` | Empty; numeric Telegram ID that receives admin-to-owner messages |
| `COMPETITION_NAME` | `Come Referral Competition` |
| `COMPETITION_START` | Start immediately |
| `COMPETITION_END` | No scheduled end |
| `PRIZE_AMOUNT` | `2500` INR |
| `MAX_SCREENSHOT_SIZE_MB` | `10` |
| `COME_API_BASE_URL`, `COME_API_KEY`, `COME_API_SECRET` | Unused until an authorized API contract is implemented |
| `COME_WEBHOOK_CAMPAIGN_ID` | Campaign identifier checked on signed webhook events |
| `COME_WEBHOOK_SECRET` | HMAC secret shared with the trusted webhook sender; keep in Replit Secrets |
| `REDIS_URL` | Optional; not required for the single-instance bot |

For local development, copy `.env.example` to `.env` and fill in the values. Do not commit the resulting `.env`.

To find a Telegram numeric ID, use a trusted Telegram ID lookup bot or inspect an update in a development bot. Only add IDs you control to `ADMIN_TELEGRAM_IDS`.

## Database setup

From this directory, apply the initial migration once:

```bash
alembic upgrade head
```

This creates tables prefixed with `competition_` and does not replace or rename other application tables. Back up important data before manually changing or reverting a migration.

When changing models, generate a migration, inspect it, and apply it to the intended database:

```bash
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
```

## Run locally or in a Replit workflow

From this directory:

```bash
python main.py
```

Or:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The configured workflow in this Repl runs `cd telegram-referral-bot && python main.py`. The service exposes `/healthz` and runs Telegram long polling in the same process. Keep exactly one bot process/replica active: Telegram long polling must not be started by multiple replicas with the same token.

The root `.replit` config selects the Telegram bot as this Repl's main run target. The bot source and dependencies remain self-contained in this directory; use the dedicated `Telegram Referral Bot` workflow here.

## Replit production operation

For a standalone Replit deployment, use an always-running VM deployment for the bot worker, not an autoscaling process that may sleep or start duplicate instances. Set the production secrets/environment variables in the production environment, apply the Alembic migration to the production database before starting the worker, and run `python main.py` as the single process. Do not put the bot token or database password in deployment logs or source files.

## User commands

- `/start` — register and open the menu; referral links use `/start CODE`.
- `/link` — show the user's unique Telegram tracking link.
- `/myreferrals` — counts and rank.
- `/leaderboard` and `/rank` — public competition ranking and personal rank.
- `/come` — the shared owner-provided Come.apk link.
- `/verify` — upload a screenshot after a referred user has joined.
- `/how` — competition instructions.
- `/support` — send a message to the competition admin team.

## Admin commands

Admins include the existing Telegram ID `6944760306` and the two requested IDs `8308849911` and `1831302205`, plus any additional IDs listed in `ADMIN_TELEGRAM_IDS`.

- `/admin`, `/stats`, `/leaderboard`, `/pending`, `/users`
- `/search <Telegram ID|username|referral code|Come.apk user ID>`
- `/approve <verification_id> [Come.apk user ID]`
- `/reject <verification_id> [reason]`
- `/reject_referral <referred Telegram ID> <reason>`
- `/delete_verification <Telegram ID>` — deletes stored verification records and Telegram file IDs; it does not change an already counted referral.
- `/export` — sends a CSV without screenshots or secrets.
- `/competition`, `/set_name`, `/set_prize`, `/set_start`, `/set_end`
- `/lock_competition`, `/end_competition`
- `/owner` or **Contact Bot Owner** — send a message to the configured bot owner. Only admins can start this contact.

Users contact the admin team from **Contact Admin** or `/support`. Admins can reply using the reply button attached to the support message. Admins contact the owner from **Contact Bot Owner** or `/owner`; the owner can reply with the button attached to the admin's message. Set `BOT_OWNER_TELEGRAM_ID` before using owner contact. Telegram requires the owner, admins, and users to start the bot before it can send them messages.

Use ISO-8601 dates for competition times, including an explicit offset when possible, for example `2026-11-01T18:30:00+05:30`. The default tie-breaker is the participant who reached their final verified count first. Ending the contest cancels unresolved referral relationships; resolve pending reviews before ending if they should be eligible.

## Tests

```bash
pytest -q
```

The tests use a private in-memory SQLite database and do not contact Telegram or Come.apk.
