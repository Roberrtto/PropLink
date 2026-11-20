# PropLink

Residential property management platform for Kenya: billing, confirmed M-Pesa payments, utilities and maintenance in one system.

## Project structure

| Folder | What it is | Tech |
|---|---|---|
| `backend/` | Single API for both apps (billing, payments, maintenance, automation, sign-in) | Python, FastAPI, SQLAlchemy |
| `frontend/` | Manager dashboard | React, Vite |
| `Resident/` | Resident mobile app (Android) | Flutter |
| `docker-compose.yml` | Starts the database and the API automatically | Docker |
| `deploy/Caddyfile` | HTTPS for production | Caddy |

## Features

**Manager dashboard** (`frontend/`)
- **Sign-in:** email and password, with admin and manager roles
- **Overview:** occupied vs total units, rent collected, outstanding balance, open requests and recent payments
- **Properties and units:** add units and start or end tenancies
- **Billing:** billing configurations, meter readings and bill generation
- **Payments:** M-Pesa STK push requests, confirmed payments and receipts
- **Maintenance:** resident service requests, status updates and charging job costs to a resident's bill
- **Providers:** service providers that can be enabled or disabled
- **Reports:** collected and outstanding amounts by charge type, maintenance cost by category, plus an audit log of who did what
- **Automation rules:** mark bills overdue and remind residents after N days; alert the manager when a request has had no update for N hours
- **Staff:** admins create, disable and manage dashboard accounts; everyone can change their own password

**Resident app** (`Resident/`)
- Sign in with phone number and a one-time SMS code
- Home screen with unit, property and outstanding balance
- View bills and pay with M-Pesa (STK push), with live payment status and receipts
- Request services and report maintenance issues, and track their progress
- Account details and notifications

## Security

| Area | How it is protected |
|---|---|
| Data in transit | HTTPS in production (Caddy, automatic certificates). The release app refuses plain `http://` servers. |
| Personal data at rest | Resident names and phone numbers are encrypted in the database (Fernet: AES + HMAC). Lookups use a keyed hash, so numbers are never stored in plain text. |
| Dashboard sign-in | Argon2id password hashing, strong password rule, account lockout after 5 wrong passwords, rate limiting, 12-hour sessions. |
| Resident sign-in | 6-digit SMS code, stored only as a keyed hash, expires after 5 minutes, max 5 tries, resend cooldown, rate limits. The API never reveals whether a number is registered. |
| Access control | Every dashboard route needs a signed-in staff member; staff management and property creation need an admin. Residents can only see their own bills, payments and requests. |
| Sign-out | Signing out, changing a password, disabling an account or ending a tenancy invalidates existing tokens immediately. |
| Payments | Safaricom's results go to a secret callback URL (optional IP allowlist). Callbacks are idempotent; a bill is only marked paid when the confirmed total covers it. Payment prompts can't be spammed. |
| App storage | The resident app keeps its token in Android Keystore-backed secure storage, and app backups are disabled. |
| Production safety | With `APP_ENV=production` the API refuses to start if any secret is missing or weak, or if simulated payments, simulated SMS or demo data are switched on. |
| Audit | Sign-ins, failed sign-ins and every change are recorded with who made them. |

## First-time setup

### 1. Requirements

- Docker Desktop
- Node.js 18+ (for the dashboard)
- Flutter SDK with Android Studio (for the resident app)
- Python 3.10+ (only to generate secrets, or to run the backend without Docker)

### 2. Create your `.env` file

```bash
cp .env.example .env
python backend/manage.py gen-secrets
```

(On Windows PowerShell: `copy .env.example .env`.)

Paste the printed values into `.env`. **Back up `.env` somewhere safe and never commit it.** If you lose `FIELD_ENCRYPTION_KEY` or `BLIND_INDEX_KEY`, stored names and phone numbers can't be read.

> If you ran an older version of PropLink, reset the database once with `docker compose down -v`: the old data isn't encrypted and the new version can't read it.

### 3. Start the database and API

```bash
docker compose up -d --build
```

This starts PostgreSQL and the API at http://localhost:8000. Both **restart automatically** after a crash, and come back after a reboot as long as Docker Desktop starts with Windows (Docker Desktop → Settings → General → *Start Docker Desktop when you sign in*).

Useful commands:

```bash
docker compose ps                 # are they running?
docker compose logs -f backend    # API log (development login codes appear here)
docker compose up -d --build      # after changing backend code
docker compose stop               # stop both (they stay stopped until you start them)
```

### 4. Create the first dashboard admin

```bash
docker compose exec backend python manage.py create-admin
```

In development mode (`SEED_DEMO=1`) a demo admin is also created; its password is printed in `docker compose logs backend`.

### 5. Start the manager dashboard (manually, when you need it)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in.

### 6. Run the resident app

```bash
cd Resident
flutter pub get
```

**Android emulator:** `flutter run` (the emulator reaches your PC at `10.0.2.2:8000`).

**Real phone over USB:**

```bash
adb reverse tcp:8000 tcp:8000
flutter run -d <device-id> --dart-define=API_URL=http://localhost:8000
```

Run `adb reverse` again each time you reconnect the phone. In development, the sign-in code is shown in the app and in `docker compose logs backend`.

## Going live with real users

