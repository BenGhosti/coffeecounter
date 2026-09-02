import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import Request, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config import settings
from app.database import get_session_secret, get_db

SESSION_COOKIE = "cc_session"
PBKDF2_ITERATIONS = 260_000


# ---------------------------------------------------------------------------
# PIN hashing (PBKDF2 — stdlib only, no extra native deps to build in Docker)
# ---------------------------------------------------------------------------
def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(hash_hex)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------------------
# Sessions (signed cookie, no server-side session table needed)
# ---------------------------------------------------------------------------
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_session_secret(), salt="cc-session")


def _max_age() -> Optional[int]:
    raw = settings.SESSION_TIMEOUT.strip().lower()
    if raw in ("instant", "0"):
        return None  # session cookie, dies with the browser
    try:
        return int(raw)
    except ValueError:
        return 28800


def create_session_token(user_id: int, role: str) -> str:
    return _serializer().dumps({"uid": user_id, "role": role})


def read_session_token(token: str) -> Optional[dict]:
    max_age = _max_age()
    try:
        return _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def set_session_cookie(response, user_id: int, role: str):
    token = create_session_token(user_id, role)
    secure = settings.BASE_URL.startswith("https://")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_max_age(),
        path="/",
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/")


class CurrentUser:
    def __init__(self, id: int, role: str, name: str):
        self.id = id
        self.role = role
        self.name = name


def get_current_user(request: Request) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    data = read_session_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Session expired")
    with get_db() as conn:
        row = conn.execute("SELECT id, name, role FROM users WHERE id=?", (data["uid"],)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return CurrentUser(id=row["id"], role=row["role"], name=row["name"])


def require_admin(user: CurrentUser = None):
    if user is None or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------------------------------------------------------------------------
# Real client IP behind a reverse proxy (Cloudflare-aware)
# ---------------------------------------------------------------------------
def get_client_ip(request: Request) -> str:
    if not settings.TRUST_PROXY:
        return request.client.host if request.client else "unknown"

    peer_ip = request.client.host if request.client else None
    if settings.TRUSTED_PROXY_IPS and peer_ip not in settings.TRUSTED_PROXY_IPS:
        # Immediate connection isn't from a proxy we trust — don't honor
        # spoofable headers, fall back to the socket peer.
        return peer_ip or "unknown"

    if settings.USE_CF_CONNECTING_IP:
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.strip()

    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Left-most entry is the original client.
        return xff.split(",")[0].strip()

    return peer_ip or "unknown"


# ---------------------------------------------------------------------------
# Simple in-memory login rate limiting (per client IP)
# ---------------------------------------------------------------------------
_login_attempts: dict[str, list[float]] = {}


def check_rate_limit(ip: str):
    now = time.time()
    window_start = now - settings.LOGIN_LOCKOUT_SECONDS
    attempts = [t for t in _login_attempts.get(ip, []) if t > window_start]
    _login_attempts[ip] = attempts
    if len(attempts) >= settings.LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in a few minutes.",
        )


def record_failed_attempt(ip: str):
    _login_attempts.setdefault(ip, []).append(time.time())


def reset_attempts(ip: str):
    _login_attempts.pop(ip, None)
