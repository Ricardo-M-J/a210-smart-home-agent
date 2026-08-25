"""Mock home-state snapshots for local development."""

from __future__ import annotations

import json
from pathlib import Path

from rooms import ROOMS, empty_rooms

_MOCK_DIR = Path(__file__).resolve().parent


def _rooms(**overrides) -> dict:
    base = empty_rooms()
    for room, patch in overrides.items():
        if room in base:
            base[room].update(patch)
    return base


SCENARIOS = {
    "day_normal": {
        "timestamp_ms": 1755670800000,
        "rooms": _rooms(living_room={"has_person": True}),
    },
    "pet_in_kitchen": {
        "timestamp_ms": 1755670800000,
        "rooms": _rooms(kitchen={"has_cat": True}),
    },
    "fall_in_bedroom": {
        "timestamp_ms": 1755702000000,
        "rooms": _rooms(bedroom={"has_person": True, "fall_like": True}),
    },
    "night_empty": {
        "timestamp_ms": 1755702000000,
        "rooms": _rooms(),
    },
    "night_person_enter": {
        "timestamp_ms": 1755702000000,
        "rooms": _rooms(living_room={"has_person": True}),
    },
}

DEFAULT_SCENE = "pet_in_kitchen"


def load_scene(name: str = DEFAULT_SCENE) -> dict:
    return json.loads(json.dumps(SCENARIOS[name]))


def write_scene(name: str = DEFAULT_SCENE, path: Path | None = None) -> Path:
    import config

    target = Path(path) if path else Path(config.HOME_STATE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(load_scene(name), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target
