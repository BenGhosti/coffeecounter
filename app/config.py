"""
Central configuration, read once at startup from environment variables.
Mirrors the style of the reference DumbLoad .env (PORT, APP_DATA_PATH,
BASE_URL, TRUST_PROXY, SESSION_TIMEOUT, ...) so it feels familiar on Unraid.
"""
import os
from pathlib import Path


def _bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


class Settings:
    # --- Server ---
    PORT: int = int(os.getenv("PORT", "3000"))
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:3000/").rstrip("/") + "/"
    NODE_ENV: str = os.getenv("NODE_ENV", "production")

    # --- Storage (Unraid appdata pattern) ---
    APP_DATA_PATH: Path = Path(os.getenv("APP_DATA_PATH", "/app/config"))
    DB_PATH: Path = Path(os.getenv("DB_PATH", str(APP_DATA_PATH / "coffeecounter.sqlite")))

    # --- Timezone ---
    TZ: str = os.getenv("TZ", "Europe/Berlin")

    # --- Auth ---
    # 'pin', 'passkey', or 'both'
    AUTH_MODE: str = os.getenv("COFFEECOUNTER_AUTH_MODE", "both").strip().lower()
    # All PINs in the system share one length, since login has no username
    # field — the login screen shows exactly this many boxes and matches
    # whichever user's PIN hash fits. Admin-set PINs must be exactly this
    # long (4-10, like the reference project's guidance).
    PIN_LENGTH: int = max(4, min(10, int(os.getenv("COFFEECOUNTER_PIN_LENGTH", "4"))))
    SESSION_TIMEOUT: str = os.getenv("SESSION_TIMEOUT", "28800")  # seconds, or "instant"
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")  # generated + persisted on first boot if empty

    # WebAuthn Relying Party
    RP_ID: str = os.getenv("COFFEECOUNTER_RP_ID", "")  # default derived from BASE_URL host
    RP_NAME: str = os.getenv("COFFEECOUNTER_RP_NAME", "CoffeeCounter")

    # --- Reverse proxy / Cloudflare ---
    TRUST_PROXY: bool = _bool(os.getenv("TRUST_PROXY"), default=True)
    TRUSTED_PROXY_IPS: list[str] = _split_csv(os.getenv("TRUSTED_PROXY_IPS", ""))
    # When true, prefer Cloudflare's CF-Connecting-IP header over X-Forwarded-For
    USE_CF_CONNECTING_IP: bool = _bool(os.getenv("USE_CF_CONNECTING_IP"), default=True)

    ALLOWED_ORIGINS: list[str] = _split_csv(os.getenv("ALLOWED_ORIGINS", ""))

    # --- Webhook ---
    WEBHOOK_DEBOUNCE: int = int(os.getenv("WEBHOOK_DEBOUNCE", "0"))  # seconds, 0 = off

    # --- Login rate limiting (PINs are short, so brute-force protection matters) ---
    LOGIN_MAX_ATTEMPTS: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))
    LOGIN_LOCKOUT_SECONDS: int = int(os.getenv("LOGIN_LOCKOUT_SECONDS", "300"))


settings = Settings()
settings.APP_DATA_PATH.mkdir(parents=True, exist_ok=True)
settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def rp_id() -> str:
    if settings.RP_ID:
        return settings.RP_ID
    host = settings.BASE_URL.split("//", 1)[-1].split("/", 1)[0]
    return host.split(":")[0]
