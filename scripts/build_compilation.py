#!/usr/bin/env python3
"""Build one public Radio sampler from selected tracks in free FRC playlists."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloudfront import get_signed_url  # noqa: E402
from playlists import get_playlist, is_pro_playlist  # noqa: E402
from tracks import get_track_info  # noqa: E402

SELECTION = Path(__file__).with_name("radio_sampler_selection.json")
OUTPUT = ROOT / "static" / "audio"


def duration_of(url: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", url],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError("could not read master duration")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("master duration is unavailable") from exc


def run_ffmpeg(args: list[str], timeout: int = 120) -> None:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True, timeout=timeout, check=False,
    )
    if result.returncode:
        # FFmpeg may echo the signed master URL in errors; keep it out of logs.
        raise RuntimeError("FFmpeg could not encode audio")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds-per-track", type=int, default=10)
    args = parser.parse_args()
    if not 2 <= args.seconds_per_track <= 25:
        parser.error("seconds per track must be between 2 and 25")

    selection = json.loads(SELECTION.read_text())
    if not isinstance(selection, list) or not 1 <= len(selection) <= 20:
        raise ValueError("Select between 1 and 20 tracks")

    seen = set()
    tracks = []
    for item in selection:
        playlist, key = item["playlist"], item["key"]
        if not playlist.startswith("- FRC - ") or is_pro_playlist(playlist):
            raise ValueError(f"Selection is not a free FRC playlist: {playlist}")
        if key in seen or key not in (get_playlist(playlist) or []):
            raise ValueError(f"Duplicate or missing track in selection: {key}")
        info = get_track_info(key)
        if not info:
            raise ValueError(f"Track metadata missing: {key}")
        seen.add(key)
        tracks.append((item, info))

    OUTPUT.mkdir(parents=True, exist_ok=True)
    catalog = []
    seconds = args.seconds_per_track
    with tempfile.TemporaryDirectory(prefix="frc-radio-sampler-") as working:
        temp = Path(working)
        segment_paths = []
        for index, (item, info) in enumerate(tracks):
            key = item["key"]
            url = get_signed_url(info["filename"])
            duration = duration_of(url)
            if duration < seconds:
                raise ValueError(f"Track is shorter than {seconds} seconds: {key}")
            start = min(max(0.0, float(item.get("start_seconds", duration * 0.3))), duration - seconds)
            segment = temp / f"segment-{index:02d}.wav"
            run_ffmpeg([
                "-ss", f"{start:.3f}", "-i", url, "-t", str(seconds), "-vn",
                "-af", f"afade=t=in:st=0:d=0.25,afade=t=out:st={seconds - 0.35}:d=0.35",
                "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", "-f", "wav", str(segment),
            ])
            if segment.stat().st_size < 10_000:
                raise RuntimeError(f"Segment was empty: {key}")
            segment_paths.append(segment)
            catalog.append({
                "key": key,
                "title": info.get("title") or key.replace("_", " ").title(),
                "playlist": item["playlist"].removeprefix("- FRC - "),
                "at_seconds": index * seconds,
            })
            print(f"{index + 1}/{len(tracks)} {catalog[-1]['title']}", flush=True)

        list_file = temp / "segments.txt"
        list_file.write_text("".join(f"file '{path}'\n" for path in segment_paths))
        temporary = OUTPUT / "radio-sampler.mp3.tmp"
        try:
            run_ffmpeg([
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "2",
                "-metadata", "title=Far Reach Radio Sampler", "-f", "mp3", "-y", str(temporary),
            ], timeout=180)
            if temporary.stat().st_size < 100_000:
                raise RuntimeError("Compilation was empty")
            temporary.replace(OUTPUT / "radio-sampler.mp3")
        finally:
            temporary.unlink(missing_ok=True)

    (OUTPUT / "radio-sampler.json").write_text(json.dumps({
        "duration_seconds": len(catalog) * seconds,
        "tracks": catalog,
    }, indent=2) + "\n")
    print(f"Ready: {len(catalog)} tracks, {len(catalog) * seconds} seconds", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
