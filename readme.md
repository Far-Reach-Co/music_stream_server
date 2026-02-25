# Music Streaming Server | Far Reach Co.

A music streaming server built with FastAPI, FFmpeg, and Redis-backed sessions. Streams audio files from S3/CloudFront using signed URLs and allows authenticated users to control playback. Tracks are registered via CSV and organized into named playlists.

---

## Requirements

- Python 3.10+
- FFmpeg installed and available in `$PATH`
- Redis server
- AWS S3 bucket with CloudFront distribution
- CloudFront key pair for signed URLs

---

## Installation

```bash
# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Config

Set the following environment variables (or in `.env` file):

### Required

```bash
# Session/Auth
SESSION_SECRET=your-signing-secret
REDIS_URL=redis://your-redis-host:6379

# User metadata lookups (pro/admin checks)
DATABASE_URL=postgresql://user:password@db-host:5432/your_database
PG_SSL=true                               # Optional
PG_SSL_REJECT_UNAUTHORIZED=false          # Optional

# Backward-compatible fallback if DATABASE_URL is not set:
PG_DB=your_database
PG_USER=your_user
PG_PW=your_password
PG_HOST=your-db-host
PG_PORT=5432

# CloudFront
CLOUDFRONT_DOMAIN=d1234567890.cloudfront.net
CLOUDFRONT_KEY_ID=KXXXXXXXXXXXXXXX
CLOUDFRONT_PRIVATE_KEY_PATH=./private_frc_cloudfront_key.pem
```

### Optional

```bash
TRACKS_CSV_PATH=tracks.csv          # Default: tracks.csv (or Google Sheets URL)
PLAYLISTS_CSV_PATH=playlists.csv    # Default: playlists.csv (or Google Sheets URL)
SESSION_COOKIE_NAME=frc_session     # Default: frc_session
SESSION_REDIS_PREFIX=frc:sess:      # Default: frc:sess:
HOST=0.0.0.0                        # Default: 0.0.0.0
PORT=5000                           # Default: 5000
CHUNK_SIZE=1024                     # Default: 1024
LISTENER_QUEUE_MAXSIZE=256          # Default: 256
IDLE_TIMEOUT=600                    # Default: 600 (seconds)
LOGIN_URL=https://example.com/login # Redirect URL for unauthenticated users
PUBLIC_BASE_URL=https://radio.example.com # Optional: forces canonical/sitemap/robots URLs
```

### Admin

```bash
ADMIN_EMAILS=admin@example.com,other@example.com  # Comma-separated email whitelist
```

### Development

```bash
DEV_MODE=true                       # Bypass auth checks for local development
DEV_USER_EMAIL=dev@localhost        # Email used for admin checks in dev mode
```

---

## Track Registry

Tracks are registered in a CSV file or Google Sheets (set via `TRACKS_CSV_PATH`).

### CSV Format

The CSV should have the following headers:

```
Track Name,File Name,KEY TITLE,Track Number,Album,Psudo-Tags,Previous Titles
```

Example row:
```
Haunting Tavern,haunting_tavern_remst_fullmix.mp3,HAUNTING_TAVERN_REMST_FULLMIX,1,Secrets of Strahd Original Soundtrack,"peaceful, town, village, horror, sos",
```

- **KEY TITLE**: Unique identifier used in playlist definitions
- **File Name**: Filename in S3 (stored at `s3://bucket/audio/{filename}`)

### Google Sheets

You can use a Google Sheets URL directly:

```bash
TRACKS_CSV_PATH=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit?gid=0
```

---

## Playlist Definitions

Playlists are loaded from a CSV file or Google Sheets (set via `PLAYLISTS_CSV_PATH`).

### CSV Format

The CSV should have the following columns:

| Playlist Title | Track Key |
|----------------|-----------|
| Tavern Ambience | HAUNTING_TAVERN_REMST_FULLMIX |
| Tavern Ambience | TAVERN_BUSTLE |
| Combat Epic | BATTLE_EPIC1 |
| Combat Epic | BATTLE_EPIC2 |

Tracks are grouped by `Playlist Title` and appended in order.

### Google Sheets

You can use a Google Sheets URL directly:

