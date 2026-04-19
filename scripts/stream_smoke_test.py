#!/usr/bin/env python3
"""
Open real listener connections and fail if the radio stream stalls or closes.

This is intentionally a black-box check. It exercises the same /stream and
/nowplaying endpoints a browser uses, so it can run against local dev, staging,
or production.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_BASE_URL = os.getenv("RADIO_BASE_URL", "https://radio.farreachco.com")
USER_AGENT = "farreach-radio-stream-smoke-test/1.0"


@dataclass
class ListenerResult:
    listener_id: int
    ok: bool = False
    status: int | None = None
    bytes_read: int = 0
    chunks_read: int = 0
    first_byte_seconds: float | None = None
    max_gap_seconds: float = 0.0
    elapsed_seconds: float = 0.0
    error: str | None = None
    closed_early: bool = False


def build_url(base_url: str, path: str, params: dict[str, str]) -> str:
    base = base_url.rstrip("/")
    return f"{base}{path}?{urllib.parse.urlencode(params)}"


def request_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body.decode("utf-8"))


def post_command(
    base_url: str, channel: str, playlist: str, cookie: str | None, timeout: float
) -> None:
    url = base_url.rstrip("/") + "/command"
    payload = json.dumps({"channel": channel, "playlist": playlist}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    if cookie:
        headers["Cookie"] = cookie

    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"POST /command returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        if exc.code in {301, 302, 303, 307, 308}:
            location = exc.headers.get("Location", "")
            raise RuntimeError(
                "POST /command redirected instead of starting the playlist. "
                f"Set --cookie or RADIO_SESSION_COOKIE with a valid login cookie. Location: {location}"
            ) from exc
        raise RuntimeError(f"POST /command returned HTTP {exc.code}: {body}") from exc


def run_listener(
    result: ListenerResult,
    base_url: str,
    channel: str,
    duration: float,
    read_size: int,
    read_timeout: float,
    max_gap_seconds: float,
) -> None:
    started_at = time.monotonic()
    deadline = started_at + duration
    url = build_url(
        base_url, "/stream", {"channel": channel, "_": str(int(time.time() * 1000))}
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=read_timeout) as response:
            result.status = response.status
            if response.status != 200:
                result.error = f"HTTP {response.status}"
                return

            last_chunk_at: float | None = None
            while time.monotonic() < deadline:
                try:
                    chunk = response.read(read_size)
                except (socket.timeout, TimeoutError) as exc:
                    result.error = f"read timed out after {read_timeout:.1f}s: {exc}"
                    return

                now = time.monotonic()
                if not chunk:
                    result.closed_early = True
                    result.error = "stream closed before duration completed"
                    return

                if result.chunks_read == 0:
                    result.first_byte_seconds = now - started_at
                elif last_chunk_at is not None:
                    gap = now - last_chunk_at
                    result.max_gap_seconds = max(result.max_gap_seconds, gap)
                    if gap > max_gap_seconds:
                        result.error = (
                            f"stream gap {gap:.1f}s exceeded --max-gap-seconds "
                            f"{max_gap_seconds:.1f}s"
                        )
                        return

                last_chunk_at = now
                result.chunks_read += 1
                result.bytes_read += len(chunk)

        result.closed_early = True
        result.error = "stream response ended"
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        result.status = exc.code
        result.error = f"HTTP {exc.code}: {body}"
    except urllib.error.URLError as exc:
        result.error = f"connection error: {exc.reason}"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.elapsed_seconds = time.monotonic() - started_at
        if (
            result.error is None
            and result.status == 200
            and result.bytes_read > 0
            and result.chunks_read > 0
            and not result.closed_early
        ):
            result.ok = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Black-box smoke test for Far Reach Radio stream continuity."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--channel")
    parser.add_argument(
        "--playlist",
        help="Optional playlist to start with POST /command before opening listeners.",
    )
    parser.add_argument(
        "--cookie",
        default=os.getenv("RADIO_SESSION_COOKIE"),
        help="Cookie header for authenticated /command, or set RADIO_SESSION_COOKIE.",
    )
    parser.add_argument("--duration", type=float, default=960.0)
    parser.add_argument("--listeners", type=int, default=2)
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--read-size", type=int, default=4096)
    parser.add_argument("--read-timeout", type=float, default=15.0)
    parser.add_argument("--max-gap-seconds", type=float, default=12.0)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable summary only."
    )
    args = parser.parse_args()

    if args.listeners < 1:
        parser.error("--listeners must be at least 1")
    if args.duration <= 0:
        parser.error("--duration must be positive")
    if not args.channel and not args.playlist:
        parser.error("--channel is required unless --playlist is provided")
    if not args.channel:
        args.channel = f"stream_smoke_{int(time.time())}"
    return args


def main() -> int:
    args = parse_args()

    command_error = None
    if args.playlist:
        try:
            post_command(
                args.base_url,
                args.channel,
                args.playlist,
                args.cookie,
                args.startup_timeout,
            )
        except Exception as exc:
            command_error = str(exc)

    polls: list[dict[str, Any]] = []
    if command_error is None:
        results = [ListenerResult(listener_id=i + 1) for i in range(args.listeners)]
        threads = [
            threading.Thread(
                target=run_listener,
                args=(
                    result,
                    args.base_url,
                    args.channel,
                    args.duration,
                    args.read_size,
                    args.read_timeout,
                    args.max_gap_seconds,
                ),
                daemon=True,
            )
            for result in results
        ]

        for thread in threads:
            thread.start()
            time.sleep(0.25)

        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline and any(
            thread.is_alive() for thread in threads
        ):
            poll_started = time.monotonic()
            poll: dict[str, Any] = {
                "elapsed_seconds": round(args.duration - (deadline - poll_started), 3)
            }
            try:
                poll.update(
                    request_json(
                        build_url(
                            args.base_url, "/nowplaying", {"channel": args.channel}
                        ),
                        timeout=args.startup_timeout,
                    )
                )
                poll["ok"] = True
            except Exception as exc:
                poll["ok"] = False
                poll["error"] = f"{type(exc).__name__}: {exc}"
            polls.append(poll)

            sleep_for = min(args.poll_interval, max(0.0, deadline - time.monotonic()))
            if sleep_for:
                time.sleep(sleep_for)

        for thread in threads:
            thread.join(timeout=1)
    else:
        results = []

    summary = {
        "ok": command_error is None and all(result.ok for result in results),
        "base_url": args.base_url,
        "channel": args.channel,
        "playlist": args.playlist,
        "duration_seconds": args.duration,
        "listeners": [asdict(result) for result in results],
        "nowplaying_polls": polls,
        "command_error": command_error,
    }

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"base_url={args.base_url}")
        print(f"channel={args.channel}")
        if args.playlist:
            print(f"playlist={args.playlist}")
        if command_error:
            print(f"command_error={command_error}")
        for result in results:
            status = "PASS" if result.ok else "FAIL"
            print(
                f"listener {result.listener_id}: {status} "
                f"status={result.status} bytes={result.bytes_read} "
                f"chunks={result.chunks_read} max_gap={result.max_gap_seconds:.2f}s "
                f"elapsed={result.elapsed_seconds:.1f}s"
                + (f" error={result.error}" if result.error else "")
            )
        failed_polls = [poll for poll in polls if not poll.get("ok")]
        print(f"nowplaying_polls={len(polls)} failed_polls={len(failed_polls)}")
        print("result=PASS" if summary["ok"] else "result=FAIL")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
