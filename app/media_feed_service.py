"""Managed Streamlink HTTP feeds for OBS Media Sources."""
from __future__ import annotations

import argparse
import os
import shutil
import socket
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
STABLE_LATENCY_MODE = "Stable"
LOW_LATENCY_MODE = "Low latency"
SYNC_FILTER_NAME = "Restream Control Sync Delay"
MAX_DIRECT_SYNC_DELAY_SECONDS = 20.0
LOG_TAIL_BYTES = 64 * 1024


def normalize_layout(layout: str | int | None = None) -> str:
    return "2P" if str(layout or "").strip().upper() in {"2", "2P"} else "4P"


def port_base(layout: str | int | None = None) -> int:
    try:
        value = int(app_state.load_config().get("media_feed_port_base", 5001))
        value = value if 1 <= value <= 65400 else 5001
    except (TypeError, ValueError):
        value = 5001
    # 4P retains the original ports. 2P uses a separate range so both sets of
    # persistent OBS Media Sources can exist without sharing an HTTP server.
    return value + (100 if normalize_layout(layout) == "2P" else 0)


# Facecam is not a physical camera in media-feed mode. It is another cropped
# scene-item reference to the same runner feed in custom layouts.
MEDIA_PARTS = ("Stream", "Tracker", "Timer", "Facecam")


def port_for_slot(slot: int, part: str = "Stream", layout: str | int | None = None) -> int:
    """Return the legacy-compatible port assigned to a runner crop part."""
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
    port = port_for_slot(slot, part, layout)
    return f"http://127.0.0.1:{port}/"


def feed_source_url(slot: int, layout: str | int | None = None) -> str:
    """Return the single local HTTP feed OBS should decode for this runner."""
    return source_url(slot, "Stream", layout)


def state_path(slot: int) -> Path:
    return FEED_DIR / f"runner_{int(slot)}.json"


def log_path(slot: int) -> Path:
    return FEED_DIR / f"runner_{int(slot)}.log"


def stream_activity(slot: int) -> str:
    """Return the current Streamlink session's observed video availability."""
    path = log_path(slot)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - LOG_TAIL_BYTES), os.SEEK_SET)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return "unknown"

    # Logs append across races. Only signals after the latest worker start
    # belong to the runner currently assigned to this slot.
    start_index = text.rfind("] Starting ")
    if start_index >= 0:
        text = text[start_index:]
    offline_index = text.rfind("Stream not available")
    # An HTTP request only proves that OBS reached the local server. Streamlink
    # can accept that request while the Twitch channel is still unavailable.
    playing_index = text.rfind("Opening stream:")
    if offline_index > playing_index:
        return "offline"
    if playing_index >= 0:
        return "playing"
    return "unknown"


def load_state(slot: int) -> dict[str, Any]:
    data = app_state.load_json(state_path(slot), {})
    return data if isinstance(data, dict) else {}


def write_state(slot: int, **updates: Any) -> None:
    existing = load_state(slot)
    existing.update(updates)
    # Remove state left by retired Direct-feed experiments. Current workers do
    # not read these values, and retaining them makes a later race look as if
    # it silently reverted to an older transport mode.
    for obsolete_key in (
        "feed_profile",
        "stability_mode",
        "ffmpeg_pid",
        "relay_port",
        "relay_packets",
        "relay_bytes",
        "relay_errors",
        "relay_last_packet_at",
        "relay_buffered_bytes",
        "relay_buffered_packets",
        "relay_control_supported",
        "relay_delay_seconds",
    ):
        existing.pop(obsolete_key, None)
    layout = normalize_layout(existing.get("layout"))
    existing["slot"] = int(slot)
    existing["layout"] = layout
    feed_url = feed_source_url(slot, layout)
    existing["port"] = port_for_slot(slot, "Stream", layout)
    existing["source_url"] = feed_url
    # Keep these compatibility fields readable by older UI builds. In v2 all
    # logical crop parts point at one OBS input rather than separate decoders.
    existing["ports"] = {part.lower(): existing["port"] for part in MEDIA_PARTS}
    existing["source_urls"] = {part.lower(): feed_url for part in MEDIA_PARTS}
    existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
    app_state.save_json(state_path(slot), existing)


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def prereq_errors() -> list[str]:
    errors = []
    if not command_available("streamlink"):
        errors.append("Streamlink was not found. Install Streamlink and reopen Restream Control.")
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
    layout = normalize_layout(state.get("layout"))
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
    stop_obs_receiver(slot, layout)
    write_state(
        slot,
        status="stopped",
        message="Stopped by Restream Control.",
        worker_pid=0,
        streamlink_pid=0,
        http_port=0,
        obs_video_detected=False,
    )


