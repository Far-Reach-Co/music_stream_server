import logging
import urllib.error
from config import TRACKS_CSV_PATH
from sheets_utils import read_csv

logger = logging.getLogger("radio.tracks")

# Track registry: KEY TITLE -> metadata dict with keys: filename, title, album
_tracks: dict[str, dict] = {}


def _load_tracks():
    """Load tracks from CSV file or Google Sheets URL."""
    global _tracks
    new_tracks: dict[str, str] = {}

    try:
        logger.info(f"Loading tracks from {TRACKS_CSV_PATH}...")
        reader, file_handle = read_csv(TRACKS_CSV_PATH)

        for row in reader:
            key = row.get("KEY TITLE", "").strip()
            filename = row.get("File Name", "").strip()
            title = row.get("Track Name", "").strip() or row.get("Title", "").strip()
            album = row.get("Album", "").strip()
            if key and filename:
                new_tracks[key] = {
                    "filename": filename,
                    "title": title or None,
                    "album": album or None,
                }

        if file_handle:
            file_handle.close()

        _tracks = new_tracks
        logger.info(f"Loaded {len(_tracks)} tracks")

    except FileNotFoundError:
        logger.error(f"Tracks CSV not found: {TRACKS_CSV_PATH}")
    except urllib.error.URLError as e:
        logger.error(f"Failed to fetch tracks from URL: {e}")
    except Exception as e:
        logger.error(f"Failed to load tracks CSV: {e}")


def get_track_filename(key: str) -> str | None:
    """Get filename for a track key."""
    if not _tracks:
        _load_tracks()
    info = _tracks.get(key)
    return info.get("filename") if info else None


def get_track_info(key: str) -> dict | None:
    """Get metadata for a track key: returns dict with filename, title, album."""
    if not _tracks:
        _load_tracks()
    return _tracks.get(key)


def get_all_track_keys() -> list[str]:
    """Get all available track keys."""
    if not _tracks:
        _load_tracks()
    return list(_tracks.keys())


def get_track_count() -> int:
    """Get the number of loaded tracks."""
    return len(_tracks)


def reload_tracks():
    """Force reload tracks from CSV."""
    _load_tracks()
