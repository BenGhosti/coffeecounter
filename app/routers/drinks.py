from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field

from app.database import get_db, now_iso
from app.security import get_current_user, CurrentUser

router = APIRouter(prefix="/api/drinks", tags=["drinks"])


def admin_only(request: Request) -> CurrentUser:
    user = get_current_user(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class NewDrink(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class UpdateDrink(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    active: bool | None = None


@router.get("")
def list_drinks(request: Request, include_inactive: bool = False):
    get_current_user(request)  # any logged-in user can see drink types
    with get_db() as conn:
        if include_inactive:
            rows = conn.execute("SELECT * FROM drink_types ORDER BY created_at").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM drink_types WHERE active=1 ORDER BY created_at"
            ).fetchall()
    return [dict(r) for r in rows]


@router.post("")
def create_drink(body: NewDrink, admin: CurrentUser = Depends(admin_only)):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO drink_types (name, color, is_default, active, created_at) "
            "VALUES (?, ?, 0, 1, ?)",
            (body.name.strip(), body.color, now_iso()),
        )
    return {"id": cur.lastrowid, "name": body.name.strip(), "color": body.color}


@router.patch("/{drink_id}")
def update_drink(drink_id: int, body: UpdateDrink, admin: CurrentUser = Depends(admin_only)):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM drink_types WHERE id=?", (drink_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Drink type not found")
        name = body.name.strip() if body.name else row["name"]
        color = body.color if body.color else row["color"]
        active = int(body.active) if body.active is not None else row["active"]
        conn.execute(
            "UPDATE drink_types SET name=?, color=?, active=? WHERE id=?",
            (name, color, active, drink_id),
        )
    return {"ok": True}


@router.delete("/{drink_id}")
def delete_drink(drink_id: int, admin: CurrentUser = Depends(admin_only)):
    """Soft-delete only — deactivate. Keeps historical events/charts intact."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM drink_types WHERE id=?", (drink_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Drink type not found")
        conn.execute("UPDATE drink_types SET active=0 WHERE id=?", (drink_id,))
    return {"ok": True}
