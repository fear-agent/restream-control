"""Managed experimental Streamlink -> FFmpeg feeds for OBS Media Sources."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import app_state

FEED_DIR = app_state.STATE_DIR / "media_feeds"
WORKER_SCRIPT = app_state.APP_DIR / "media_feed_worker.py"
MAX_AUTO_RETRIES = 3
RETRY_DELAY_SECONDS = 5


def normalize_layout(layout: str | int | None = None) -> str:
    return "2P" if str(layout or "").strip().upper() in {"2", "2P"} else "4P"


def port_base(layout: str | int | None = None) -> int:
    try:
        value = int(app_state.load_config().get("media_feed_port_base", 5001))
        value = value if 1 <= value <= 65400 else 5001
    except (TypeError, ValueError):
        value = 5001
    # 4P retains the original addresses. 2P needs a separate address range
    # because OBS Media Sources can otherwise compete for the same UDP feed.
    return value + (100 if normalize_layout(layout) == "2P" else 0)


# Facecam is not a physical camera in media-feed mode. It is another
# independently cropped copy of the same runner feed for custom layouts.
MEDIA_PARTS = ("Stream", "Tracker", "Timer", "Facecam")


def port_for_slot(slot: int, part: str = "Stream", layout: str | int | None = None) -> int:
    """Give each cropable part its own local UDP output.

    A normal UDP feed can only be consumed reliably by one OBS Media Source.
    FFmpeg therefore sends three identical feeds per runner: Stream has audio,
    Tracker and Timer are muted inside OBS.
    """
    normalized_part = str(part).title()
    if normalized_part == "Facecam":
        # Keep the original Stream/Tracker/Timer addresses stable so an app
        # update never breaks existing OBS Media Source URLs.
        return port_base(layout) + 12 + (int(slot) - 1)
    try:
        part_offset = ("Stream", "Tracker", "Timer").index(normalized_part)
    except ValueError:
        part_offset = 0
    return port_base(layout) + ((int(slot) - 1) * 3) + part_offset


def source_url(slot: int, part: str = "Stream", layout: str | int | None = None) -> str:
    return f"udp://127.0.0.1:{port_for_slot(slot, part, layout)}?pkt_size=1316"


def state_path(slot: int) -> Path:
    return FEED_DIR / f"runner_{int(slot)}.json"


def log_path(slot: int) -> Path:
    return FEED_DIR / f"runner_{int(slot)}.log"


def load_state(slot: int) -> dict[str, Any]:
    data = app_state.load_json(state_path(slot), {})
    return data if isinstance(data, dict) else {}


def write_state(slot: int, **updates: Any) -> None:
    existing = load_state(slot)
    existing.update(updates)
    layout = normalize_layout(existing.get("layout"))
    existing["slot"] = int(slot)
    existing["layout"] = layout
    existing["ports"] = {part.lower(): port_for_slot(slot, part, layout) for part in MEDIA_PARTS}
    existing["source_urls"] = {part.lower(): source_url(slot, part, layout) for part in MEDIA_PARTS}
    existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
    app_state.save_json(state_path(slot), existing)


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def prereq_errors() -> list[str]:
    errors = []
    if not command_available("streamlink"):
        errors.append("Streamlink was not found. Install Streamlink and reopen Restream Control.")
    if not command_available("ffmpeg"):
        errors.append("FFmpeg was not found. Install FFmpeg and add its bin folder to Windows Path.")
    return errors


def is_worker_running(state: dict[str, Any]) -> bool:
    pid = state.get("worker_pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_slot(slot: int) -> None:
    state = load_state(slot)
    pid = state.get("worker_pid")
    if isinstance(pid, int) and pid > 0 and is_worker_running(state):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    write_state(slot, status="stopped", message="Stopped by Restream Control.", worker_pid=0)


def normalize_delay(delay_seconds: float | int | str | None) -> float:
    try:
        value = float(delay_seconds or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    return round(value, 3)


def start_slot(
    slot: int,
    display_name: str,
    twitch_name: str,
    quality: str,
    delay_seconds: float | int | str | None = 0,
    layout: str | int | None = None,
) -> None:
    errors = prereq_errors()
    if errors:
        raise RuntimeError("\n".join(errors))
    clean_twitch = str(twitch_name).strip().lstrip("@")
    if not clean_twitch:
        raise RuntimeError(f"Runner {slot} has no Twitch name.")

    delay = normalize_delay(delay_seconds)
    normalized_layout = normalize_layout(layout)
    stop_slot(slot)
    write_state(
        slot,
        status="starting",
        message="Starting Streamlink and FFmpeg...",
        display_name=str(display_name).strip() or clean_twitch,
        twitch_name=clean_twitch,
        quality=str(quality).strip() or "best",
        delay_seconds=delay,
        layout=normalized_layout,
        worker_pid=0,
    )

    worker_args = [
        "--slot", str(slot),
        "--display-name", str(display_name).strip() or clean_twitch,
        "--twitch-name", clean_twitch,
        "--quality", str(quality).strip() or "best",
        "--delay-seconds", str(delay),
        "--layout", normalized_layout,
    ]
    if app_state.IS_FROZEN:
        command = [sys.executable, "--media-feed-worker", *worker_args]
    else:
        command = [sys.executable, str(WORKER_SCRIPT), *worker_args]

    flags = 0
    startupinfo = None
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    process = subprocess.Popen(
        command,
        cwd=str(app_state.APP_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        startupinfo=startupinfo,
    )
    write_state(slot, worker_pid=process.pid, message="Starting Streamlink and FFmpeg...")


def restart_slot_with_delay(slot: int, delay_seconds: float | int | str) -> None:
    """Restart a feed using its saved runner data and a real FFmpeg timeshift."""
    state = load_state(slot)
    twitch = str(state.get("twitch_name") or "").strip()
    if not twitch:
        raise RuntimeError(f"R{slot} has no running media feed to delay.")
    start_slot(
        slot,
        str(state.get("display_name") or twitch),
        twitch,
        str(state.get("quality") or "best"),
        delay_seconds,
        state.get("layout"),
    )


def stop_all() -> None:
    for slot in range(1, 5):
        stop_slot(slot)


def all_states() -> dict[int, dict[str, Any]]:
    states: dict[int, dict[str, Any]] = {}
    for slot in range(1, 5):
        state = load_state(slot)
        if state and state.get("status") in {"starting", "retrying", "running"} and not is_worker_running(state):
            write_state(slot, status="stopped", message="Worker is no longer running.", worker_pid=0)
            state = load_state(slot)
        states[slot] = state
    return states


def worker_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restream Control media-feed worker")
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--twitch-name", required=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--delay-seconds", type=float, default=0)
    parser.add_argument("--layout", default="4P")
    args = parser.parse_args(argv)
    slot = args.slot
    if slot not in {1, 2, 3, 4}:
        raise SystemExit("slot must be 1 through 4")

    FEED_DIR.mkdir(parents=True, exist_ok=True)
    delay = normalize_delay(args.delay_seconds)
    layout = normalize_layout(args.layout)
    streamlink_cmd = [
        "streamlink", "--twitch-low-latency", "--stdout",
        f"https://twitch.tv/{args.twitch_name}", args.quality,
    ]
    def output_args(url: str) -> list[str]:
        if delay <= 0:
            return ["-f", "mpegts", url]
        # FFmpeg's fifo muxer buffers packets before writing them to its
        # underlying MPEG-TS output, creating a true live timeshift.
        queue_size = max(12000, min(300000, int(delay * 12000)))
        return [
            "-f", "fifo",
            "-fifo_format", "mpegts",
            "-queue_size", str(queue_size),
            "-timeshift", f"{delay:.3f}",
            url,
        ]

    ffmpeg_cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay",
        "-i", "pipe:0",
        # The main Stream output carries video and audio. Tracker and Timer
        # only need video, which keeps their sources out of OBS's audio mixer.
        "-map", "0:v?", "-map", "0:a?",
        "-c", "copy", "-muxdelay", "0", "-muxpreload", "0",
        *output_args(source_url(slot, "Stream", layout)),
        "-map", "0:v?", "-an",
        "-c", "copy", "-muxdelay", "0", "-muxpreload", "0",
        *output_args(source_url(slot, "Tracker", layout)),
        "-map", "0:v?", "-an",
        "-c", "copy", "-muxdelay", "0", "-muxpreload", "0",
        *output_args(source_url(slot, "Timer", layout)),
        "-map", "0:v?", "-an",
        "-c", "copy", "-muxdelay", "0", "-muxpreload", "0",
        *output_args(source_url(slot, "Facecam", layout)),
    ]
    child_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    child_startupinfo = None
    if os.name == "nt":
        child_startupinfo = subprocess.STARTUPINFO()
        child_startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        child_startupinfo.wShowWindow = 0
    log_file = log_path(slot).open("a", encoding="utf-8")
    last_error = ""
    try:
        for attempt in range(1, MAX_AUTO_RETRIES + 1):
            streamlink = None
            ffmpeg = None
            try:
                write_state(
                    slot,
                    status="starting",
                    message=f"Connecting Streamlink (attempt {attempt}/{MAX_AUTO_RETRIES})...",
                    worker_pid=os.getpid(),
                    retry_attempt=attempt,
                    display_name=args.display_name,
                    twitch_name=args.twitch_name,
                    quality=args.quality,
                    delay_seconds=delay,
                    layout=layout,
                )
                log_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Starting {args.twitch_name}, attempt {attempt}\n")
                log_file.flush()
                streamlink = subprocess.Popen(
                    streamlink_cmd,
                    stdout=subprocess.PIPE,
                    stderr=log_file,
                    creationflags=child_flags,
                    startupinfo=child_startupinfo,
                )
                assert streamlink.stdout is not None
                write_state(slot, status="starting", message=f"Starting FFmpeg (attempt {attempt}/{MAX_AUTO_RETRIES})...")
                ffmpeg = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=streamlink.stdout,
                    stderr=log_file,
                    creationflags=child_flags,
                    startupinfo=child_startupinfo,
                )
                streamlink.stdout.close()
                write_state(
                    slot,
                    status="running",
                    message="FFmpeg output started. Waiting for OBS video...",
                    worker_pid=os.getpid(),
                    streamlink_pid=streamlink.pid,
                    ffmpeg_pid=ffmpeg.pid,
                    retry_attempt=attempt,
                )
                while True:
                    if streamlink.poll() is not None:
                        last_error = f"Streamlink stopped (exit code {streamlink.returncode})."
                        break
                    if ffmpeg.poll() is not None:
                        last_error = f"FFmpeg stopped (exit code {ffmpeg.returncode})."
                        break
                    time.sleep(1)
            except Exception as exc:
                last_error = str(exc)
            finally:
                for process in (ffmpeg, streamlink):
                    if process is not None and process.poll() is None:
                        process.terminate()

            if attempt >= MAX_AUTO_RETRIES:
                write_state(
                    slot,
                    status="failed",
                    message=f"{last_error} Retries exhausted.",
                    worker_pid=0,
                    streamlink_pid=0,
                    ffmpeg_pid=0,
                    retry_attempt=attempt,
                )
                return 1

            write_state(
                slot,
                status="retrying",
                message=f"{last_error} Retrying in {RETRY_DELAY_SECONDS}s ({attempt}/{MAX_AUTO_RETRIES}).",
                worker_pid=os.getpid(),
                streamlink_pid=0,
                ffmpeg_pid=0,
                retry_attempt=attempt,
            )
            time.sleep(RETRY_DELAY_SECONDS)
    finally:
        log_file.close()
