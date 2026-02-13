import logging
import urllib.error
from config import PLAYLISTS_CSV_PATH, PRO_PLAYLISTS_CSV_PATH
from sheets_utils import read_csv

logger = logging.getLogger("radio.playlists")

# Playlist registry: Playlist Title -> list of Track Keys
_playlists: dict[str, list[str]] = {}

# Pro playlist registry: set of playlist names requiring pro status (None = not yet loaded)
_pro_playlists: set[str] | None = None


def _load_playlists():
    """Load playlists from CSV file or Google Sheets URL.

    Expects columns: "Playlist Title", "Track Key"
    Builds playlists by appending each track to its playlist.
    """
    global _playlists
    new_playlists: dict[str, list[str]] = {}

    try:
        logger.info(f"Loading playlists from {PLAYLISTS_CSV_PATH}...")
        reader, file_handle = read_csv(PLAYLISTS_CSV_PATH)

        for row in reader:
            playlist_title = row.get("Playlist Title", "").strip()
            track_key = row.get("Track Key", "").strip()
            if playlist_title and track_key:
                if playlist_title not in new_playlists:
                    new_playlists[playlist_title] = []
                new_playlists[playlist_title].append(track_key)

        if file_handle:
            file_handle.close()

        _playlists = new_playlists
        logger.info(f"Loaded {len(_playlists)} playlists")

    except FileNotFoundError:
        logger.error(f"Playlists CSV not found: {PLAYLISTS_CSV_PATH}")
    except urllib.error.URLError as e:
        logger.error(f"Failed to fetch playlists from URL: {e}")
    except Exception as e:
        logger.error(f"Failed to load playlists CSV: {e}")


def _load_pro_playlists():
    """Load pro playlist names from CSV file or Google Sheets URL.

    Expects column: "Playlist Title"
    """
    global _pro_playlists
    new_pro: set[str] = set()

    try:
        logger.info(f"Loading pro playlists from {PRO_PLAYLISTS_CSV_PATH}...")
        reader, file_handle = read_csv(PRO_PLAYLISTS_CSV_PATH)

        for row in reader:
            playlist_title = row.get("Playlist Title", "").strip()
            if playlist_title:
                new_pro.add(playlist_title)

        if file_handle:
            file_handle.close()

        _pro_playlists = new_pro
        logger.info(f"Loaded {len(_pro_playlists)} pro playlists")

    except FileNotFoundError:
        logger.warning(f"Pro playlists CSV not found: {PRO_PLAYLISTS_CSV_PATH}. All playlists will be free.")
        _pro_playlists = set()
    except urllib.error.URLError as e:
        logger.error(f"Failed to fetch pro playlists from URL: {e}")
    except Exception as e:
        logger.error(f"Failed to load pro playlists CSV: {e}")


def is_pro_playlist(name: str) -> bool:
    """Check if a playlist requires pro status."""
    if _pro_playlists is None:
        _load_pro_playlists()
    return name in _pro_playlists


def reload_pro_playlists():
    """Force reload pro playlists from CSV."""
    global _pro_playlists
    _pro_playlists = None
    _load_pro_playlists()


def get_playlist(name: str) -> list[str] | None:
    """Get track keys for a playlist."""
    if not _playlists:
        _load_playlists()
    return _playlists.get(name)


def get_all_playlists() -> list[str]:
    """Get all playlist names."""
    if not _playlists:
        _load_playlists()
    return list(_playlists.keys())


def get_free_playlists() -> list[str]:
    """Get playlist names excluding pro-only playlists."""
    if not _playlists:
        _load_playlists()
    if _pro_playlists is None:
        _load_pro_playlists()
    return [name for name in _playlists if name not in _pro_playlists]


def reload_playlists():
    """Force reload playlists from CSV."""
    global _playlists
    _playlists = {}
    _load_playlists()
