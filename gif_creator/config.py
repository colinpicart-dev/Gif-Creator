import json
import os

from gif_creator.region import is_large_enough
from gif_creator.shortcuts import ACTIONS, DEFAULT_SHORTCUTS, is_valid_accel, normalize_accel

DEFAULTS = {
    "fps": 30,
    "max_duration_seconds": 4,
    "include_cursor": False,
    "show_window_during_capture": False,
    "show_frame_during_capture": False,
}


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    directory = os.path.join(base, "gif-creator")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, "config.json")


def _clamp(value, low, high, fallback):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def _shortcuts_from(raw):
    shortcuts = dict(DEFAULT_SHORTCUTS)
    if isinstance(raw, dict):
        for action in ACTIONS:
            value = raw.get(action)
            if isinstance(value, str) and is_valid_accel(value):
                shortcuts[action] = normalize_accel(value)
    seen = set()
    for action in ACTIONS:
        normalized = normalize_accel(shortcuts[action])
        if not normalized or normalized in seen:
            shortcuts[action] = DEFAULT_SHORTCUTS[action]
            normalized = normalize_accel(shortcuts[action])
        seen.add(normalized)
    if len({normalize_accel(shortcuts[action]) for action in ACTIONS}) < len(ACTIONS):
        return dict(DEFAULT_SHORTCUTS)
    return shortcuts


def _region_from(raw):
    if not isinstance(raw, dict):
        return None
    try:
        region = {
            "x": int(raw["x"]),
            "y": int(raw["y"]),
            "width": int(raw["width"]),
            "height": int(raw["height"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if not is_large_enough(region["width"], region["height"]):
        return None
    return region


def load_config():
    path = config_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "fps": _clamp(data.get("fps"), 1, 30, DEFAULTS["fps"]),
        "max_duration_seconds": _clamp(
            data.get("max_duration_seconds"),
            1,
            180,
            DEFAULTS["max_duration_seconds"],
        ),
        "include_cursor": bool(data.get("include_cursor", DEFAULTS["include_cursor"])),
        "show_window_during_capture": bool(
            data.get("show_window_during_capture", DEFAULTS["show_window_during_capture"])
        ),
        "show_frame_during_capture": bool(
            data.get("show_frame_during_capture", DEFAULTS["show_frame_during_capture"])
        ),
        "region": _region_from(data.get("region")),
        "shortcuts": _shortcuts_from(data.get("shortcuts")),
    }


def save_config(settings):
    shortcuts = _shortcuts_from(settings.get("shortcuts"))
    payload = {
        "fps": _clamp(settings.get("fps"), 1, 30, DEFAULTS["fps"]),
        "max_duration_seconds": _clamp(
            settings.get("max_duration_seconds"),
            1,
            180,
            DEFAULTS["max_duration_seconds"],
        ),
        "include_cursor": bool(settings.get("include_cursor", DEFAULTS["include_cursor"])),
        "show_window_during_capture": bool(
            settings.get("show_window_during_capture", DEFAULTS["show_window_during_capture"])
        ),
        "show_frame_during_capture": bool(
            settings.get("show_frame_during_capture", DEFAULTS["show_frame_during_capture"])
        ),
        "region": _region_from(settings.get("region")),
        "shortcuts": shortcuts,
    }
    path = config_path()
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary, path)
    settings["fps"] = payload["fps"]
    settings["max_duration_seconds"] = payload["max_duration_seconds"]
    settings["include_cursor"] = payload["include_cursor"]
    settings["show_window_during_capture"] = payload["show_window_during_capture"]
    settings["show_frame_during_capture"] = payload["show_frame_during_capture"]
    settings["region"] = payload["region"]
    settings["shortcuts"] = payload["shortcuts"]
