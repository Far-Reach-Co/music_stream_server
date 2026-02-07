import base64
import hashlib
import hmac
import queue
import re
import signal
import urllib.parse
import logging
import psycopg2
import uvicorn

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import (
    LISTENER_QUEUE_MAXSIZE,
    SILENT_BUFFER,
    SESSION_COOKIE_NAME,
    SESSION_SECRET,
    SESSION_DB_DSN,
    HOST,
    PORT,
    LOGIN_URL,
    ADMIN_EMAILS,
    DEV_MODE,
    DEV_USER_EMAIL,
)
from tracks import reload_tracks
from playlists import get_playlist, get_all_playlists, reload_playlists
from channel import Channel
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("radio")
logger.level = logging.INFO

limiter = Limiter(key_func=get_remote_address)


async def rate_limit_handler(request: Request, exc: Exception):
    detail = exc.detail if isinstance(exc, RateLimitExceeded) else str(exc)
    return JSONResponse(
        status_code=429,
        content={"error": "Too Many Requests", "detail": str(detail)},
    )


class RadioWebService:
    MAX_CHANNEL_NAME_LENGTH = 256

    def __init__(self):
        self.app = FastAPI()
        self.channels = {}
        self.streamers = {}
        self.app.state.limiter = limiter
        self.app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
        self.app.add_middleware(
            BaseHTTPMiddleware, dispatch=self.create_session_middleware()
        )
        self.app.mount("/static", StaticFiles(directory="static"), name="static")
        self._define_routes()

    def _validate_channel_name(self, name: str) -> tuple[bool, str]:
        """Validate channel name format and length."""
        if not name or not isinstance(name, str):
            return False, "Channel name required"

        name = name.strip()
        if len(name) > self.MAX_CHANNEL_NAME_LENGTH:
            return False, "Channel name too long"

        # Whitelist allowed characters
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            return False, "Channel name contains invalid characters"

        return True, name

    def _get_channel(self, name: str) -> Channel:
        if name not in self.channels:
            logger.info(f"[Channel] Creating new channel: {name}")
            self.channels[name] = Channel(name)
        return self.channels[name]

    def create_session_middleware(self):
        async def session_middleware(request: Request, call_next):
            cookie = request.cookies.get(SESSION_COOKIE_NAME)
            if not cookie:
                logger.info("[Session] No session cookie")
                return await call_next(request)

            valid, session_id = self.verify_express_cookie(cookie, SESSION_SECRET)
            if not valid:
                logger.info("[Session] Invalid signature")
                return await call_next(request)

            try:
                with psycopg2.connect(SESSION_DB_DSN) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT sess FROM session WHERE sid = %s AND expire > NOW()",
                            (session_id,),
                        )
                        row = cur.fetchone()
                        if not row:
                            logger.info("[Session] Session expired or not found")
                            return await call_next(request)

                        session_data = row[0]
                        request.state.session_data = session_data
                        request.state.user_id = session_data.get("user")
            except psycopg2.OperationalError as e:
                logger.warning(f"[Session] DB connection error: {e}")
            except psycopg2.ProgrammingError as e:
                logger.error(f"[Session] DB query error: {e}")
            except Exception as e:
                logger.error(f"[Session] Unexpected error: {e}", exc_info=True)

            return await call_next(request)

        return session_middleware

    def verify_express_cookie(self, cookie_str: str, secret: str):
        def base64_to_base64url(s):
            return s.replace("+", "-").replace("/", "_").rstrip("=")

        cookie_str = urllib.parse.unquote(cookie_str)

        if not cookie_str.startswith("s:") or len(cookie_str) < 3:
            logger.warning(
                "[VerifyCookie] Invalid cookie format"
            )
            return False, None

        try:
            value, sig = cookie_str[2:].split(".", 1)
        except ValueError:
            logger.warning(
                "[VerifyCookie] Failed to split cookie into value and signature."
            )
            return False, None

        expected_sig = hmac.new(
            secret.encode(), msg=value.encode(), digestmod=hashlib.sha256
        ).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()

        # Convert incoming cookie signature to Base64URL format
        cookie_sig_urlsafe = base64_to_base64url(sig)

        if hmac.compare_digest(expected_sig_b64, cookie_sig_urlsafe):
            logger.info("[VerifyCookie] Signature valid")
            return True, value
        else:
            logger.info("[VerifyCookie] Signature mismatch")
            return False, None

    async def login_required(self, request: Request):
        if DEV_MODE:
            request.state.user_id = 0
            request.state.dev_mode = True
            return
        if not getattr(request.state, "user_id", None):
            raise HTTPException(
                status_code=307,
                detail="Redirecting to login",
                headers={"Location": LOGIN_URL},
            )
        # Helper to load an HTML file and inject the footer snippet server-side
    def _render_file_with_footer(self, relpath: str):
        try:
            base = Path(__file__).parent
            file_path = base / relpath
            footer_path = base / "static" / "footer.html"
            if not file_path.exists():
                return FileResponse(relpath)

            html = file_path.read_text(encoding="utf-8")
            footer_html = footer_path.read_text(encoding="utf-8") if footer_path.exists() else ""

            # Replace placeholder div if present, else append before </body>
            placeholder = '<div id="site-footer" aria-hidden="true"></div>'
            if placeholder in html:
                html = html.replace(placeholder, footer_html)
            else:
                html = html.replace("</body>", footer_html + "</body>")

            return Response(content=html, media_type="text/html")
        except Exception as e:
            logger.exception("[Render] Error injecting footer")
            return FileResponse(relpath)
        
    def _define_routes(self):
        @self.app.get("/robots.txt")
        @limiter.limit("60/minute")
        def robots_txt(request: Request):
            return FileResponse("static/robots.txt", media_type="text/plain")

        @self.app.get("/")
        @limiter.limit("30/minute")
        def index(request: Request):
            return self._render_file_with_footer("static/index.html")

        @self.app.get("/listen")
        @limiter.limit("30/minute")
        def listen(request: Request):
            channel_name = request.query_params.get("channel", "").strip()
            valid, result = self._validate_channel_name(channel_name)
            if not valid:
                return Response(result, status_code=400)

            # serve listener page with server-side footer injection
            return self._render_file_with_footer("static/listener.html")

        @self.app.get("/host")
        @limiter.limit("20/minute")
        async def host(
            request: Request,
            _: None = Depends(self.login_required),
        ):
            return self._render_file_with_footer("static/host.html")

        @self.app.get("/admin")
        @limiter.limit("20/minute")
        async def admin_page(
            request: Request,
            _: None = Depends(self.login_required),
        ):
            # Check if user is in admin whitelist
            if getattr(request.state, "dev_mode", False):
                user_email = DEV_USER_EMAIL
            else:
                user_id = getattr(request.state, "user_id", None)
                if not user_id:
                    raise HTTPException(status_code=401, detail="Unauthorized")

                try:
                    with psycopg2.connect(SESSION_DB_DSN) as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                'SELECT email FROM "public"."User" WHERE id = %s',
                                (user_id,),
                            )
                            row = cur.fetchone()
                            if not row:
                                raise HTTPException(status_code=404, detail="User not found")
                            user_email = row[0]
                except psycopg2.Error as e:
                    logger.error(f"[Admin] DB error: {e}")
                    raise HTTPException(status_code=500, detail="Database error")

            if user_email not in ADMIN_EMAILS:
                raise HTTPException(status_code=403, detail="Forbidden")

            return FileResponse("static/admin.html")

        @self.app.get("/playlists")
        @limiter.limit("30/minute")
        def get_playlists_route(
            request: Request,
            _: None = Depends(self.login_required),
        ):
            return {"playlists": get_all_playlists()}

        @self.app.post("/admin/reload")
        @limiter.limit("5/minute")
        async def admin_reload(
            request: Request,
            _: None = Depends(self.login_required),
        ):
            # In dev mode, use configured dev email
            if getattr(request.state, "dev_mode", False):
                user_email = DEV_USER_EMAIL
                logger.info(f"[Admin] Dev mode - using email: {user_email}")
            else:
                user_id = getattr(request.state, "user_id", None)
                if not user_id:
                    return {"error": "Unauthorized"}, 401

                # Query users table for email
                try:
                    with psycopg2.connect(SESSION_DB_DSN) as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                'SELECT email FROM "public"."User" WHERE id = %s',
                                (user_id,),
                            )
                            row = cur.fetchone()
                            if not row:
                                logger.warning(f"[Admin] User {user_id} not found in users table")
                                return {"error": "User not found"}, 404
                            user_email = row[0]
                except Exception as e:
                    logger.error(f"[Admin] DB error looking up user email: {e}")
                    return {"error": "Database error"}, 500

            # Check if email is in admin whitelist
            if user_email not in ADMIN_EMAILS:
                logger.warning(f"[Admin] Unauthorized reload attempt by {user_email}")
                return {"error": "Forbidden"}, 403

            # Reload both tracks and playlists
            logger.info(f"[Admin] Reload triggered by {user_email}")
            reload_tracks()
            reload_playlists()

            return {"status": "ok", "message": "Tracks and playlists reloaded"}

        @self.app.post("/command")
        @limiter.limit("60/minute")
        async def command(
            request: Request,
            _: None = Depends(self.login_required),
        ):
            try:
                data = await request.json()
            except Exception as e:
                logger.warning(f"[Command] Invalid JSON: {e}")
                return {"error": "Invalid JSON"}, 400

            if not isinstance(data, dict):
                return {"error": "Expected JSON object"}, 400

            cmd = data.get("command")
            channel_name = data.get("channel", "")
            playlist_name = data.get("playlist")

            valid, result = self._validate_channel_name(channel_name)
            if not valid:
                return {"error": result}, 400

            channel_name = result  # Use validated/normalized name
            try:
                channel = self._get_channel(channel_name)
                if playlist_name:
                    # Validate playlist exists
                    if get_playlist(playlist_name) is None:
                        return {"error": "Playlist not found"}, 400

                    channel.play_playlist(playlist_name, self.streamers)
                elif cmd:
                    channel.send_command(cmd, self.streamers)
                else:
                    return {"error": "Missing command or playlist"}, 400
                return {"status": "ok", "channel": channel_name}
            except Exception as e:
                logger.error(f"[Command] Error: {e}")
                return {"error": str(e)}, 500

        @self.app.get("/stream")
        @limiter.limit("10/minute")
        async def stream(request: Request):
            channel_name = request.query_params.get("channel", "").strip()
            valid, result = self._validate_channel_name(channel_name)
            if not valid:
                return Response(content=result, status_code=400)

            channel_name = result  # Use validated/normalized name
            try:
                channel = self._get_channel(channel_name)
                playlist = channel.current_playlist
                if not playlist or playlist not in self.streamers:
                    return Response(content="Channel not active", status_code=400)

                q = queue.Queue(maxsize=LISTENER_QUEUE_MAXSIZE)
                self.streamers[playlist].add_listener(channel_name, q)

                try:
                    q.put_nowait(SILENT_BUFFER)
                except queue.Full:
                    pass

                def generate():
                    logger.info(f"[Stream] Client connected to {channel_name}")
                    try:
                        yield SILENT_BUFFER
                        while True:
                            try:
                                chunk = q.get(timeout=5)
                            except queue.Empty:
                                chunk = SILENT_BUFFER
                            yield chunk
                    finally:
                        self.streamers[playlist].remove_listener(channel_name, q)
                        if not self.streamers[playlist].listener_queues.get(
                            channel_name
                        ):
                            logger.info(
                                f"[Channel] No more listeners on '{channel_name}', removing channel"
                            )
                            del self.channels[channel_name]

                return StreamingResponse(
                    generate(),
                    media_type="audio/mpeg",
                    headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                )

            except Exception as e:
                logger.exception("[Stream] Unhandled exception")
                return Response(content=str(e), status_code=500)

        @self.app.get("/nowplaying")
        @limiter.limit("30/minute")
        def now_playing(request: Request):
            channel_name = request.query_params.get("channel", "").strip()
            valid, result = self._validate_channel_name(channel_name)
            if not valid:
                return Response(content=result, status_code=400)

            channel = self._get_channel(result)
            playlist = channel.current_playlist
            if not playlist or playlist not in self.streamers:
                return {"playlist": playlist, "track_key": None, "file_name": None}

            streamer = self.streamers[playlist]
            return {
                "playlist": playlist,
                "track_key": getattr(streamer, "current_track_key", None),
                "file_name": getattr(streamer, "current_track_filename", None),
                "track_title": getattr(streamer, "current_track_title", None),
                "album": getattr(streamer, "current_track_album", None),
            }


# === Signal Handler for Data Reload ===
def _handle_sighup(signum, frame):
    """Handle SIGHUP to reload tracks and playlists from source."""
    logger.info("[Signal] Received SIGHUP, reloading tracks and playlists...")
    reload_tracks()
    reload_playlists()


signal.signal(signal.SIGHUP, _handle_sighup)


# === Main Entrypoint ===
if __name__ == "__main__":
    # Load tracks and playlists on startup
    logger.info("Loading tracks and playlists...")
    reload_tracks()
    reload_playlists()

    service = RadioWebService()
    logger.info(f"Server running at http://{HOST}:{PORT}")
    uvicorn.run(service.app, host=HOST, port=PORT)
