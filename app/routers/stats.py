from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException

from app.database import get_db
from app.security import get_current_user

router = APIRouter(prefix="/api/stats", tags=["stats"])

# range -> (lookback timedelta or None for "all", sqlite strftime bucket format)
RANGE_CONFIG = {
    "day": (timedelta(days=1), "%Y-%m-%dT%H:00"),
    "week": (timedelta(days=7), "%Y-%m-%d"),
    "month": (timedelta(days=31), "%Y-%m-%d"),
    "year": (timedelta(days=366), "%Y-%m"),
    "2year": (timedelta(days=731), "%Y-%m"),
    "all": (None, "%Y-%m"),
}

# Ranges aggregated at (at least) day granularity can come from daily_stats.
# "day" is hourly and therefore always reads raw events.
DAILY_RANGES = ("week", "month", "year", "2year", "all")


def _validate(range: str, scope: str):
    if range not in RANGE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid range")
    if scope not in ("global", "user"):
        raise HTTPException(status_code=400, detail="Invalid scope")


def _target_user(request: Request, scope: str, user_id: int | None) -> int | None:
    current = get_current_user(request)
    if scope == "user":
        return user_id if (user_id and current.role == "admin") else current.id
    return None


def _start_day(lookback: timedelta | None) -> str | None:
    """daily_stats is keyed by whole days, so coarse ranges start at the
    beginning (UTC) of the first day inside the window instead of mid-day."""
    if lookback is None:
        return None
    return (datetime.now(timezone.utc) - lookback).date().isoformat()


def _active_drinks(conn):
    return conn.execute(
        "SELECT id, name, color FROM drink_types WHERE active=1 ORDER BY created_at"
    ).fetchall()


def _hourly_stats(conn, drinks, bucket_fmt: str, lookback: timedelta | None, target_user: int | None):
    """Hourly 'day' range — reads raw events (rolling 24 h), like before."""
    since = None
    if lookback:
        since = (datetime.now(timezone.utc) - lookback).isoformat()

    series = {}
    for d in drinks:
        params = [bucket_fmt, d["id"]]
        query = (
            "SELECT strftime(?, timestamp) AS bucket, COUNT(*) AS c "
            "FROM events WHERE drink_type_id = ?"
        )
        if target_user:
            query += " AND user_id = ?"
            params.append(target_user)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " GROUP BY bucket ORDER BY bucket"
        rows = conn.execute(query, params).fetchall()
        series[d["name"]] = {
            "color": d["color"],
            "points": [{"bucket": r["bucket"], "count": r["c"]} for r in rows],
        }

    base = "FROM events e JOIN drink_types dt ON dt.id = e.drink_type_id WHERE dt.active = 1"
    params = []
    if target_user:
        base += " AND e.user_id = ?"
        params.append(target_user)
    if since:
        base += " AND e.timestamp >= ?"
        params.append(since)

    pie_rows = conn.execute(f"SELECT dt.name, dt.color, COUNT(*) c {base} GROUP BY dt.id", params).fetchall()
    active_days = conn.execute(
        f"SELECT COUNT(DISTINCT date(e.timestamp)) c {base}", params
    ).fetchone()["c"]
    busy = conn.execute(
        f"SELECT date(e.timestamp) AS day, COUNT(*) c {base} GROUP BY day ORDER BY c DESC, day DESC LIMIT 1",
        params,
    ).fetchone()

    return _package(pie_rows, series, active_days, busy)


def _daily_stats(conn, drinks, bucket_fmt: str, lookback: timedelta | None, target_user: int | None):
    start_day = _start_day(lookback)
    monthly = bucket_fmt == "%Y-%m"
    bucket_expr = "substr(ds.day, 1, 7)" if monthly else "ds.day"

    conds = ""
    params = []
    if target_user:
        conds += " AND ds.user_id = ?"
        params.append(target_user)
    if start_day:
        conds += " AND ds.day >= ?"
        params.append(start_day)

    series = {}
    for d in drinks:
        rows = conn.execute(
            f"SELECT {bucket_expr} AS bucket, SUM(ds.count) AS c "
            "FROM daily_stats ds WHERE ds.drink_type_id = ?"
            f"{conds} GROUP BY bucket ORDER BY bucket",
            [d["id"], *params],
        ).fetchall()
        series[d["name"]] = {
            "color": d["color"],
            "points": [{"bucket": r["bucket"], "count": r["c"]} for r in rows],
        }

    join = "FROM daily_stats ds JOIN drink_types dt ON dt.id = ds.drink_type_id WHERE dt.active = 1"
    pie_rows = conn.execute(
        f"SELECT dt.name, dt.color, SUM(ds.count) c {join}{conds} GROUP BY dt.id ORDER BY dt.created_at",
        params,
    ).fetchall()
    active_days = conn.execute(
        f"SELECT COUNT(DISTINCT ds.day) c {join}{conds}", params
    ).fetchone()["c"]
    busy = conn.execute(
        f"SELECT ds.day, SUM(ds.count) c {join}{conds} GROUP BY ds.day ORDER BY c DESC, ds.day DESC LIMIT 1",
        params,
    ).fetchone()

    return _package(pie_rows, series, active_days, busy)


def _package(pie_rows, series, active_days, busy):
    pie = [{"name": r["name"], "color": r["color"], "count": r["c"]} for r in pie_rows]
    total = sum(p["count"] for p in pie)
    top = max(pie, key=lambda p: p["count"]) if pie else None
    return {
        "series": series,
        "pie": pie,
        "total": total,
        "top_drink": top,
        "busiest_day": {"day": busy["day"], "count": busy["c"]} if busy else None,
        "active_days": active_days,
        "avg_per_day": round(total / active_days, 2) if active_days else 0,
    }


@router.get("")
def get_stats(request: Request, scope: str = "global", range: str = "month", user_id: int | None = None):
    _validate(range, scope)
    target_user = _target_user(request, scope, user_id)
    lookback, bucket_fmt = RANGE_CONFIG[range]

    with get_db() as conn:
        drinks = _active_drinks(conn)
        if range == "day":
            data = _hourly_stats(conn, drinks, bucket_fmt, lookback, target_user)
        else:
            data = _daily_stats(conn, drinks, bucket_fmt, lookback, target_user)
    return data


@router.get("/leaderboard")
def leaderboard(request: Request, range: str = "month"):
    """Who drank how much in the selected range — every user, sorted. The
    dashboard shows this only for the global scope."""
    if range not in RANGE_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid range")
    get_current_user(request)
    lookback, _ = RANGE_CONFIG[range]

    with get_db() as conn:
        if range == "day":
            since = (datetime.now(timezone.utc) - lookback).isoformat()
            agg = (
                "SELECT e.user_id AS user_id, COUNT(*) c FROM events e "
                "WHERE e.timestamp >= ? GROUP BY e.user_id"
            )
            params: list = [since]
        else:
            start_day = _start_day(lookback)
            agg = "SELECT ds.user_id, SUM(ds.count) c FROM daily_stats ds"
            params = []
            if start_day:
                agg += " WHERE ds.day >= ?"
                params.append(start_day)
            agg += " GROUP BY ds.user_id"

        rows = conn.execute(
            "SELECT u.id AS user_id, u.name, COALESCE(s.c, 0) AS count "
            "FROM users u LEFT JOIN (" + agg + ") s ON s.user_id = u.id "
            "ORDER BY count DESC, u.name COLLATE NOCASE",
            params,
        ).fetchall()

    return {
        "range": range,
        "people": [{"user_id": r["user_id"], "name": r["name"], "count": r["count"]} for r in rows],
    }
