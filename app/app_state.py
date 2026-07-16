from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
REPO_ROOT = APP_DIR if IS_FROZEN else APP_DIR.parent
STATE_DIR = APP_DIR / "state"
CONFIG_FILE = APP_DIR / "app_config.json"
CURRENT_RACE_FILE = STATE_DIR / "current_race.json"
CROP_PRESETS_FILE = STATE_DIR / "crop_presets.json"
LOG_FILE = STATE_DIR / "restream_app.log"
CRASH_LOG_FILE = STATE_DIR / "crash.log"

DEFAULT_CONFIG: dict[str, Any] = {
    "obs_text_dir": str(APP_DIR / "obs_text"),
    "screenshot_dir": str(APP_DIR / "crop_screenshots"),
    "runner_csv": str(REPO_ROOT / "data" / "runners.csv"),
    "quality": "720p60,720p,480p,360p,1080p60,1080p,best",
    "vlc_audio_device": "",
    "obs_websocket": {
        "host": "localhost",
        "port": 4455,
        "password": "",
    },
    "obs_source_map": {},
}


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_config() -> dict[str, Any]:
    data = load_json(CONFIG_FILE, {})
    config = DEFAULT_CONFIG.copy()
    config.update(data if isinstance(data, dict) else {})
    local_runner_csv = APP_DIR / "runners.csv"
    default_runner_csv = Path(DEFAULT_CONFIG["runner_csv"])
    try:
        configured_runner_csv = Path(str(config.get("runner_csv", ""))).expanduser()
        if local_runner_csv.exists() and configured_runner_csv.resolve() == default_runner_csv.resolve():
            config["runner_csv"] = str(local_runner_csv)
    except Exception:
        if local_runner_csv.exists():
            config["runner_csv"] = str(local_runner_csv)
    obs_defaults = DEFAULT_CONFIG["obs_websocket"].copy()
    obs_defaults.update(config.get("obs_websocket", {}) if isinstance(config.get("obs_websocket"), dict) else {})
    config["obs_websocket"] = obs_defaults
    if not isinstance(config.get("obs_source_map"), dict):
        config["obs_source_map"] = {}
    return config


def save_config(config: dict[str, Any]) -> None:
    current = load_config()
    current.update(config)
    save_json(CONFIG_FILE, current)


def config_path(name: str) -> Path:
    value = load_config().get(name, DEFAULT_CONFIG[name])
    return Path(str(value)).expanduser()


def runner_to_dict(runner: Any) -> dict[str, str]:
    return {
        "display_name": str(getattr(runner, "display_name", "")).strip(),
        "twitch_name": str(getattr(runner, "twitch_name", "")).strip(),
    }


def save_current_race(mode: int, selected: dict[int, Any], comms: str) -> None:
    runners = {str(slot): runner_to_dict(runner) for slot, runner in selected.items() if runner}
    data = {
        "mode": int(mode),
        "comms": comms,
        "runners": runners,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_json(CURRENT_RACE_FILE, data)
    append_log(f"Saved current race: {mode}P, {len(runners)} runner(s).")


def load_current_race() -> dict[str, Any]:
    data = load_json(CURRENT_RACE_FILE, {})
    return data if isinstance(data, dict) else {}


def update_current_race_slot(slot: int, runner: Any) -> None:
    data = load_current_race()
    runners = data.get("runners")
    if not isinstance(runners, dict):
        runners = {}
    runners[str(slot)] = runner_to_dict(runner)
    data["runners"] = runners
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(CURRENT_RACE_FILE, data)
    append_log(f"Updated current race slot {slot}: {runners[str(slot)].get('display_name', '')}.")


def normalize_layout(layout: str | int | None) -> str:
    value = str(layout or "").strip().upper()
    if value in {"2", "2P"}:
        return "2P"
    if value in {"4", "4P"}:
        return "4P"
    return "4P"


def crop_key(twitch_name: str, source_part: str, layout: str | int | None = None) -> str:
    return f"{normalize_layout(layout).lower()}::{twitch_name.strip().lower()}::{source_part.strip().lower()}"


def legacy_crop_key(twitch_name: str, source_part: str) -> str:
    return f"{twitch_name.strip().lower()}::{source_part.strip().lower()}"


def load_crop_presets() -> dict[str, Any]:
    data = load_json(CROP_PRESETS_FILE, {})
    return data if isinstance(data, dict) else {}


def get_crop_preset(twitch_name: str, source_part: str, layout: str | int | None = None) -> dict[str, Any] | None:
    presets = load_crop_presets()
    preset = presets.get(crop_key(twitch_name, source_part, layout))
    if not isinstance(preset, dict):
        preset = presets.get(legacy_crop_key(twitch_name, source_part))
    return preset if isinstance(preset, dict) else None


def save_crop_preset(twitch_name: str, display_name: str, source_part: str, crop: tuple[int, int, int, int], layout: str | int | None = None) -> None:
    presets = load_crop_presets()
    layout_label = normalize_layout(layout)
    presets[crop_key(twitch_name, source_part, layout_label)] = {
        "layout": layout_label,
        "twitch_name": twitch_name,
        "display_name": display_name,
        "source_part": source_part,
        "crop": {
            "left": int(crop[0]),
            "right": int(crop[1]),
            "top": int(crop[2]),
            "bottom": int(crop[3]),
        },
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_json(CROP_PRESETS_FILE, presets)
    append_log(f"Saved {layout_label} crop preset for {display_name or twitch_name} {source_part}.")


def append_log(message: str) -> None:
    ensure_state_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")
