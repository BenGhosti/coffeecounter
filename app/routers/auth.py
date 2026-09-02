from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_db, now_iso, has_any_user
from app.security import (
    hash_pin, verify_pin, set_session_cookie, clear_session_cookie,
    get_current_user, get_client_ip, check_rate_limit, record_failed_attempt,
    reset_attempts,
)
from app import webauthn_utils

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PinLogin(BaseModel):
    pin: str


class SetupAdmin(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    pin: str


def _check_pin_length(pin: str):
    if len(pin) != settings.PIN_LENGTH or not pin.isdigit():
        raise HTTPException(
            status_code=422, detail=f"PIN must be exactly {settings.PIN_LENGTH} digits"
        )


@router.get("/status")
def status():
    return {
        "setupRequired": not has_any_user(),
        "authMode": settings.AUTH_MODE,
        "pinLength": settings.PIN_LENGTH,
    }


@router.post("/setup")
def setup_first_admin(body: SetupAdmin, response: Response):
    """Only works once — creates the first user, who becomes admin.
    Everyone after this is created by the admin via the GUI."""
    if has_any_user():
        raise HTTPException(status_code=409, detail="Setup already completed")
    _check_pin_length(body.pin)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (name, role, pin_hash, created_at) VALUES (?, 'admin', ?, ?)",
            (body.name.strip(), hash_pin(body.pin), now_iso()),
        )
        user_id = cur.lastrowid
    set_session_cookie(response, user_id, "admin")
    return {"id": user_id, "name": body.name.strip(), "role": "admin"}


@router.post("/login/pin")
def login_pin(body: PinLogin, request: Request, response: Response):
    if settings.AUTH_MODE == "passkey":
        raise HTTPException(status_code=403, detail="PIN login is disabled")

    ip = get_client_ip(request)
    check_rate_limit(ip)

    with get_db() as conn:
        users = conn.execute("SELECT id, name, role, pin_hash FROM users").fetchall()

    match = None
    for u in users:
        if u["pin_hash"] and verify_pin(body.pin, u["pin_hash"]):
            match = u
            break

    if not match:
        record_failed_attempt(ip)
        raise HTTPException(status_code=401, detail="Invalid PIN")

    reset_attempts(ip)
    set_session_cookie(response, match["id"], match["role"])
    return {"id": match["id"], "name": match["name"], "role": match["role"]}


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = get_current_user(request)
    return {"id": user.id, "name": user.name, "role": user.role}


# --- Passkey login (discoverable credentials — no PIN/username needed) ---
@router.post("/login/passkey/options")
def passkey_login_options():
    if settings.AUTH_MODE == "pin":
        raise HTTPException(status_code=403, detail="Passkey login is disabled")
    challenge_id, options = webauthn_utils.build_authentication_options()
    return {"challengeId": challenge_id, "options": options}


@router.post("/login/passkey/verify")
def passkey_login_verify(body: dict, response: Response):
    challenge_id = body.get("challengeId")
    credential = body.get("response")
    if not challenge_id or not credential:
        raise HTTPException(status_code=400, detail="Missing challengeId or response")
    try:
        user = webauthn_utils.verify_authentication(challenge_id, credential)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    set_session_cookie(response, user["id"], user["role"])
    return {"id": user["id"], "name": user["name"], "role": user["role"]}
