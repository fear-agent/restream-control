#!/usr/bin/env python3
"""
Restream Control Launcher

Expected folder:
  Launcher/
    start_crosskeys_control.bat
    launch_crosskeys.py
    runners.csv
    cropping_tool.py
    obs_crop_helper_ws.py  (old name, optional)
    capture_runner_screenshots.ps1
    obs_text/

This script:
  - launches 2P/4P Streamlink/VLC runner windows with OBS-safe titles
  - writes OBS text files for runner names and commentators
  - opens the Cropping Tool
  - runs the screenshot capture PowerShell helper
  - relaunches/replaces one runner slot without rebuilding the whole race setup
  - edits OBS runner/comm text without relaunching streams
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import app_state

ROOT = app_state.APP_DIR
REPO_ROOT = app_state.REPO_ROOT
RUNNERS_CSV = app_state.config_path("runner_csv")
OBS_TEXT_DIR = app_state.config_path("obs_text_dir")
LAST_SETUP = ROOT / "race_setup_last.txt"
# Prefer 720-class streams for consistent VLC window size, but allow 1080 if Twitch offers no lower transcodes.
QUALITY = str(app_state.load_config().get("quality", app_state.DEFAULT_CONFIG["quality"]))


def vlc_player_args() -> str:
    args = ["--no-video-title-show", "--no-osd", "--no-qt-privacy-ask", "--play-and-pause"]
    vlc_audio_device = str(app_state.load_config().get("vlc_audio_device", "")).strip()
    if vlc_audio_device:
        args.extend(["--aout=mmdevice", f"--mmdevice-audio-device={vlc_audio_device}"])
    args.append("{playerinput}")
    return " ".join(args)

SOURCE_TITLES = {
    1: "RUNNER 1",
    2: "RUNNER 2",
    3: "RUNNER 3",
    4: "RUNNER 4",
}

@dataclass
class Runner:
    display_name: str
    twitch_name: str
    aliases: tuple[str, ...] = ()


def clean(s: str) -> str:
    return (s or "").strip()


def norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", clean(s).lower())


def normalize_twitch_input(value: str) -> str:
    """Accept @name, twitch.tv/name, https://twitch.tv/name, or plain name."""
    s = clean(value)
    if not s:
        return ""
    if s.startswith("@"):
        s = s[1:].strip()

    # Strip URL prefix.
    s = re.sub(r"^https?://", "", s, flags=re.I)
    s = re.sub(r"^www\.", "", s, flags=re.I)

    # Strip twitch.tv/ if present.
    if s.lower().startswith("twitch.tv/"):
        s = s.split("/", 1)[1]

    # Take only first path segment and remove query/fragment.
    s = s.split("/", 1)[0]
    s = s.split("?", 1)[0]
    s = s.split("#", 1)[0]
    return s.strip()


def parse_aliases(value: str) -> tuple[str, ...]:
    aliases = [clean(p) for p in re.split(r"\s*(?:,|;|\|)\s*", value or "") if clean(p)]
    return tuple(dict.fromkeys(aliases))


def is_probable_twitch_name(value: str) -> bool:
    s = normalize_twitch_input(value)
    return bool(re.fullmatch(r"[A-Za-z0-9_]{2,25}", s))


def load_runners() -> list[Runner]:
    if not RUNNERS_CSV.exists():
        print(f"WARNING: runners.csv not found at {RUNNERS_CSV}")
        return []

    rows: list[Runner] = []
    with RUNNERS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []

        # Accept old or new headers.
        lower_headers = {h.lower().strip(): h for h in reader.fieldnames}
        display_key = (
            lower_headers.get("display_name")
            or lower_headers.get("discord name")
            or lower_headers.get("name")
            or reader.fieldnames[0]
        )
        twitch_key = (
            lower_headers.get("twitch_name")
            or lower_headers.get("twitch name")
            or lower_headers.get("twitch")
            or (reader.fieldnames[1] if len(reader.fieldnames) > 1 else reader.fieldnames[0])
        )
        aliases_key = lower_headers.get("aliases") or lower_headers.get("alias")

        for row in reader:
            display = clean(row.get(display_key, ""))
            twitch = normalize_twitch_input(row.get(twitch_key, ""))
            if display and twitch:
                aliases = parse_aliases(row.get(aliases_key, "") if aliases_key else "")
                rows.append(Runner(display, twitch, aliases))

    return rows


