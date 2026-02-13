import queue
import time
import random
import threading
import subprocess
import logging

from config import CHUNK_SIZE, IDLE_TIMEOUT
from tracks import get_track_filename, get_track_info
from playlists import get_playlist
from cloudfront import get_signed_url

logger = logging.getLogger("radio")


class AudioStreamer:
    def __init__(self, playlist_name: str):
        self.playlist_name = playlist_name
        self.listener_queues = {}  # channel_name -> set[Queue]
        self.listener_queues_lock = threading.Lock()
        self.command_queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)

        self.last_listener_time = time.time()
        # Current playing track metadata (updated while streaming)
        self.current_track_key = None
        self.current_track_filename = None
        self.current_track_title = None
        self.current_track_album = None

    def start(self):
        if not self.thread.is_alive():
            self.thread.start()

    def has_listeners(self) -> bool:
        with self.listener_queues_lock:
            return any(len(queues) > 0 for queues in self.listener_queues.values())

    def add_listener(self, channel_name, q):
        with self.listener_queues_lock:
            if channel_name not in self.listener_queues:
                self.listener_queues[channel_name] = set()
            self.listener_queues[channel_name].add(q)

        # Presence matters more than sound
        self.last_listener_time = time.time()

    def remove_listener(self, channel_name, q):
        with self.listener_queues_lock:
            if channel_name in self.listener_queues:
                self.listener_queues[channel_name].discard(q)
                if not self.listener_queues[channel_name]:
                    del self.listener_queues[channel_name]

    def put_command(self, cmd: str):
        self.command_queue.put(cmd)

    def _run(self):
        try:
            self._run_loop()
        except Exception:
            logger.exception(f"[Streamer] Fatal error in streamer for playlist '{self.playlist_name}'")

    def _run_loop(self):
        while True:
            track_keys = get_playlist(self.playlist_name)
            if not track_keys:
                logger.warning(f"[Streamer] Playlist '{self.playlist_name}' not found or empty.")
                time.sleep(5)
                continue

            tracks = []
            for key in track_keys:
                filename = get_track_filename(key)
                if filename:
                    tracks.append((key, filename))
                else:
                    logger.warning(f"[Streamer] Track key '{key}' not found in registry.")

            if not tracks:
                logger.warning(f"[Streamer] No valid tracks found for playlist '{self.playlist_name}'. Waiting...")
                time.sleep(5)
                continue

            random.shuffle(tracks)

            for track_key, track_filename in tracks:
                # fetch metadata for this track
                track_info = get_track_info(track_key)
                title = track_info.get("title") if track_info else None
                album = track_info.get("album") if track_info else None

                # Update currently-playing metadata for listeners and API
                self.current_track_key = track_key
                self.current_track_filename = track_filename
                self.current_track_title = title
                self.current_track_album = album
                track_url = get_signed_url(track_filename)
                logger.info(
                    f"Now playing: {track_key} ({track_filename}) - {title or ''}"
                )

                try:
                    proc = subprocess.Popen(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel", "quiet",
                            "-re",
                            "-i", track_url,
                            "-vn",
                            "-acodec", "libmp3lame",
                            "-ar", "44100",
                            "-b:a", "128k",
                            "-f", "mp3",
                            "-",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    )
                except FileNotFoundError:
                    logger.error("FFmpeg not found in PATH")
                    time.sleep(5)
                    continue
                except Exception as e:
                    logger.error(f"Failed to start FFmpeg: {e}")
                    time.sleep(5)
                    continue

                try:
                    while True:
                        # --- commands ---
                        try:
                            cmd = self.command_queue.get_nowait()
                            if cmd == "stop":
                                logger.info("[Streamer] Stopped.")
                                return
                            elif cmd == "next":
                                logger.info("[Streamer] Skipping track.")
                                break
                        except queue.Empty:
                            pass

                        # --- idle detection ---
                        if self.has_listeners():
                            self.last_listener_time = time.time()
                        elif time.time() - self.last_listener_time > IDLE_TIMEOUT:
                            logger.info(
                                f"[Streamer] No listeners for {IDLE_TIMEOUT} seconds. Exiting."
                            )
                            return

                        # --- audio read ---
                        if proc.stdout is None:
                            logger.error("[Streamer] FFmpeg stdout is None, skipping track")
                            break
                        chunk = proc.stdout.read(CHUNK_SIZE)

                        if not chunk:
                            logger.info("[Streamer] End of track reached.")
                            break

                        with self.listener_queues_lock:
                            for listeners in self.listener_queues.values():
                                for q in listeners:
                                    try:
                                        q.put_nowait(chunk)
                                    except queue.Full:
                                        pass

                finally:
                    # Clear current track state when finished or on error
                    self.current_track_key = None
                    self.current_track_filename = None
                    self.current_track_title = None
                    self.current_track_album = None
                    if proc.poll() is None:
                        proc.kill()
                    if proc.stdout:
                        proc.stdout.close()
                    proc.wait()
                    if proc.returncode and proc.returncode != 0:
                        logger.warning(f"[Streamer] FFmpeg exited with code {proc.returncode} for track '{track_key}'")