def normalize_delay(delay_seconds: float | int | str | None) -> float:
    try:
        value = float(delay_seconds or 0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    return round(value, 3)


def normalize_latency_mode(value: str | None) -> str:
    return LOW_LATENCY_MODE if str(value or "").strip().lower() == "low latency" else STABLE_LATENCY_MODE


def streamlink_command(
    twitch_name: str,
    quality: str,
    latency_mode: str,
    http_port: int,
) -> list[str]:
    command = ["streamlink"]
    if normalize_latency_mode(latency_mode) == LOW_LATENCY_MODE:
        command.append("--twitch-low-latency")
    else:
        command.extend(["--hls-live-edge", "3"])
    command.extend([
        "--stream-segment-attempts", "5",
        "--stream-segment-threads", "2",
        "--retry-open", "3",
        "--player-external-http",
        "--player-external-http-interface", "127.0.0.1",
        "--player-external-http-port", str(int(http_port)),
        "--player-external-http-continuous", "yes",
        f"https://twitch.tv/{twitch_name}",
        quality,
    ])
    return command


def wait_for_http_server(process: subprocess.Popen[Any], port: int, timeout: float = 15.0) -> bool:
    """Wait until Streamlink's loopback HTTP listener accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def set_obs_sync_delay(slot: int, layout: str | int | None, delay_seconds: float | int | str) -> None:
    """Delay one Direct source with OBS's native async video delay filter."""
    delay = normalize_delay(delay_seconds)
    if delay > MAX_DIRECT_SYNC_DELAY_SECONDS:
        raise RuntimeError(
            f"Direct to OBS supports sync delays up to {MAX_DIRECT_SYNC_DELAY_SECONDS:g} seconds. "
            "Use Standard VLC for a longer delay."
        )
    source_name = f"{normalize_layout(layout)} R{int(slot)} Media Stream"
    import obs_crop_service

    client = obs_crop_service.connect()
    filters = list(getattr(client.get_source_filter_list(source_name), "filters", []) or [])
    existing = next(
        (item for item in filters if str(item.get("filterName") or "") == SYNC_FILTER_NAME),
        None,
    )
    if delay <= 0:
        if existing is not None:
            client.remove_source_filter(source_name, SYNC_FILTER_NAME)
        return
    settings = {"delay_ms": int(round(delay * 1000))}
    if existing is None:
        client.create_source_filter(
            source_name,
            SYNC_FILTER_NAME,
            "async_delay_filter",
            settings,
        )
    else:
        client.set_source_filter_settings(source_name, SYNC_FILTER_NAME, settings, True)
        client.set_source_filter_enabled(source_name, SYNC_FILTER_NAME, True)


def clear_obs_sync_delay(slot: int, layout: str | int | None) -> None:
    try:
        set_obs_sync_delay(slot, layout, 0)
    except Exception:
        # Starting a feed must still work when OBS is closed or the source has
        # not been created yet.
        pass


def restart_obs_receiver(slot: int, layout: str, log_file: Any) -> None:
    """Reconnect OBS after a new Streamlink HTTP server takes over a runner port."""
    source_name = f"{normalize_layout(layout)} R{int(slot)} Media Stream"
    try:
        import obs_crop_service

        obs_crop_service.connect().trigger_media_input_action(
            source_name,
            "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
        )
        log_file.write(
            f"[{datetime.now().isoformat(timespec='seconds')}] Restarted OBS receiver {source_name}\n"
        )
        log_file.flush()
    except Exception as exc:
        # The feed must still work when OBS is closed or websocket is disabled.
        log_file.write(
            f"[{datetime.now().isoformat(timespec='seconds')}] OBS receiver restart skipped: {exc}\n"
        )
        log_file.flush()


def stop_obs_receiver(slot: int, layout: str | int | None) -> None:
    """Stop OBS reconnect attempts after a Direct feed is deliberately stopped."""
    source_name = f"{normalize_layout(layout)} R{int(slot)} Media Stream"
    try:
        import obs_crop_service

        obs_crop_service.connect().trigger_media_input_action(
            source_name,
            "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP",
        )
    except Exception:
        # Stopping the worker must still succeed when OBS is closed or the
        # Direct layout has not been created yet.
        pass


def set_obs_video_detected(slot: int, detected: bool) -> None:
    """Persist an explicit OBS signal check so automatic UI refreshes keep it."""
    state = load_state(slot)
    if state.get("status") != "running":
        return
    latency = normalize_latency_mode(str(state.get("latency_mode") or STABLE_LATENCY_MODE))
    message = (
        f"OBS video detected. Streamlink HTTP feed is running in {latency} mode."
        if detected
        else f"Streamlink HTTP feed ready in {latency} mode. Waiting for OBS video..."
    )
    write_state(slot, obs_video_detected=bool(detected), message=message)


def start_slot(
    slot: int,
    display_name: str,
    twitch_name: str,
    quality: str,
    delay_seconds: float | int | str | None = 0,
    layout: str | int | None = None,
    latency_mode: str | None = None,
) -> None:
    errors = prereq_errors()
    if errors:
        raise RuntimeError("\n".join(errors))
    clean_twitch = str(twitch_name).strip().lstrip("@")
    if not clean_twitch:
        raise RuntimeError(f"Runner {slot} has no Twitch name.")

    delay = normalize_delay(delay_seconds)
    normalized_layout = normalize_layout(layout)
    normalized_latency = normalize_latency_mode(
        latency_mode or str(app_state.load_config().get("media_feed_latency", STABLE_LATENCY_MODE))
    )
    stop_slot(slot)
    if delay <= 0:
        clear_obs_sync_delay(slot, normalized_layout)
    write_state(
        slot,
        status="starting",
        message="Starting Streamlink HTTP feed...",
        display_name=str(display_name).strip() or clean_twitch,
        twitch_name=clean_twitch,
        quality=str(quality).strip() or "best",
        delay_seconds=delay,
        latency_mode=normalized_latency,
        layout=normalized_layout,
        worker_pid=0,
        obs_video_detected=False,
    )

    worker_args = [
        "--slot", str(slot),
        "--display-name", str(display_name).strip() or clean_twitch,
        "--twitch-name", clean_twitch,
        "--quality", str(quality).strip() or "best",
        "--delay-seconds", str(delay),
        "--layout", normalized_layout,
        "--latency-mode", normalized_latency,
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
    write_state(slot, worker_pid=process.pid, message="Starting Streamlink HTTP feed...")


def restart_slot_with_delay(slot: int, delay_seconds: float | int | str) -> None:
    """Apply a Direct delay in OBS without restarting the feed pipeline."""
    state = load_state(slot)
    twitch = str(state.get("twitch_name") or "").strip()
    if not twitch:
        raise RuntimeError(f"R{slot} has no running media feed to delay.")
    delay = normalize_delay(delay_seconds)
    if state.get("status") != "running" or not is_worker_running(state):
        raise RuntimeError(f"R{slot} does not have a running Direct feed to delay.")
    set_obs_sync_delay(slot, state.get("layout"), delay)
    write_state(
        slot,
        delay_seconds=delay,
        message=(
            f"OBS is applying a {delay:g}s async sync delay."
            if delay > 0
            else "Running at live playback."
        ),
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
    parser.add_argument("--latency-mode", default=STABLE_LATENCY_MODE)
    args = parser.parse_args(argv)
    slot = args.slot
    if slot not in {1, 2, 3, 4}:
        raise SystemExit("slot must be 1 through 4")

    FEED_DIR.mkdir(parents=True, exist_ok=True)
    delay = normalize_delay(args.delay_seconds)
    layout = normalize_layout(args.layout)
    requested_latency = normalize_latency_mode(args.latency_mode)
    child_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    child_startupinfo = None
    if os.name == "nt":
        child_startupinfo = subprocess.STARTUPINFO()
        child_startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        child_startupinfo.wShowWindow = 0
    log_file = log_path(slot).open("a", encoding="utf-8")
    http_port = port_for_slot(slot, "Stream", layout)
    last_error = ""
    try:
        # OBS decodes this runner once over loopback HTTP. Stream, Tracker,
        # Timer, and Facecam are scene-item references to this one input.
        for attempt in range(1, MAX_AUTO_RETRIES + 1):
            streamlink = None
            try:
                # A requested low-latency connection gets one attempt. If it
                # fails, retry with Streamlink's normal HLS edge so one
                # incompatible Twitch channel cannot remain unusable.
                active_latency = requested_latency if attempt == 1 else STABLE_LATENCY_MODE
                streamlink_cmd = streamlink_command(
                    args.twitch_name,
                    args.quality,
                    active_latency,
                    http_port,
                )
                write_state(
                    slot,
                    status="starting",
                    message=f"Connecting Streamlink in {active_latency} mode (attempt {attempt}/{MAX_AUTO_RETRIES})...",
                    worker_pid=os.getpid(),
                    retry_attempt=attempt,
                    display_name=args.display_name,
                    twitch_name=args.twitch_name,
                    quality=args.quality,
                    latency_mode=active_latency,
                    delay_seconds=delay,
                    layout=layout,
                    transport="http",
                    http_port=http_port,
                    obs_video_detected=False,
                )
                log_file.write(
                    f"\n[{datetime.now().isoformat(timespec='seconds')}] Starting {args.twitch_name}, "
                    f"attempt {attempt}, mode={active_latency}, delay={delay:g}s\n"
                )
                log_file.flush()
                streamlink = subprocess.Popen(
                    streamlink_cmd,
                    stdout=log_file,
                    stderr=log_file,
                    creationflags=child_flags,
                    startupinfo=child_startupinfo,
                )
                if not wait_for_http_server(streamlink, http_port):
                    raise RuntimeError(
                        f"Streamlink HTTP server did not open 127.0.0.1:{http_port}."
                    )
                write_state(
                    slot,
                    status="running",
                    message=f"Streamlink HTTP feed ready in {active_latency} mode. Waiting for OBS video...",
                    worker_pid=os.getpid(),
                    streamlink_pid=streamlink.pid,
                    transport="http",
                    http_port=http_port,
                    obs_video_detected=False,
                    retry_attempt=attempt,
                )
                # The HTTP listener is ready before OBS reconnects. Unlike the
                # old UDP relay, no packets from the new timestamp timeline can
                # accumulate in OBS before its demuxer is reopened.
                restart_obs_receiver(slot, layout, log_file)
                while True:
                    if streamlink.poll() is not None:
                        last_error = f"Streamlink stopped (exit code {streamlink.returncode})."
                        break
                    time.sleep(1)
            except Exception as exc:
                last_error = str(exc)
            finally:
                if streamlink is not None and streamlink.poll() is None:
                    streamlink.terminate()

            if attempt >= MAX_AUTO_RETRIES:
                write_state(
                    slot,
                    status="failed",
                    message=f"{last_error} Retries exhausted.",
                    worker_pid=0,
                    streamlink_pid=0,
                    http_port=0,
                    retry_attempt=attempt,
                )
                return 1

            write_state(
                slot,
                status="retrying",
                message=f"{last_error} Retrying in {RETRY_DELAY_SECONDS}s ({attempt}/{MAX_AUTO_RETRIES}).",
                worker_pid=os.getpid(),
                streamlink_pid=0,
                http_port=http_port,
                retry_attempt=attempt,
            )
            time.sleep(RETRY_DELAY_SECONDS)
    finally:
        log_file.close()
