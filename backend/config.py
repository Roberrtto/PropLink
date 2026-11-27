"""All settings come from environment variables (or a .env file in the project root or backend/).

APP_ENV=development  -> safe defaults for local testing (demo data, simulated M-Pesa).
APP_ENV=production   -> real users. The API refuses to start if any secret is missing or weak.

M-Pesa credentials are NOT set here: each landlord enters their own Paybill/Till details in the dashboard
(Payment settings), and they are stored encrypted in the database.
"""
import base64, hashlib, os, sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")
    load_dotenv(here.parent / ".env")
except ImportError:
    pass


def _env(name, default=""):
    return os.getenv(name, default).strip()


def _flag(name, default):
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


APP_ENV = _env("APP_ENV", "development").lower()
PRODUCTION = APP_ENV == "production"

DATABASE_URL = _env("DATABASE_URL", "postgresql+psycopg2://proplink:proplink@127.0.0.1:5433/proplink")
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
SEED_DEMO = _flag("SEED_DEMO", not PRODUCTION)

# Secrets. Development falls back to fixed, clearly-insecure values so the app runs out of the box.
_DEV = "insecure-development-only"
JWT_SECRET = _env("JWT_SECRET") or ("" if PRODUCTION else _DEV + "-jwt-secret-0123456789")
FIELD_ENCRYPTION_KEY = _env("FIELD_ENCRYPTION_KEY") or ("" if PRODUCTION else base64.urlsafe_b64encode(hashlib.sha256((_DEV + "-fernet").encode()).digest()).decode())
BLIND_INDEX_KEY = _env("BLIND_INDEX_KEY") or ("" if PRODUCTION else _DEV + "-blind-index")

STAFF_TOKEN_HOURS = int(_env("STAFF_TOKEN_HOURS", "12"))
RESIDENT_TOKEN_DAYS = int(_env("RESIDENT_TOKEN_DAYS", "30"))

# M-Pesa (Daraja). DARAJA_MOCK=1 simulates payments; the real credentials are per landlord (see above).
DARAJA_MOCK = _flag("DARAJA_MOCK", not PRODUCTION)
DARAJA_BASE = _env("DARAJA_BASE", "https://sandbox.safaricom.co.ke").rstrip("/")  # https://api.safaricom.co.ke for live
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL").rstrip("/")  # e.g. https://api.yourdomain.co.ke; Safaricom posts payment results here
MPESA_CALLBACK_TOKEN = _env("MPESA_CALLBACK_TOKEN") or ("" if PRODUCTION else _DEV + "-callback")
MPESA_ALLOWED_IPS = {ip.strip() for ip in _env("MPESA_ALLOWED_IPS").split(",") if ip.strip()}

# Activation codes are issued by a manager in the dashboard and read out to the resident
OTP_TTL_SECONDS = 120
OTP_MAX_ATTEMPTS = 5


def problems():
    """Return a list of configuration errors that make the current settings unsafe for real users."""
    p = []
    if JWT_SECRET.startswith(_DEV) or len(JWT_SECRET) < 32:
        p.append("JWT_SECRET must be a random value of at least 32 characters")
    if not _env("FIELD_ENCRYPTION_KEY"):
        p.append("FIELD_ENCRYPTION_KEY is required (run: python manage.py gen-secrets)")
    if BLIND_INDEX_KEY.startswith(_DEV) or len(BLIND_INDEX_KEY) < 32:
        p.append("BLIND_INDEX_KEY must be a random value of at least 32 characters")
    if "*" in CORS_ORIGINS:
        p.append("CORS_ORIGINS must list your dashboard's exact https:// address, not *")
    if SEED_DEMO:
        p.append("SEED_DEMO must be 0 (no fake residents in production)")
    if DARAJA_MOCK:
        p.append("DARAJA_MOCK must be 0 (simulated payments are not allowed in production)")
    else:
        if not PUBLIC_BASE_URL.startswith("https://"):
            p.append("PUBLIC_BASE_URL must be your API's public https:// address (Safaricom sends payment results there)")
        if MPESA_CALLBACK_TOKEN.startswith(_DEV) or len(MPESA_CALLBACK_TOKEN) < 24:
            p.append("MPESA_CALLBACK_TOKEN must be a random value of at least 24 characters")
    return p


if PRODUCTION and (errs := problems()):
    sys.exit("PropLink will not start in production with unsafe settings:\n  - " + "\n  - ".join(errs))