def runner_exists(twitch_name: str) -> bool:
    twitch = normalize_twitch_input(twitch_name)
    return any(norm_key(r.twitch_name) == norm_key(twitch) for r in load_runners())


def csv_keys(fieldnames: list[str]) -> tuple[str, str, str | None]:
    lower_headers = {h.lower().strip(): h for h in fieldnames}
    display_key = lower_headers.get("display_name") or lower_headers.get("discord name") or lower_headers.get("name") or fieldnames[0]
    twitch_key = lower_headers.get("twitch_name") or lower_headers.get("twitch name") or lower_headers.get("twitch") or (fieldnames[1] if len(fieldnames) > 1 else fieldnames[0])
    aliases_key = lower_headers.get("aliases") or lower_headers.get("alias")
    return display_key, twitch_key, aliases_key


def read_runner_csv_rows() -> tuple[list[str], list[dict[str, str]]]:
    if not RUNNERS_CSV.exists() or RUNNERS_CSV.stat().st_size == 0:
        return ["display_name", "twitch_name", "aliases"], []
    with RUNNERS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or ["display_name", "twitch_name", "aliases"], list(reader)


def write_runner_csv_rows(fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    display_key, _twitch_key, _aliases_key = csv_keys(fieldnames)
    rows.sort(key=lambda item: norm_key(item.get(display_key, "")))
    RUNNERS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RUNNERS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def add_alias_to_existing_runner(twitch_name: str, alias: str) -> bool:
    alias = clean(alias)
    twitch = normalize_twitch_input(twitch_name)
    if not alias or not twitch:
        return False

    fieldnames, rows = read_runner_csv_rows()
    display_key, twitch_key, aliases_key = csv_keys(fieldnames)
    if aliases_key is None:
        aliases_key = "aliases"
        fieldnames.append(aliases_key)
        for row in rows:
            row[aliases_key] = ""

    changed = False
    for row in rows:
        if norm_key(normalize_twitch_input(row.get(twitch_key, ""))) != norm_key(twitch):
            continue
        existing_values = {norm_key(row.get(display_key, "")), norm_key(row.get(twitch_key, ""))}
        aliases = list(parse_aliases(row.get(aliases_key, "")))
        existing_values.update(norm_key(value) for value in aliases)
        if norm_key(alias) not in existing_values:
            aliases.append(alias)
            row[aliases_key] = ";".join(aliases)
            changed = True
        break

    if changed:
        write_runner_csv_rows(fieldnames, rows)
    return changed


def add_runner_to_csv(runner: Runner, aliases: str = "") -> bool:
    if runner_exists(runner.twitch_name):
        return False

    fieldnames, rows = read_runner_csv_rows()
    display_key, twitch_key, aliases_key = csv_keys(fieldnames)
    if aliases_key is None:
        aliases_key = "aliases"
        fieldnames.append(aliases_key)
        for existing in rows:
            existing[aliases_key] = ""

    row = {key: "" for key in fieldnames}
    row[display_key] = runner.display_name
    row[twitch_key] = runner.twitch_name
    row[aliases_key] = aliases

    rows.append(row)
    write_runner_csv_rows(fieldnames, rows)
    return True


def prompt_save_runner(runner: Runner) -> None:
    if runner_exists(runner.twitch_name):
        if add_alias_to_existing_runner(runner.twitch_name, runner.display_name):
            print("Added alias to existing runners.csv entry.")
        return
    yn = input(f"Save {runner.display_name} / twitch.tv/{runner.twitch_name} to runners.csv? [Y/n]: ").strip().lower()
    if yn in ("", "y", "yes"):
        if add_runner_to_csv(runner):
            print("Saved to runners.csv.")


def print_runner_list(runners: list[Runner]) -> None:
    print()
    print("Saved runner list:")
    for i, r in enumerate(runners, start=1):
        print(f"{i:>3}. {r.display_name}  -  twitch.tv/{r.twitch_name}")
    print()


def choose_from_matches(matches: list[Runner], label: str) -> Optional[Runner]:
    print()
    print(f"Multiple matches for {label}:")
    for i, r in enumerate(matches, start=1):
        print(f"{i:>2}. {r.display_name}  -  twitch.tv/{r.twitch_name}")
    print(" 0. Cancel / type again")
    choice = input("Choose number: ").strip()
    if choice.isdigit():
        n = int(choice)
        if n == 0:
            return None
        if 1 <= n <= len(matches):
            return matches[n - 1]
    print("Invalid choice.")
    return None


def find_runner(query: str, runners: list[Runner]) -> Optional[Runner]:
    q_raw = clean(query)
    q = norm_key(q_raw)
    if not q:
        return None

    # Number from list.
    if q_raw.isdigit():
        n = int(q_raw)
        if 1 <= n <= len(runners):
            r = runners[n - 1]
            print(f"Selected #{n}: {r.display_name} - twitch.tv/{r.twitch_name}")
            return r

    # Exact display/twitch/alias.
    exact = [
        r for r in runners
        if norm_key(r.display_name) == q
        or norm_key(r.twitch_name) == q
        or any(norm_key(alias) == q for alias in r.aliases)
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return choose_from_matches(exact, q_raw)

    # Partial display/twitch/alias.
    partial = [
        r for r in runners
        if q in norm_key(r.display_name)
        or q in norm_key(r.twitch_name)
        or any(q in norm_key(alias) for alias in r.aliases)
    ]
    if len(partial) == 1:
        r = partial[0]
        yn = input(f"Use {r.display_name} - twitch.tv/{r.twitch_name}? [Y/n]: ").strip().lower()
        if yn in ("", "y", "yes"):
            return r
        return None
    if len(partial) > 1:
        return choose_from_matches(partial, q_raw)

    return None


def prompt_runner(slot: int, runners: list[Runner]) -> Runner:
    while True:
        print()
        raw = input(f"Runner {slot} name / number / @twitch / list: ").strip()
        if not raw:
            print("Please enter a runner.")
            continue

        if raw.lower() == "list":
            print_runner_list(runners)
            continue

        # Manual forced twitch forms.
        if raw.startswith("@") or "twitch.tv/" in raw.lower() or raw.lower().startswith("http"):
            twitch = normalize_twitch_input(raw)
            if is_probable_twitch_name(twitch):
                display = input(f"Display name for twitch.tv/{twitch} [{twitch}]: ").strip() or twitch
                runner = Runner(display, twitch)
                prompt_save_runner(runner)
                return runner
            print(f"That does not look like a Twitch name: {raw}")
            continue

        r = find_runner(raw, runners)
        if r:
            return r

        # No CSV match. Offer manual.
        twitch = normalize_twitch_input(raw)
        if is_probable_twitch_name(twitch):
            yn = input(f"No saved match. Use twitch.tv/{twitch} manually? [y/N]: ").strip().lower()
            if yn in ("y", "yes"):
                display = input(f"Display name for twitch.tv/{twitch} [{twitch}]: ").strip() or twitch
                runner = Runner(display, twitch)
                prompt_save_runner(runner)
                return runner

        print("No runner selected. Type 'list' to choose by number, or use @twitchname for a manual entry.")


def write_text_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def update_obs_text_files(mode: int, selected: dict[int, Runner], comms: str = "") -> None:
    OBS_TEXT_DIR.mkdir(exist_ok=True)

    for slot in range(1, 5):
        value = selected[slot].display_name if slot in selected else ""
        write_text_file(OBS_TEXT_DIR / f"runner{slot}.txt", value)

    write_text_file(OBS_TEXT_DIR / "comm_names.txt", comms)
    write_text_file(OBS_TEXT_DIR / "race_mode.txt", f"{mode}P")


def get_vlc_player() -> str:
    candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return "vlc"


def launch_stream(slot: int, runner: Runner) -> None:
    title = SOURCE_TITLES[slot]
    url = f"https://twitch.tv/{runner.twitch_name}"
    player = get_vlc_player()

    cmd = [
        "streamlink",
        "--twitch-low-latency",
        "--player-no-close",
        "--player", player,
        "--player-args", vlc_player_args(),
        "--title", title,
        url,
        QUALITY,
    ]

    print(f"Launching {title}: {runner.display_name} - {url}")
    try:
        # Detach Streamlink from this launcher console so closing/restarting the control panel
        # does not kill active VLC/Streamlink feeds.
        if os.name == "nt":
            flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                creationflags=flags,
                startupinfo=startupinfo,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(cmd, cwd=str(ROOT))
    except FileNotFoundError:
        print("ERROR: streamlink was not found. Confirm Streamlink is installed and available in PowerShell/CMD.")
    except Exception as exc:
        print(f"ERROR launching {title}: {exc}")


def format_comms(raw: str) -> str:
    raw = clean(raw)
    if not raw:
        return ""
    parts = [clean(p) for p in re.split(r"\s*(?:,|&|\+|;)\s*", raw) if clean(p)]
    return " & ".join(parts)


def prompt_comms() -> str:
    print()
    raw = input("Commentators, separated by comma or &: ").strip()
    return format_comms(raw)


def save_last_setup(mode: int, selected: dict[int, Runner], comms: str) -> None:
    lines = [
        "Restream Last Setup",
        f"Saved: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}",
        f"Race type: {mode}P",
        f"Quality: {QUALITY}",
        "",
        "Runners:",
    ]
    for slot in range(1, mode + 1):
        r = selected.get(slot)
        if r:
            lines.append(f"  Runner {slot}: {r.display_name} - twitch.tv/{r.twitch_name}")
    lines.extend(["", f"Comms: {comms or '(blank)'}", ""])
    LAST_SETUP.write_text("\n".join(lines), encoding="utf-8")
    app_state.save_current_race(mode, selected, comms)


def launch_race(mode: int) -> None:
    runners = load_runners()
    print()
    print("=" * 44)
    print(f"Launch {mode}P Race")
    print(f"Quality: {QUALITY}")
    print("=" * 44)

    selected: dict[int, Runner] = {}
    for slot in range(1, mode + 1):
        selected[slot] = prompt_runner(slot, runners)

    comms = prompt_comms()
    update_obs_text_files(mode, selected, comms)
    save_last_setup(mode, selected, comms)

    print()
    print("OBS text files updated.")
    for slot in range(1, mode + 1):
        launch_stream(slot, selected[slot])

    print()
    print("Next recommended steps:")
    print("  1. Capture runner screenshots from this launcher.")
    print("  2. Open Cropping Tool.")
    print("  3. Crop Stream / Tracker / Timer for each runner and Apply to OBS.")
    print()


def close_runner_window(slot: int) -> None:
    title = SOURCE_TITLES[slot]
    ps = f"""
$procs = Get-Process vlc -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowTitle -like "*{title}*" }}
foreach ($p in $procs) {{
    try {{
        $null = $p.CloseMainWindow()
        Start-Sleep -Milliseconds 500
        if (-not $p.HasExited) {{ $p.Kill() }}
    }} catch {{}}
}}
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def relaunch_slot() -> None:
    runners = load_runners()
    print()
    raw = input("Which slot to relaunch/replace? 1-4: ").strip()
    if raw not in {"1", "2", "3", "4"}:
        print("Invalid slot.")
        return
    slot = int(raw)

    new_runner = prompt_runner(slot, runners)
    yn = input(f"Close existing {SOURCE_TITLES[slot]} VLC window first? [Y/n]: ").strip().lower()
    if yn in ("", "y", "yes"):
        close_runner_window(slot)

    # Update only that runner text file.
    write_text_file(OBS_TEXT_DIR / f"runner{slot}.txt", new_runner.display_name)

    # Update last setup note as a small append, not a full rewrite.
    with LAST_SETUP.open("a", encoding="utf-8") as f:
        f.write(f"\nSlot {slot} relaunched at {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}: "
                f"{new_runner.display_name} - twitch.tv/{new_runner.twitch_name}\n")
        f.write(f"  Runner {slot}: {new_runner.display_name} - twitch.tv/{new_runner.twitch_name}\n")
    app_state.update_current_race_slot(slot, new_runner)

    launch_stream(slot, new_runner)



def focus_control_window() -> None:
    """Try to return keyboard focus to this control console after helper windows run."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

def capture_runner_screenshots(default_slots: str | None = None) -> None:
    ps1 = ROOT / "capture_runner_screenshots.ps1"
    if not ps1.exists():
        print(f"Missing screenshot script: {ps1}")
        return

    if default_slots is None:
        race = app_state.load_current_race()
        mode = race.get("mode")
        default_slots = "1,2" if mode == 2 else "1,2,3,4"

    raw = input(f"Slots to capture? Press Enter for {default_slots}, or type specific slots like 1 2: ").strip()
    if not raw:
        slots = default_slots
    else:
        parts = [p for p in re.split(r"[,\s]+", raw) if p in {"1", "2", "3", "4"}]
        if not parts:
            print("No valid slots entered.")
            return
        slots = ",".join(parts)

    print()
    print("Capturing screenshots...")
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(ps1),
        "-SlotList", slots,
    ]
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("PowerShell messages/errors:")
            print(result.stderr)
        focus_control_window()
    except Exception as exc:
        print(f"ERROR running screenshot capture: {exc}")


def delete_screenshots() -> None:
    folder = ROOT / "crop_screenshots"
    if not folder.exists():
        print(f"No screenshot folder found: {folder}")
        return

    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}]
    if not files:
        print("No screenshots to delete.")
        return

    print()
    print(f"Screenshot folder: {folder}")
    print(f"Found {len(files)} screenshot file(s).")
    yn = input("Delete all crop screenshots? Type DELETE to confirm: ").strip()
    if yn != "DELETE":
        print("Cancelled.")
        return

    deleted = 0
    failed = 0
    for f in files:
        try:
            f.unlink()
            deleted += 1
        except Exception as exc:
            failed += 1
            print(f"Could not delete {f.name}: {exc}")
    print(f"Deleted {deleted} screenshot(s)." + (f" Failed: {failed}." if failed else ""))


