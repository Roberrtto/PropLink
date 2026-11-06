# PropLink

Residential property management platform for Kenya: billing, confirmed M-Pesa payments, utilities and maintenance in one system.

| Folder | What it is | Tech |
|---|---|---|
| `backend/` | Single API for both apps (billing, payments, maintenance, automation, resident login) | Python, FastAPI, SQLAlchemy |
| `frontend/` | Manager dashboard (8 pages) | React, Vite |
| `resident-app/` | Resident mobile app (Android) | React Native CLI |
| `docker-compose.yml` | PostgreSQL database | Docker |

M-Pesa (Daraja) is simulated by default (`DARAJA_MOCK=1`). See `resident-app/SETUP.md` for the mobile app.

## Run locally
1. `docker compose up -d` (database on port 5433)
2. `cd backend`, create/activate `.venv`, `pip install -r requirements.txt`, `uvicorn main:app --reload --host 0.0.0.0`
3. `cd frontend`, `npm install`, `npm run dev` (http://localhost:5173)
4. `cd resident-app`, `npm install`, start the emulator, `npx react-native start`, then `npx react-native run-android`

## Configuration (environment variables)
`DATABASE_URL`, `JWT_SECRET` (change before any real use), `DARAJA_MOCK`, `DARAJA_KEY`, `DARAJA_SECRET`, `DARAJA_SHORTCODE`, `DARAJA_PASSKEY`, `DARAJA_CALLBACK_URL`. Never commit real keys.

## Status
Done: manager dashboard, resident app, mocked M-Pesa flow, audit log. To do: manager login and roles, request photos, scheduled automation, live Daraja.