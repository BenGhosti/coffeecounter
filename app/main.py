from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database import init_db
from app.routers import auth, users, drinks, webhooks, events, stats, export

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="CoffeeCounter")

init_db()

if settings.ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# API + webhook routers first, so they take priority over the static catch-all.
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(drinks.router)
app.include_router(webhooks.router)
app.include_router(events.router)
app.include_router(stats.router)
app.include_router(export.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Static frontend assets (css/js/icons) under /assets
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    """Serve static HTML/CSS/JS directly by filename, defaulting to
    index.html (the login/entry page) for unknown paths."""
    candidate = FRONTEND_DIR / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(FRONTEND_DIR / "index.html")