```bash
PLAYLISTS_CSV_PATH=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit?gid=0
```

The sheet must be publicly accessible (or "Anyone with the link can view").

---

## S3/CloudFront Setup

Audio files should be stored in S3 with the path prefix `/audio/`:

```
s3://your-bucket/
└── audio/
    ├── haunting_tavern_remst_fullmix.mp3
    ├── battle_epic_01.mp3
    └── ...
```

CloudFront should be configured with:
- Origin pointing to your S3 bucket
- Signed URL requirement (restricted viewer access)
- Key pair for signing (private key stored locally)

---

## Run

```bash
python3 radio.py
```

Or with `uvicorn` manually:

```bash
uvicorn radio:service.app --reload --host 0.0.0.0 --port 5000
```

---

## Authentication

This server reads Express-compatible signed cookies (e.g., `s:<value>.<sig>`) and validates them using HMAC SHA256.

Session data is loaded from Redis using the key format:

```text
frc:sess:<sid>
```

`frc:sess:` is configurable via `SESSION_REDIS_PREFIX`.

Expected JSON structure:

```json
{
  "user": "user_id_value",
  "cookie": {}
}
```

---

## API Endpoints

### `GET /`
Returns the main landing page (`index.html`).

### `GET /listen?channel=some_channel`
Returns the listener interface.

### `GET /host?channel=some_channel`
Requires login. Shows host controls for managing the specified channel.

### `GET /playlists`
Requires login. Returns available playlist names.

Response format:
```json
{
  "playlists": ["tavern_ambience", "combat_epic", "exploration"]
}
```

### `POST /command`
Requires login. Controls playback or switches playlists.

Send a command (next/stop):
```json
{
  "channel": "my_channel",
  "command": "next"
}
```

Or switch to a playlist by name:
```json
{
  "channel": "my_channel",
  "playlist": "tavern_ambience"
}
```

### `GET /stream?channel=some_channel`
Streams MP3 audio for that channel.

### `GET /admin`
Requires login and email in `ADMIN_EMAILS` whitelist. Shows admin panel with reload controls.

### `POST /admin/reload`
Requires login and email in `ADMIN_EMAILS` whitelist. Reloads tracks and playlists from their configured sources.

Response:
```json
{
  "status": "ok",
  "message": "Tracks and playlists reloaded"
}
```

---

## Reloading Data

Tracks and playlists can be reloaded without restarting the server:

### Via Admin UI
Navigate to `/admin` (requires whitelisted email) and click the reload button.

### Via CLI
```bash
python reload_tracks_cli.py
```

This sends `SIGHUP` to the running server process.

### Via Signal
```bash
kill -HUP $(pgrep -f "python.*radio.py")
```

---

## Notes

- Audio files are streamed from CloudFront via signed URLs (3-day expiry)
- Signed URLs are cached in Redis to avoid regeneration on every play (refreshed 1 hour before expiry)
- If Redis is unavailable, the server falls back to generating fresh URLs
- FFmpeg reads directly from the signed URL and transcodes to MP3
- The server streams `.mp3`, `.wav`, `.ogg`, `.flac` files (any format FFmpeg supports)
- You must have `ffmpeg` installed and accessible from the command line
- Background streamer threads terminate if no listeners connect for `IDLE_TIMEOUT` seconds (default 600)

---

## Deploy (Systemd)

This repo includes local deploy and service scripts for the same droplet workflow used in dm-dash.

Deploy from local:

```bash
./scripts/deploy.sh
```

What deploy does:
1. SSHes to `root@165.227.88.65`
2. Ensures `/root/music_stream_server` is a git checkout (re-clones if `.git` is missing)
3. Pulls `origin main`
4. Runs `python3 -m pip install --no-cache-dir -r requirements.txt`
5. Installs/updates `systemd/radio.service` and restarts `radio.service`
6. Runs a local health check on `http://127.0.0.1:5000/`

Service commands:

```bash
./scripts/service.sh status
./scripts/service.sh logs
./scripts/service.sh restart
./scripts/service.sh stop
```

Optional overrides:

```bash
MUSIC_SERVER=root@your-server-ip MUSIC_BRANCH=main ./scripts/deploy.sh
```
