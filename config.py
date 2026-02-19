import os
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_VALID_SSL_MODES = {
    "disable",
    "allow",
    "prefer",
    "require",
    "verify-ca",
    "verify-full",
    "no-verify",
}


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"{name} environment variable required")
    return value


def _read_bool(name: str):
    value = os.getenv(name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False

    raise SystemExit(f"{name} must be a boolean value (true/false)")


def _resolve_ssl_mode():
    explicit_mode = (os.getenv("PGSSLMODE") or os.getenv("PG_SSL_MODE") or "").strip().lower()
    if explicit_mode:
        if explicit_mode not in _VALID_SSL_MODES:
            raise SystemExit(
                "PGSSLMODE/PG_SSL_MODE must be one of: "
                "disable, allow, prefer, require, verify-ca, verify-full, no-verify"
            )
        return explicit_mode

    ssl_enabled = _read_bool("PG_SSL")
    if ssl_enabled is False:
        return "disable"
    if ssl_enabled is True:
        reject_unauthorized = _read_bool("PG_SSL_REJECT_UNAUTHORIZED")
        if reject_unauthorized is None:
            reject_unauthorized = False
        return "verify-full" if reject_unauthorized else "require"

    return None


def _build_database_url_from_parts() -> str:
    user = quote(_require_env("PG_USER"), safe="")
    host = _require_env("PG_HOST")
    db_name = quote(_require_env("PG_DB"), safe="")
    password = quote(_require_env("PG_PW"), safe="")

    port = (os.getenv("PG_PORT") or "5432").strip()
    if not port.isdigit() or int(port) <= 0:
        raise SystemExit("PG_PORT must be a positive integer")

    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _ensure_ssl_mode(database_url: str, ssl_mode) -> str:
    if not ssl_mode or ssl_mode == "disable":
        return database_url

    parsed = urlparse(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" in query:
        return database_url

    query["sslmode"] = "require" if ssl_mode == "no-verify" else ssl_mode
    return urlunparse(parsed._replace(query=urlencode(query)))


def _resolve_database_dsn() -> str:
    direct_database_url = (os.getenv("DATABASE_URL") or "").strip()
    database_url = direct_database_url if direct_database_url else _build_database_url_from_parts()
    return _ensure_ssl_mode(database_url, _resolve_ssl_mode())


# === Config ===
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1024"))
LISTENER_QUEUE_MAXSIZE = int(os.getenv("LISTENER_QUEUE_MAXSIZE", "256"))
IDLE_TIMEOUT = int(os.getenv("IDLE_TIMEOUT", "600"))
SILENCE_PATH = os.getenv("SILENCE_PATH", "silence.mp3")
MUSIC_BASE_DIR = os.getenv("MUSIC_BASE_DIR", "music")

# Track registry
TRACKS_CSV_PATH = os.getenv("TRACKS_CSV_PATH", "tracks.csv")

# Playlist registry (Google Sheets URL or local CSV path)
PLAYLISTS_CSV_PATH = os.getenv("PLAYLISTS_CSV_PATH", "playlists.csv")

# Pro playlists registry (Google Sheets URL or local CSV path)
PRO_PLAYLISTS_CSV_PATH = os.getenv("PRO_PLAYLISTS_CSV_PATH", "pro_playlists.csv")

# Admin whitelist for reload endpoint (comma-separated emails)
ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

# Dev mode: bypass auth checks (set to "true" to enable)
DEV_MODE = os.getenv("DEV_MODE", "").lower() == "true"
DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "dev@localhost")

# CloudFront configuration
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN") or exit("CLOUDFRONT_DOMAIN is required")
CLOUDFRONT_KEY_ID = os.getenv("CLOUDFRONT_KEY_ID") or exit("CLOUDFRONT_KEY_ID is required")
CLOUDFRONT_PRIVATE_KEY_PATH = os.getenv("CLOUDFRONT_PRIVATE_KEY_PATH") or exit("CLOUDFRONT_PRIVATE_KEY_PATH is required")

# Redis configuration
REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
if not REDIS_URL:
    raise SystemExit("REDIS_URL environment variable required")
SESSION_REDIS_PREFIX = os.getenv("SESSION_REDIS_PREFIX", "frc:sess:")

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
LOGIN_URL = os.getenv("LOGIN_URL", "https://farreachco.com/login")

# Session configuration
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "frc_session")
SESSION_SECRET = os.getenv("SESSION_SECRET") or exit("SESSION_SECRET is required")

# Database configuration
SESSION_DB_DSN = _resolve_database_dsn()

# === Load Silence Buffer ===
try:
    with open(SILENCE_PATH, "rb") as f:
        SILENT_BUFFER = f.read()
except FileNotFoundError:
    import logging

    logging.warning(f"Silence buffer file not found: {SILENCE_PATH}. Using fallback.")
    SILENT_BUFFER = b"\x00" * CHUNK_SIZE
