# PropLink

Residential property management platform for Kenya: billing, confirmed M-Pesa payments, utilities and maintenance in one system.

## Project structure

| Folder | What it is | Tech |
|---|---|---|
| `backend/` | Single API for both apps (billing, payments, maintenance, automation, resident login) | Python, FastAPI, SQLAlchemy |
| `frontend/` | Manager dashboard | React, Vite |
| `Resident/` | Resident mobile app (Android) | Flutter |
| `docker-compose.yml` | PostgreSQL database | Docker |

M-Pesa (Daraja) is simulated by default (`DARAJA_MOCK=1`), so you can test the full payment flow without real keys.

## Features

**Manager dashboard** (`frontend/`)
- **Overview:** occupied vs total units, rent collected, outstanding balance, open requests and recent payments
- **Properties and units:** add units and start or end tenancies
- **Billing:** billing configurations, meter readings and bill generation
- **Payments:** M-Pesa STK push requests, confirmed payments and receipts
- **Maintenance:** resident service requests, status updates and charging job costs to a resident's bill
- **Providers:** service providers that can be enabled or disabled
- **Reports:** collected and outstanding amounts by charge type, maintenance cost by category, plus an audit log
- **Automation rules:** mark bills overdue and remind residents after N days; alert the manager when a request has had no update for N hours

**Resident app** (`Resident/`)
- Sign in with phone number and one-time code
- Home screen with unit, property and outstanding balance
- View bills and pay with M-Pesa (STK push), with live payment status and receipts
- Request services and report maintenance issues, and track their progress
- Account details and notifications

## Requirements

- Docker Desktop (for PostgreSQL)
- Python 3.10+
- Node.js 18+
- Flutter SDK with Android Studio (Android SDK, platform tools / `adb`)
- JDK 17 (set as the Gradle JDK in Android Studio)

## Run locally

### 1. Database

```bash
docker compose up -d
```

PostgreSQL runs on port **5433** (user, password and database are all `proplink`).

### 2. Backend API

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0
```

The API runs at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

### 3. Manager dashboard

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 4. Resident app (Flutter)

```bash
cd Resident
flutter pub get
```

**On the Android emulator:**

```bash
flutter run
```

The emulator reaches your PC's backend at `10.0.2.2:8000` automatically.

**On a real Android phone (USB):**

1. Enable Developer options and USB debugging on the phone, connect it, and accept the debugging prompt.
2. Check it is detected:
   ```bash
   flutter devices
   ```
3. Forward the phone's port 8000 to your PC, then run with the API URL:
   ```bash
   adb reverse tcp:8000 tcp:8000
   flutter run -d <device-id> --dart-define=API_URL=http://localhost:8000
   ```

Run `adb reverse` again each time you reconnect the phone.

**Signing in:** residents sign in with their phone number and a one-time code. While `DARAJA_MOCK=1`, no SMS is sent; the code is printed in the backend terminal (`[SMS simulated] code for ...`). The phone number must belong to a resident with an active tenancy, which you can set up from the manager dashboard.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://proplink:proplink@127.0.0.1:5433/proplink` | Database connection |
| `JWT_SECRET` | `dev-secret-change-me` | Signs resident login tokens. **Change before any real use.** |
| `DARAJA_MOCK` | `1` | `1` = simulated M-Pesa, `0` = live Daraja |
| `DARAJA_BASE` | `https://sandbox.safaricom.co.ke` | Daraja API base URL |
| `DARAJA_KEY`, `DARAJA_SECRET` | | Daraja app credentials (live mode only) |
| `DARAJA_SHORTCODE`, `DARAJA_PASSKEY` | | Paybill / till details (live mode only) |
| `DARAJA_CALLBACK_URL` | | Public URL Daraja posts results to, e.g. `https://<your-domain>/api/mpesa/callback` |

Never commit real keys.

## Troubleshooting

**Flutter build fails with `Could not close incremental caches` / `this and base files have different roots`**

This happens on Windows when the project and the Flutter Pub cache are on different drives (for example, the project on `R:` and the cache on `C:`). `Resident/android/gradle.properties` contains `kotlin.incremental=false` to prevent it. If you still see the error, stop the stale build daemons and rebuild:

```powershell
cd Resident\android
.\gradlew --stop
cd ..
flutter clean
flutter pub get
flutter run
```

**The app shows "Cannot reach the server"**

- Check the backend is running and started with `--host 0.0.0.0`.
- On a real phone, run `adb reverse tcp:8000 tcp:8000` again and launch with `--dart-define=API_URL=http://localhost:8000`.

**Phone not listed in `flutter devices`**

Set the USB mode to File transfer, accept the "Allow USB debugging?" prompt, or try another cable. Run `adb kill-server` and then `adb devices`.

## Status

**Done:** manager dashboard, Flutter resident app, mocked M-Pesa flow, audit log.

**To do:** manager login and roles, request photos, scheduled automation, live Daraja.