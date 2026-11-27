"""Sign-in tokens, password hashing, rate limiting and the auth dependencies used by every protected route."""
import threading, time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
import config
from models import get_db, StaffUser, UserAccount, Tenancy

_ph = PasswordHasher()  # Argon2id
ALGO = "HS256"
MIN_PASSWORD = 10


# ---------- passwords ----------
def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def check_password(stored: str, pw: str) -> bool:
    try:
        return _ph.verify(stored, pw)
    except (VerificationError, InvalidHashError):
        return False


_DUMMY_HASH = _ph.hash("timing-equaliser")  # so unknown accounts take as long as wrong passwords


def burn_time(pw: str) -> None:
    check_password(_DUMMY_HASH, pw)


def password_problem(pw: str) -> str | None:
    if len(pw) < MIN_PASSWORD: return f"Password must be at least {MIN_PASSWORD} characters"
    if pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        return "Password must mix upper and lower case letters and include a number"
    return None


# ---------- tokens ----------
def make_token(kind: str, sub: int, ver: int, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"typ": kind, "sub": str(sub), "ver": ver, "iat": now, "exp": now + lifetime}, config.JWT_SECRET, algorithm=ALGO)


def read_token(authorization: str, kind: str) -> dict:
    tok = authorization.removeprefix("Bearer ").strip()
    try:
        data = jwt.decode(tok, config.JWT_SECRET, algorithms=[ALGO], options={"require": ["exp", "sub", "typ"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Please sign in again")
    if data.get("typ") != kind:
        raise HTTPException(401, "Please sign in again")
    return data


# ---------- rate limiting (per process; enough for a single API server) ----------
_hits: dict = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limit(bucket: str, key: str, limit: int, window_s: int) -> None:
    now = time.monotonic()
    with _hits_lock:
        q = _hits[(bucket, key)]
        while q and q[0] <= now - window_s: q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
        q.append(now)


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, start uvicorn with --proxy-headers so this is the real visitor, not the proxy.
    return request.client.host if request.client else "unknown"


# ---------- dependencies ----------
def current_staff(authorization: str = Header(""), db=Depends(get_db)) -> StaffUser:
    data = read_token(authorization, "staff")
    s = db.get(StaffUser, int(data["sub"]))
    if not s or not s.active or s.token_version != data.get("ver"):
        raise HTTPException(401, "Please sign in again")
    db.info["actor"] = s.email
    db.info["actor_id"] = s.id
    db.info["org"] = s.org_id
    return s


def require_landlord(s: StaffUser = Depends(current_staff)) -> StaffUser:
    """Routes that handle money, reports, billing rules, payment settings and staff accounts."""
    if s.role != "landlord": raise HTTPException(403, "Only the landlord can do this")
    return s


def current_tenancy(authorization: str = Header(""), db=Depends(get_db)):
    data = read_token(authorization, "resident")
    u = db.get(UserAccount, int(data["sub"]))
    if not u or u.token_version != data.get("ver"):
        raise HTTPException(401, "Please sign in again")
    t = db.scalar(select(Tenancy).where(Tenancy.resident_id == u.id, Tenancy.end_date.is_(None)))
    if not t: raise HTTPException(403, "No active tenancy")
    db.info["actor"] = f"resident #{u.id}"
    db.info["org"] = u.org_id
    return t