1. **Server and domain.** Use a server that is always on and reachable from the internet (for example a small cloud VPS), with a domain such as `proplink.yourcompany.co.ke` pointing to it. Safaricom must be able to reach your API over HTTPS.
2. **M-Pesa.** On the [Daraja portal](https://developer.safaricom.co.ke), take your app live for your paybill or till to get production keys and the passkey.
3. **SMS.** Create an [Africa's Talking](https://africastalking.com) account, top it up, and (optionally) register a sender ID.
4. **Fill in `.env` on the server:**
   ```
   APP_ENV=production
   SEED_DEMO=0
   DOMAIN=proplink.yourcompany.co.ke
   CORS_ORIGINS=https://proplink.yourcompany.co.ke
   PUBLIC_BASE_URL=https://proplink.yourcompany.co.ke
   DARAJA_MOCK=0
   DARAJA_BASE=https://api.safaricom.co.ke
   DARAJA_KEY=...  DARAJA_SECRET=...  DARAJA_SHORTCODE=...  DARAJA_PASSKEY=...
   SMS_PROVIDER=africastalking
   AT_USERNAME=...  AT_API_KEY=...
   ```
   plus the secrets from `gen-secrets`. The API lists anything that is missing or unsafe and refuses to start until it's fixed.
5. **Build the dashboard and start everything with HTTPS:**
   ```bash
   cd frontend && npm install && npm run build && cd ..
   docker compose --profile production up -d --build
   docker compose exec backend python manage.py create-admin
   ```
   Caddy gets a free HTTPS certificate for your domain automatically. The dashboard is then at `https://<your domain>`.
6. **Build the app for residents:**
   ```bash
   cd Resident
   flutter build apk --release --dart-define=API_URL=https://proplink.yourcompany.co.ke
   ```
   For the Play Store, create a release keystore and `Resident/android/key.properties` (see the comment at the top of `Resident/android/app/build.gradle.kts`). Never commit the keystore or `key.properties`.
7. **Automation (optional).** Schedule `docker compose exec -T backend python manage.py run-automation` to run daily (cron on Linux, Task Scheduler on Windows).
8. **Backups.** Back up the database regularly, for example:
   ```bash
   docker compose exec -T db pg_dump -U proplink proplink > backup.sql
   ```

## Configuration (environment variables)

All settings live in `.env`; see `.env.example` for the full list with comments.

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` (demo data, simulated payments and SMS) or `production` (real users, strict checks) |
| `POSTGRES_PASSWORD` | Database password |
| `JWT_SECRET` | Signs sign-in tokens |
| `FIELD_ENCRYPTION_KEY` | Encrypts names and phone numbers. To rotate, put the new key first and keep the old ones after it, comma-separated. |
| `BLIND_INDEX_KEY` | Keyed hash used to look up phone numbers and one-time codes |
| `CORS_ORIGINS` | Dashboard addresses allowed to call the API |
| `SEED_DEMO` | `1` creates fake demo data (development only) |
| `DARAJA_MOCK` | `1` simulated M-Pesa, `0` real M-Pesa |
| `DARAJA_BASE` | Sandbox or live Daraja URL |
| `DARAJA_KEY`, `DARAJA_SECRET`, `DARAJA_SHORTCODE`, `DARAJA_PASSKEY` | Daraja credentials |
| `DARAJA_TRANSACTION_TYPE`, `DARAJA_PARTY_B` | Paybill (default) or till (Buy Goods) |
| `PUBLIC_BASE_URL`, `MPESA_CALLBACK_TOKEN` | Where Safaricom posts payment results (a secret URL) |
| `MPESA_ALLOWED_IPS` | Optional: only accept payment results from these IPs |
| `SMS_PROVIDER`, `AT_USERNAME`, `AT_API_KEY`, `AT_SENDER_ID` | SMS for sign-in codes (`console` prints them; `africastalking` sends them) |
| `DOMAIN` | Your domain, for HTTPS in production |

Admin commands (run inside Docker with `docker compose exec backend python manage.py ...`):

| Command | What it does |
|---|---|
| `gen-secrets` | Print new random secrets for `.env` |
| `create-admin` | Create a dashboard admin |
| `reset-password EMAIL` | Set a new password for an account and unlock it |
| `run-automation` | Run the automation rules once |

## Troubleshooting

**`docker compose up` says `Set POSTGRES_PASSWORD in .env`**
Create `.env` from `.env.example` and run `python backend/manage.py gen-secrets` (step 2).

**The API keeps restarting / `password authentication failed`**
The database was created earlier with a different password. If it only holds test data, reset it with `docker compose down -v` and start again.

**Flutter build fails with `Could not close incremental caches` / `this and base files have different roots`**
This happens on Windows when the project and the Flutter Pub cache are on different drives (for example R: and C:). `Resident/android/gradle.properties` already contains `kotlin.incremental=false` to prevent it. If you still see the error, stop the stale build daemons and rebuild:

```powershell
cd Resident\android
.\gradlew --stop
cd ..
flutter clean
flutter pub get
flutter run
```

**The app shows "Cannot reach the server"**
- Check the API is running: `docker compose ps`.
- On a real phone, run `adb reverse tcp:8000 tcp:8000` again and launch with `--dart-define=API_URL=http://localhost:8000`.

**The app says "This build is not set up for a secure (https) server"**
Release builds only talk to `https://` servers. Rebuild with `--dart-define=API_URL=https://your-domain`.

**Phone not listed in `flutter devices`**
Set the USB mode to File transfer, accept the "Allow USB debugging?" prompt, or try another cable. Run `adb kill-server` and then `adb devices`.

## Status

**Done:** manager dashboard with sign-in and roles, Flutter resident app, M-Pesa (simulated and live), SMS sign-in codes, encryption of personal data, audit log, automatic API startup.

**To do:** request photos, built-in scheduled automation, database migrations (schema changes currently need a reset).