def open_python_tool(filename: str, label: str) -> None:
    path = ROOT / filename
    if not path.exists():
        print(f"Missing {label}: {path}")
        return

    print(f"Opening {label}...")
    try:
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen([sys.executable, str(path)], cwd=str(ROOT), creationflags=creationflags)
    except Exception as exc:
        print(f"ERROR opening {label}: {exc}")


def open_crop_helper() -> None:
    if (ROOT / "cropping_tool.py").exists():
        open_python_tool("cropping_tool.py", "Cropping Tool")
    elif (ROOT / "obs_crop_helper_ws.py").exists():
        open_python_tool("obs_crop_helper_ws.py", "Cropping Tool")
    elif (ROOT / "obs_crop_helper.py").exists():
        open_python_tool("obs_crop_helper.py", "Cropping Tool")
    else:
        print("No cropping tool found. Expected cropping_tool.py.")


def open_discord_ptb() -> None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        local / "DiscordPTB" / "Update.exe",
        local / "DiscordPTB" / "DiscordPTB.exe",
    ]

    for c in candidates:
        if c.exists():
            print(f"Opening Discord PTB: {c}")
            try:
                if c.name.lower() == "update.exe":
                    subprocess.Popen([str(c), "--processStart", "DiscordPTB.exe"])
                else:
                    subprocess.Popen([str(c)])
                return
            except Exception as exc:
                print(f"ERROR opening Discord PTB: {exc}")
                return

    print("Discord PTB not found in the usual location.")
    print(r"Expected something like: %LOCALAPPDATA%\DiscordPTB\Update.exe")



