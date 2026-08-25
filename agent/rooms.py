"""Shared room and signal contract for the smart-home agent.

VirtualHome currently exposes four concrete rooms:

- living_room
- bedroom
- kitchen
- bathroom

Legacy mock snapshots used bedroom1/bedroom2. They are normalized to bedroom so
older prompts and stored rules can still match the VirtualHome room model.
"""

from __future__ import annotations

from typing import Any

ROOMS = ("living_room", "bedroom", "kitchen", "bathroom")

ROOM_CN = {
    "living_room": "客厅",
    "bedroom": "卧室",
    "kitchen": "厨房",
    "bathroom": "卫生间",
}

ROOM_ALIASES = {
    "living_room": "living_room",
    "livingroom": "living_room",
    "living room": "living_room",
    "客厅": "living_room",
    "bedroom": "bedroom",
    "bedroom1": "bedroom",
    "bedroom_1": "bedroom",
    "bedroom2": "bedroom",
    "bedroom_2": "bedroom",
    "卧室": "bedroom",
    "卧室1": "bedroom",
    "卧室2": "bedroom",
    "kitchen": "kitchen",
    "厨房": "kitchen",
    "bathroom": "bathroom",
    "卫生间": "bathroom",
    "洗手间": "bathroom",
}

WHOLE_HOME_ALIASES = {"all", "all_rooms", "whole_home", "home", "全屋", "全部房间"}

ROOM_FIELDS = (
    "person_count",
    "cat_count",
    "dog_count",
    "pet_count",
    "unknown_person_count",
    "known_resident_count",
    "live_object_count",
    "has_person",
    "has_cat",
    "has_dog",
    "fall_like",
    "hazard_detected",
    "hazard_type",
    "health_event",
    "unknown_person",
)


def normalize_room(room: Any) -> str | None:
    """Return a canonical room name, or None for whole-home/no room signals."""
    if not isinstance(room, str):
        return None
    key = room.strip().lower().replace("-", "_")
    if key in WHOLE_HOME_ALIASES:
        return None
    return ROOM_ALIASES.get(key)


def empty_room_state() -> dict[str, Any]:
    return {
        "person_count": 0,
        "cat_count": 0,
        "dog_count": 0,
        "pet_count": 0,
        "unknown_person_count": 0,
        "known_resident_count": 0,
        "live_object_count": 0,
        "has_person": False,
        "has_cat": False,
        "has_dog": False,
        "fall_like": False,
        "hazard_detected": False,
        "hazard_type": "",
        "health_event": False,
        "unknown_person": False,
    }


def empty_rooms() -> dict[str, dict[str, Any]]:
    return {room: empty_room_state() for room in ROOMS}
