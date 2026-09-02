from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_db, now_iso
from app.security import hash_pin, get_current_user, CurrentUser
from app import webauthn_utils

router = APIRouter(prefix="/api/users", tags=["users"])


def admin_only(request: Request) -> CurrentUser:
    user = get_current_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _check_pin_length(pin: str):
    if len(pin) != settings.PIN_LENGTH or not pin.isdigit():
        raise HTTPException(
            status_code=422, detail=f"PIN must be exactly {settings.PIN_LENGTH} digits"
        )


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    pin: str
    role: str = Field(default="user", pattern="^(admin|user)$")


class UpdateUser(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    pin: str | None = None
    role: str | None = Field(default=None, pattern="^(admin|user)$")


@router.get("")
def list_users(admin: CurrentUser = Depends(admin_only)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, role, created_at FROM users ORDER BY created_at"
        ).fetchall()
        result = []
        for r in rows:
            keys = conn.execute(
                "SELECT COUNT(*) c FROM passkeys WHERE user_id=?", (r["id"],)
            ).fetchone()["c"]
            result.append({**dict(r), "passkeyCount": keys})
    return result


@router.post("")
def create_user(body: NewUser, admin: CurrentUser = Depends(admin_only)):
    _check_pin_length(body.pin)
    with get_db() as conn:
        clash = conn.execute("SELECT id FROM users").fetchall()
        for u in clash:
            pass  # PIN uniqueness is enforced by hash-scan at login time; check plain-pin collisions here
        existing_pins = conn.execute("SELECT pin_hash FROM users").fetchall()
        from app.security import verify_pin
        for row in existing_pins:
            if row["pin_hash"] and verify_pin(body.pin, row["pin_hash"]):
                raise HTTPException(status_code=409, detail="This PIN is already in use — PINs must be unique")
        cur = conn.execute(
            "INSERT INTO users (name, role, pin_hash, created_at) VALUES (?, ?, ?, ?)",
            (body.name.strip(), body.role, hash_pin(body.pin), now_iso()),
        )
        user_id = cur.lastrowid
    return {"id": user_id, "name": body.name.strip(), "role": body.role}


@router.patch("/{user_id}")
def update_user(user_id: int, body: UpdateUser, admin: CurrentUser = Depends(admin_only)):
    if body.pin:
        _check_pin_length(body.pin)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if row["role"] == "admin" and body.role == "user":
            admins = conn.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"]
            if admins <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last remaining admin")

        name = body.name.strip() if body.name else row["name"]
        role = body.role if body.role else row["role"]
        pin_hash = hash_pin(body.pin) if body.pin else row["pin_hash"]
        conn.execute(
            "UPDATE users SET name=?, role=?, pin_hash=? WHERE id=?",
            (name, role, pin_hash, user_id),
        )
    return {"ok": True}


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: CurrentUser = Depends(admin_only)):
    with get_db() as conn:
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        if row["role"] == "admin":
            admins = conn.execute("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"]
            if admins <= 1:
                raise HTTPException(status_code=400, detail="Cannot delete the last remaining admin")
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"ok": True}


# --- Passkeys: any logged-in user manages their own; admin can manage any user's ---
@router.get("/{user_id}/passkeys")
def list_passkeys(user_id: int, request: Request):
    user = get_current_user(request)
    if user.id != user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, last_used_at FROM passkeys WHERE user_id=? ORDER BY created_at",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/{user_id}/passkeys/register-options")
def passkey_register_options(user_id: int, body: dict, request: Request):
    user = get_current_user(request)
    if user.id != user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")
    with get_db() as conn:
        row = conn.execute("SELECT name FROM users WHERE id=?", (user_id,)).fetchone()
    challenge_id, options = webauthn_utils.build_registration_options(user_id, row["name"])
    return {"challengeId": challenge_id, "options": options}


@router.post("/{user_id}/passkeys/register-verify")
def passkey_register_verify(user_id: int, body: dict, request: Request):
    user = get_current_user(request)
    if user.id != user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")
    challenge_id = body.get("challengeId")
    credential = body.get("response")
    name = body.get("name", "Passkey")
    try:
        webauthn_utils.verify_registration(challenge_id, credential, user_id, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.delete("/{user_id}/passkeys/{passkey_id}")
def delete_passkey(user_id: int, passkey_id: int, request: Request):
    user = get_current_user(request)
    if user.id != user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")
    with get_db() as conn:
        conn.execute("DELETE FROM passkeys WHERE id=? AND user_id=?", (passkey_id, user_id))
    return {"ok": True}
