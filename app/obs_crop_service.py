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
KNOWN_SCENES = ["4P Restream", "2P Restream", "4P Media Restream", "2P Media Restream"]
LAYOUT_DESIGN_FILE = app_state.STATE_DIR / "layout_designer.json"
MEDIA_ITEM_MAP_FILE = app_state.STATE_DIR / "media_scene_items.json"


def load_media_item_map() -> dict[str, dict[str, Any]]:
    data = app_state.load_json(MEDIA_ITEM_MAP_FILE, {})
    items = data.get("items", {}) if isinstance(data, dict) else {}
    return items if isinstance(items, dict) else {}


def save_media_item_location(
    logical_name: str,
    scene_name: str,
    scene_item_id: int,
    source_name: str,
) -> None:
    items = load_media_item_map()
    items[str(logical_name)] = {
        "scene_name": str(scene_name),
        "scene_item_id": int(scene_item_id),
        "source_name": str(source_name),
    }
    app_state.save_json(MEDIA_ITEM_MAP_FILE, {"version": 2, "items": items})


def remove_media_item_locations(layout: str | int, logical_names: set[str] | None = None) -> None:
    normalized = app_state.normalize_layout(layout)
    items = load_media_item_map()
    retained: dict[str, dict[str, Any]] = {}
    for logical_name, details in items.items():
        remove = str(logical_name).startswith(f"{normalized} R")
        if logical_names is not None:
            remove = logical_name in logical_names
        if not remove:
            retained[logical_name] = details
    app_state.save_json(MEDIA_ITEM_MAP_FILE, {"version": 2, "items": retained})


def media_item_location(logical_name: str) -> tuple[str, int, str] | None:
    details = load_media_item_map().get(str(logical_name))
    if not isinstance(details, dict):
        return None
    try:
        return (
            str(details["scene_name"]),
            int(details["scene_item_id"]),
            str(details.get("source_name", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


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

    # Layout designer v2 stores separate 2P and 4P definitions under
    # ``layouts``.  Keep accepting the original single-layout file as well,
    # since a user's local state may predate that change.
    layouts = data.get("layouts")
    if isinstance(layouts, dict):
        layout_data = [
            (app_state.normalize_layout(layout), value)
            for layout, value in layouts.items()
            if isinstance(value, dict)
        ]
    else:
        layout_data = [(app_state.normalize_layout(data.get("layout")), data)]

    targets: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for stored_layout, layout_definition in layout_data:
        default_layout = app_state.normalize_layout(layout_definition.get("layout", stored_layout))
        regions = layout_definition.get("regions", [])
        if not isinstance(regions, list):
            continue
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
    # The experimental no-VLC path uses independent OBS Media Sources. They
    # need to be discoverable by the same crop service as the VLC sources.
    for source, layout, slot, part in BASE_TARGETS:
        targets.append((f"{layout} {slot} Media {part}", layout, slot, part))
    for layout, slots in (("2P", range(1, 3)), ("4P", range(1, 5))):
        for slot in slots:
            targets.append((f"{layout} R{slot} Media Facecam", layout, f"R{slot}", "Facecam"))
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
    valid_items: set[tuple[str, int]] = set()
    target_names = set(all_target_names())
    media_items = load_media_item_map()
    source_map = app_state.load_config().get("obs_source_map", {})
    if not isinstance(source_map, dict):
        source_map = {}
    actual_to_logical = {str(actual): str(logical) for logical, actual in source_map.items() if str(actual).strip()}

    def add_item(container_name, item):
        name = item.get("sourceName") if isinstance(item, dict) else getattr(item, "source_name", None)
        item_id = item.get("sceneItemId") if isinstance(item, dict) else getattr(item, "scene_item_id", None)
        if not name or item_id is None:
            return
        valid_items.add((str(container_name), int(item_id)))
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
    for details in media_items.values():
        if isinstance(details, dict) and details.get("scene_name"):
            scenes.add(str(details["scene_name"]))
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

    # Direct OBS v2 uses one input per runner and several references to it in
    # the scene. Their source names are identical, so the persisted logical
    # name -> scene-item ID map is what distinguishes Game/Tracker/Timer/etc.
    for logical_name, details in media_items.items():
        if not isinstance(details, dict):
            continue
        try:
            location = (str(details["scene_name"]), int(details["scene_item_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if location in valid_items:
            locations[str(logical_name)] = location

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
