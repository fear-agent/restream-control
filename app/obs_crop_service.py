from __future__ import annotations

from typing import Any

import app_state

try:
    import obsws_python as obs
except Exception:
    obs = None

TARGETS_4P = [
    ("4P R1 Stream", "4P", "R1", "Stream"),
    ("4P R1 Tracker", "4P", "R1", "Tracker"),
    ("4P R1 Timer", "4P", "R1", "Timer"),
    ("4P R2 Stream", "4P", "R2", "Stream"),
    ("4P R2 Tracker", "4P", "R2", "Tracker"),
    ("4P R2 Timer", "4P", "R2", "Timer"),
    ("4P R3 Stream", "4P", "R3", "Stream"),
    ("4P R3 Tracker", "4P", "R3", "Tracker"),
    ("4P R3 Timer", "4P", "R3", "Timer"),
    ("4P R4 Stream", "4P", "R4", "Stream"),
    ("4P R4 Tracker", "4P", "R4", "Tracker"),
    ("4P R4 Timer", "4P", "R4", "Timer"),
]

TARGETS_2P = [
    ("2P R1 Stream", "2P", "R1", "Stream"),
    ("2P R1 Tracker", "2P", "R1", "Tracker"),
    ("2P R1 Timer", "2P", "R1", "Timer"),
    ("2P R2 Stream", "2P", "R2", "Stream"),
    ("2P R2 Tracker", "2P", "R2", "Tracker"),
    ("2P R2 Timer", "2P", "R2", "Timer"),
]

BASE_TARGETS = TARGETS_4P + TARGETS_2P
ALL_TARGETS = [t[0] for t in BASE_TARGETS]
KNOWN_GROUPS = ["4P R1", "4P R2", "4P R3", "4P R4", "2P R1", "2P R2"]
KNOWN_SCENES = ["4P Restream", "2P Restream"]
LAYOUT_DESIGN_FILE = app_state.STATE_DIR / "layout_designer.json"


def connect():
    if obs is None:
        raise RuntimeError("obsws-python is not installed.")
    obs_config = app_state.load_config().get("obs_websocket", {})
    return obs.ReqClient(
        host=obs_config.get("host", "localhost"),
        port=int(obs_config.get("port", 4455)),
        password=obs_config.get("password", ""),
        timeout=3,
    )


def designer_crop_targets() -> list[tuple[str, str, str, str]]:
    data = app_state.load_json(LAYOUT_DESIGN_FILE, {})
    if not isinstance(data, dict):
        return []
    default_layout = app_state.normalize_layout(data.get("layout"))
    regions = data.get("regions", [])
    if not isinstance(regions, list):
        return []
    targets: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for region in regions:
        if not isinstance(region, dict):
            continue
        region_type = str(region.get("type", ""))
        if region_type not in {"Facecam", "Camera"}:
            continue
        layout = app_state.normalize_layout(region.get("layout", default_layout))
        slot = str(region.get("slot", "")).strip().upper()
        if slot not in {"R1", "R2", "R3", "R4"}:
            continue
        if layout == "2P" and slot not in {"R1", "R2"}:
            continue
        source = str(region.get("source", "") or f"{layout} {slot} Facecam").strip()
        source = source.replace(" Camera", " Facecam")
        if not source or source in seen:
            continue
        seen.add(source)
        targets.append((source, layout, slot, "Facecam"))
    return targets


def all_crop_targets() -> list[tuple[str, str, str, str]]:
    targets = list(BASE_TARGETS)
    existing = {target[0] for target in targets}
    for target in designer_crop_targets():
        if target[0] not in existing:
            targets.append(target)
            existing.add(target[0])
    return targets


def all_target_names() -> list[str]:
    return [target[0] for target in all_crop_targets()]


def find_crop_targets(client: Any) -> dict[str, tuple[str, int]]:
    locations: dict[str, tuple[str, int]] = {}
    target_names = set(all_target_names())
    source_map = app_state.load_config().get("obs_source_map", {})
    if not isinstance(source_map, dict):
        source_map = {}
    actual_to_logical = {str(actual): str(logical) for logical, actual in source_map.items() if str(actual).strip()}

    def add_item(container_name, item):
        name = item.get("sourceName") if isinstance(item, dict) else getattr(item, "source_name", None)
        item_id = item.get("sceneItemId") if isinstance(item, dict) else getattr(item, "scene_item_id", None)
        if not name or item_id is None:
            return
        if name in target_names:
            locations[name] = (container_name, item_id)
        logical_name = actual_to_logical.get(name)
        if logical_name:
            locations[logical_name] = (container_name, item_id)

    groups = set(KNOWN_GROUPS)
    try:
        resp = client.get_group_list()
        for group in getattr(resp, "groups", []):
            groups.add(str(group))
    except Exception:
        pass

    scenes = set(KNOWN_SCENES)
    try:
        resp = client.get_scene_list()
        for scene in getattr(resp, "scenes", []):
            name = scene.get("sceneName") if isinstance(scene, dict) else getattr(scene, "scene_name", None)
            if name:
                scenes.add(str(name))
    except Exception:
        pass

    for group in groups:
        try:
            resp = client.get_group_scene_item_list(group)
            for item in getattr(resp, "scene_items", []):
                add_item(group, item)
        except Exception:
            pass

    for scene in scenes:
        try:
            resp = client.get_scene_item_list(scene)
            for item in getattr(resp, "scene_items", []):
                add_item(scene, item)
        except Exception:
            pass

    return locations


def crop_tuple_from_preset(preset: dict[str, Any]) -> tuple[int, int, int, int]:
    crop = preset.get("crop", {})
    return (int(crop["left"]), int(crop["right"]), int(crop["top"]), int(crop["bottom"]))


def set_crop(client: Any, locations: dict[str, tuple[str, int]], source_name: str, crop: tuple[int, int, int, int]) -> None:
    if source_name not in locations:
        raise RuntimeError(f"OBS source not found: {source_name}")
    container_name, item_id = locations[source_name]
    left, right, top, bottom = crop
    client.set_scene_item_transform(container_name, item_id, {
        "cropLeft": int(left),
        "cropRight": int(right),
        "cropTop": int(top),
        "cropBottom": int(bottom),
    })
