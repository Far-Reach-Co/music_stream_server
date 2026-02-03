import os
from dotenv import load_dotenv

load_dotenv()


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

# Admin whitelist for reload endpoint (comma-separated emails)
ADMIN_EMAILS = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

# Dev mode: bypass auth checks (set to "true" to enable)
DEV_MODE = os.getenv("DEV_MODE", "").lower() == "true"
DEV_USER_EMAIL = os.getenv("DEV_USER_EMAIL", "dev@localhost")

# CloudFront configuration
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN") or exit("CLOUDFRONT_DOMAIN is required")
CLOUDFRONT_KEY_ID = os.getenv("CLOUDFRONT_KEY_ID") or exit("CLOUDFRONT_KEY_ID is required")
CLOUDFRONT_PRIVATE_KEY_PATH = os.getenv("CLOUDFRONT_PRIVATE_KEY_PATH") or exit("CLOUDFRONT_PRIVATE_KEY_PATH is required")

# Redis configuration (for signed URL caching)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))
LOGIN_URL = os.getenv("LOGIN_URL", "https://farreachco.com/login")

# Session configuration
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "frc_session")
SESSION_SECRET = os.getenv("SESSION_SECRET") or exit("SESSION_SECRET is required")

# Database configuration (all required for security)
PG_DB = os.getenv("PG_DB") or exit("PG_DB environment variable required")
PG_USER = os.getenv("PG_USER") or exit("PG_USER environment variable required")
PG_PW = os.getenv("PG_PW") or exit("PG_PW environment variable required")
PG_HOST = os.getenv("PG_HOST") or exit("PG_HOST environment variable required")
SESSION_DB_DSN = f"dbname={PG_DB} user={PG_USER} password={PG_PW} host={PG_HOST}"

# === Load Silence Buffer ===
try:
    with open(SILENCE_PATH, "rb") as f:
        SILENT_BUFFER = f.read()
except FileNotFoundError:
    import logging
    logging.warning(f"Silence buffer file not found: {SILENCE_PATH}. Using fallback.")
    SILENT_BUFFER = b"\x00" * CHUNK_SIZE
