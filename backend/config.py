"""All settings come from environment variables (or a .env file in the project root or backend/).

APP_ENV=development  -> safe defaults for local testing (demo data, simulated M-Pesa and SMS).
APP_ENV=production   -> real users. The API refuses to start if any secret is missing or weak.
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
ORG_NAME = _env("ORG_NAME", "My Property Company")
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
SEED_DEMO = _flag("SEED_DEMO", not PRODUCTION)

# Secrets. Development falls back to fixed, clearly-insecure values so the app runs out of the box.
_DEV = "insecure-development-only"
JWT_SECRET = _env("JWT_SECRET") or ("" if PRODUCTION else _DEV + "-jwt-secret-0123456789")
FIELD_ENCRYPTION_KEY = _env("FIELD_ENCRYPTION_KEY") or ("" if PRODUCTION else base64.urlsafe_b64encode(hashlib.sha256((_DEV + "-fernet").encode()).digest()).decode())
BLIND_INDEX_KEY = _env("BLIND_INDEX_KEY") or ("" if PRODUCTION else _DEV + "-blind-index")

STAFF_TOKEN_HOURS = int(_env("STAFF_TOKEN_HOURS", "12"))
RESIDENT_TOKEN_DAYS = int(_env("RESIDENT_TOKEN_DAYS", "30"))

# M-Pesa (Daraja)
DARAJA_MOCK = _flag("DARAJA_MOCK", not PRODUCTION)
DARAJA_BASE = _env("DARAJA_BASE", "https://sandbox.safaricom.co.ke").rstrip("/")
DARAJA_KEY = _env("DARAJA_KEY")
DARAJA_SECRET = _env("DARAJA_SECRET")
DARAJA_SHORTCODE = _env("DARAJA_SHORTCODE")
DARAJA_PASSKEY = _env("DARAJA_PASSKEY")
DARAJA_TRANSACTION_TYPE = _env("DARAJA_TRANSACTION_TYPE", "CustomerPayBillOnline")  # or CustomerBuyGoodsOnline for a till
DARAJA_PARTY_B = _env("DARAJA_PARTY_B") or DARAJA_SHORTCODE  # till number when using Buy Goods
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL").rstrip("/")  # e.g. https://api.yourdomain.co.ke
MPESA_CALLBACK_TOKEN = _env("MPESA_CALLBACK_TOKEN") or ("" if PRODUCTION else _DEV + "-callback")
MPESA_ALLOWED_IPS = {ip.strip() for ip in _env("MPESA_ALLOWED_IPS").split(",") if ip.strip()}

# SMS for one-time login codes
SMS_PROVIDER = _env("SMS_PROVIDER", "africastalking" if PRODUCTION else "console").lower()  # console | africastalking
AT_USERNAME = _env("AT_USERNAME")
AT_API_KEY = _env("AT_API_KEY")
AT_SENDER_ID = _env("AT_SENDER_ID")

OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60


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
        for k in ("DARAJA_KEY", "DARAJA_SECRET", "DARAJA_SHORTCODE", "DARAJA_PASSKEY"):
            if not _env(k): p.append(f"{k} is required for live M-Pesa")
        if not PUBLIC_BASE_URL.startswith("https://"):
            p.append("PUBLIC_BASE_URL must be your API's public https:// address (Safaricom sends payment results there)")
        if MPESA_CALLBACK_TOKEN.startswith(_DEV) or len(MPESA_CALLBACK_TOKEN) < 24:
            p.append("MPESA_CALLBACK_TOKEN must be a random value of at least 24 characters")
    if SMS_PROVIDER == "console":
        p.append("SMS_PROVIDER=console only prints codes to the log; use africastalking in production")
    elif SMS_PROVIDER == "africastalking" and not (AT_USERNAME and AT_API_KEY):
        p.append("AT_USERNAME and AT_API_KEY are required to send login codes by SMS")
    return p


if PRODUCTION and (errs := problems()):
    sys.exit("PropLink will not start in production with unsafe settings:\n  - " + "\n  - ".join(errs))