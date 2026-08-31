from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

IS_FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent
REPO_ROOT = APP_DIR if IS_FROZEN else APP_DIR.parent


def default_data_dir() -> Path:
    override = os.environ.get("RESTREAM_CONTROL_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "RestreamControl"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "RestreamControl"
    return Path.home() / ".local" / "share" / "RestreamControl"


DATA_DIR = default_data_dir()
STATE_DIR = DATA_DIR / "state"
CONFIG_FILE = DATA_DIR / "app_config.json"
RUNNERS_FILE = DATA_DIR / "runners.csv"
OBS_TEXT_DIR = DATA_DIR / "obs_text"
CROP_SCREENSHOT_DIR = DATA_DIR / "crop_screenshots"
SYNC_SCREENSHOT_DIR = DATA_DIR / "sync_screenshots"
OBS_ASSET_DIR = DATA_DIR / "obs_assets"
UPDATES_DIR = DATA_DIR / "updates"
UPDATE_DOWNLOAD_DIR = UPDATES_DIR / "downloads"
UPDATE_BACKUP_DIR = UPDATES_DIR / "backups"
UPDATE_HEALTH_DIR = UPDATES_DIR / "health"
LAST_SETUP_FILE = DATA_DIR / "race_setup_last.txt"
CROPPING_CONFIG_FILE = DATA_DIR / "cropping_tool_config.json"
MIGRATION_FILE = DATA_DIR / "storage_migration.json"
CURRENT_RACE_FILE = STATE_DIR / "current_race.json"
CROP_PRESETS_FILE = STATE_DIR / "crop_presets.json"
LOG_FILE = STATE_DIR / "restream_app.log"
CRASH_LOG_FILE = STATE_DIR / "crash.log"

DEFAULT_CONFIG: dict[str, Any] = {
    "obs_text_dir": str(OBS_TEXT_DIR),
    "screenshot_dir": str(CROP_SCREENSHOT_DIR),
    "runner_csv": str(RUNNERS_FILE),
    "quality": "720p60,720p,480p,360p,1080p60,1080p,best",
    "vlc_audio_device": "",
    "media_feed_port_base": 5001,
    "media_feed_quality": "Preferred",
    "media_feed_latency": "Stable",
    "playback_engine": "VLC Windows",
    "obs_websocket": {
        "host": "localhost",
        "port": 4455,
        "password": "",
    },
    "obs_source_map": {},
}

_INITIALIZED = False


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


def _copy_file(
    source: Path,
    destination: Path,
    migrated: list[str],
    replace_existing: bool = False,
) -> bool:
    if not source.is_file() or (destination.exists() and not replace_existing):
        return False
    try:
        if source.resolve() == destination.resolve():
            return False
    except OSError:
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    migrated.append(str(destination))
    return True


def _copy_folder_contents(
    source: Path,
    destination: Path,
    migrated: list[str],
    replace_existing: bool = False,
) -> None:
    if not source.is_dir():
        return
    for item in source.rglob("*"):
        if item.is_file():
            _copy_file(item, destination / item.relative_to(source), migrated, replace_existing)


def migrate_legacy_data(
    legacy_app_dir: Path,
    legacy_repo_root: Path,
    data_dir: Path,
    seed_runners_file: Path | None = None,
    replace_existing: bool = False,
) -> list[str]:
    """Copy user-owned files from a portable install into stable app data."""
    legacy_app_dir = Path(legacy_app_dir)
    legacy_repo_root = Path(legacy_repo_root)
    data_dir = Path(data_dir)
    state_dir = data_dir / "state"
    config_file = data_dir / "app_config.json"
    runners_file = data_dir / "runners.csv"
    migrated: list[str] = []

    data_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    legacy_config_file = legacy_app_dir / "app_config.json"
    legacy_config = load_json(legacy_config_file, {})
    if not isinstance(legacy_config, dict):
        legacy_config = {}

    runner_candidates: list[Path] = []
    configured_runner = str(legacy_config.get("runner_csv", "")).strip()
    if configured_runner:
        runner_candidates.append(Path(configured_runner).expanduser())
    runner_candidates.extend(
        [
            legacy_app_dir / "runners.csv",
            legacy_repo_root / "data" / "runners.csv",
            legacy_app_dir / "data" / "runners.csv",
        ]
    )
    for candidate in runner_candidates:
        if _copy_file(candidate, runners_file, migrated, replace_existing):
            break
    if not runners_file.exists() and seed_runners_file is not None:
        _copy_file(Path(seed_runners_file), runners_file, migrated)

    for name in [
        "current_race.json",
        "crop_presets.json",
        "layout_designer.json",
        "media_scene_items.json",
        "runners.local.backup.csv",
    ]:
        _copy_file(legacy_app_dir / "state" / name, state_dir / name, migrated, replace_existing)
    _copy_folder_contents(
        legacy_app_dir / "state" / "backups",
        state_dir / "backups",
        migrated,
        replace_existing,
    )

    for source, destination in [
        (legacy_app_dir / "race_setup_last.txt", data_dir / "race_setup_last.txt"),
        (legacy_app_dir / "cropping_tool_config.json", data_dir / "cropping_tool_config.json"),
    ]:
        _copy_file(source, destination, migrated, replace_existing)

    for source, destination in [
        (legacy_app_dir / "obs_text", data_dir / "obs_text"),
        (legacy_app_dir / "crop_screenshots", data_dir / "crop_screenshots"),
        (legacy_app_dir / "sync_screenshots", data_dir / "sync_screenshots"),
    ]:
        _copy_folder_contents(source, destination, migrated, replace_existing)

    if (replace_existing or not config_file.exists()) and legacy_config:
        config = json.loads(json.dumps(legacy_config))
        replacements = {
            "runner_csv": data_dir / "runners.csv",
            "obs_text_dir": data_dir / "obs_text",
            "screenshot_dir": data_dir / "crop_screenshots",
        }
        for key, replacement in replacements.items():
            config[key] = str(replacement)
        save_json(config_file, config)
        migrated.append(str(config_file))

    return migrated


def initialize_data_storage() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    for folder in [
        DATA_DIR,
        STATE_DIR,
        OBS_TEXT_DIR,
        CROP_SCREENSHOT_DIR,
        SYNC_SCREENSHOT_DIR,
        OBS_ASSET_DIR,
        UPDATE_DOWNLOAD_DIR,
        UPDATE_BACKUP_DIR,
        UPDATE_HEALTH_DIR,
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    migrated: list[str] = []
    if not MIGRATION_FILE.exists():
        migrated = migrate_legacy_data(
            APP_DIR,
            REPO_ROOT,
            DATA_DIR,
            bundled_example_runners_file(),
        )
        save_json(
            MIGRATION_FILE,
            {
                "format": 1,
                "migrated_at": datetime.now().isoformat(timespec="seconds"),
                "legacy_app_dir": str(APP_DIR),
                "migrated_files": migrated,
            },
        )
    elif not RUNNERS_FILE.exists():
        _copy_file(bundled_example_runners_file(), RUNNERS_FILE, migrated)

    _copy_folder_contents(
        REPO_ROOT / "obs-template" / "assets",
        OBS_ASSET_DIR,
        [],
        replace_existing=True,
    )

    _INITIALIZED = True


def bundled_example_runners_file() -> Path:
    packaged_seed = REPO_ROOT / "data" / "example_runners.csv"
    return packaged_seed if packaged_seed.exists() else REPO_ROOT / "data" / "runners.csv"


def ensure_state_dir() -> None:
    initialize_data_storage()
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    initialize_data_storage()
    data = load_json(CONFIG_FILE, {})
    config = DEFAULT_CONFIG.copy()
    config.update(data if isinstance(data, dict) else {})
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