def open_stream_syncer() -> None:
    syncer = ROOT / "stream_syncer.py"
    if not syncer.exists():
        print(f"Sync tool not found: {syncer}")
        return
    try:
        subprocess.Popen([sys.executable, str(syncer)], cwd=str(ROOT), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        print("Opened Sync Tool.")
    except Exception as exc:
        print(f"Could not open Stream Syncer: {exc}")


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def edit_obs_text_names() -> None:
    """Edit one OBS text file without relaunching any runner streams."""
    OBS_TEXT_DIR.mkdir(exist_ok=True)
    while True:
        print()
        print("Edit OBS text names")
        print("1. Runner 1")
        print("2. Runner 2")
        print("3. Runner 3")
        print("4. Runner 4")
        print("5. Commentators")
        print("6. Back")
        choice = input("Choose which text to edit: ").strip()

        if choice in {"1", "2", "3", "4"}:
            slot = int(choice)
            path = OBS_TEXT_DIR / f"runner{slot}.txt"
            current = read_text_file(path)
            new_value = input(f"Runner {slot} display name [{current}]: ").strip()
            if new_value:
                write_text_file(path, new_value)
                print(f"Updated Runner {slot} to: {new_value}")
            else:
                print("No change.")
            return

        if choice == "5":
            path = OBS_TEXT_DIR / "comm_names.txt"
            current = read_text_file(path)
            raw = input(f"Commentators [{current}] (comma or & separated): ").strip()
            if raw:
                formatted = format_comms(raw)
                write_text_file(path, formatted)
                print(f"Updated commentators to: {formatted}")
            else:
                print("No change.")
            return

        if choice == "6":
            return

        print("Invalid choice.")


def show_last_setup() -> None:
    if LAST_SETUP.exists():
        print()
        print(LAST_SETUP.read_text(encoding="utf-8"))
    else:
        print("No last setup file found yet.")


def main_menu() -> None:
    while True:
        print()
        print("=" * 44)
        print(" Restream Control")
        print("=" * 44)
        print("1. Launch 2P race")
        print("2. Launch 4P race")
        print("3. Relaunch / replace one runner slot")
        print("4. Edit runner/comm text names")
        print("5. Take Screenshots")
        print("6. Open Cropping Tool")
        print("7. Delete Screenshots")
        print("8. Open Sync Tool")
        print("9. Open Discord PTB")
        print("10. Show Last Setup")
        print("11. Quit")
        print()
        choice = input("Choose: ").strip()

        if choice == "1":
            launch_race(2)
        elif choice == "2":
            launch_race(4)
        elif choice == "3":
            relaunch_slot()
        elif choice == "4":
            edit_obs_text_names()
        elif choice == "5":
            capture_runner_screenshots()
        elif choice == "6":
            open_crop_helper()
        elif choice == "7":
            delete_screenshots()
        elif choice == "8":
            open_stream_syncer()
        elif choice == "9":
            open_discord_ptb()
        elif choice == "10":
            show_last_setup()
        elif choice == "11":
            print("Bye.")
            return
        else:
            print("Invalid choice.")


def run_cli_action(argv: list[str]) -> bool:
    """Return True if a command-line action was handled."""
    if not argv:
        return False

    action = argv[0].strip().lower()
    if action in {"--launch", "launch"}:
        if len(argv) < 2 or argv[1] not in {"2", "4", "2p", "4p"}:
            print("Usage: launch_crosskeys.py --launch 2|4")
            return True
        mode = 2 if argv[1].startswith("2") else 4
        launch_race(mode)
        input("Press Enter to close...")
        return True

    if action in {"--replace", "replace"}:
        relaunch_slot()
        input("Press Enter to close...")
        return True

    if action in {"--screenshots", "screenshots"}:
        capture_runner_screenshots(argv[1] if len(argv) > 1 else None)
        input("Press Enter to close...")
        return True

    if action in {"--crop", "crop"}:
        open_crop_helper()
        return True

    if action in {"--sync", "sync"}:
        open_stream_syncer()
        return True

    if action in {"--discord", "discord"}:
        open_discord_ptb()
        return True

    if action in {"--delete-screenshots", "delete-screenshots"}:
        delete_screenshots()
        input("Press Enter to close...")
        return True

    if action in {"--last-setup", "last-setup"}:
        show_last_setup()
        input("Press Enter to close...")
        return True

    return False


if __name__ == "__main__":
    try:
        if not run_cli_action(sys.argv[1:]):
            main_menu()
    except KeyboardInterrupt:
        print()
        print("Cancelled.")
