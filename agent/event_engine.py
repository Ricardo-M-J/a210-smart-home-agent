"""Event engine for monitor rules over the current home-state snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memory import Memory
from rooms import ROOM_CN, ROOM_FIELDS, normalize_room


def is_night(timestamp_ms: int) -> bool:
    """Return whether the timestamp is in the local night window, 22:00-06:00."""
    try:
        hour = datetime.fromtimestamp(timestamp_ms / 1000).hour
    except (OSError, ValueError, OverflowError):
        return False
    return hour >= 22 or hour < 6


def _room_matches(room_state: dict[str, Any], when: dict[str, Any]) -> bool:
    for field in ROOM_FIELDS:
        if field in when and room_state.get(field) != when[field]:
            return False
    return True


def check(state: dict, when: dict) -> list[str]:
    """Return canonical room names that match a monitor rule."""
    if not state or "error" in state:
        return []

    if "is_night" in when and is_night(state.get("timestamp_ms", 0)) != when["is_night"]:
        return []

    rooms = state.get("rooms", {})
    if not isinstance(rooms, dict):
        return []

    requested_room = normalize_room(when.get("room")) if when.get("room") else None
    candidates = [requested_room] if requested_room else list(rooms.keys())

    matched: list[str] = []
    for name in candidates:
        canonical = normalize_room(name) or name
        room_state = rooms.get(canonical)
        if isinstance(room_state, dict) and _room_matches(room_state, when):
            matched.append(canonical)
    return matched


class EventEngine:
    def __init__(self):
        self._active: set[str] = set()

    def detect(self, state: dict) -> list[dict]:
        if "error" in state:
            return []

        events: list[dict] = []
        current_hits: set[str] = set()

        for rule in Memory().list_rules(active_only=True):
            when = rule.get("when") or {}
            requires_mode = rule.get("requires_mode")
            if requires_mode and Memory().get_home_mode() != requires_mode:
                continue

            for room in check(state, when):
                key = f"{rule['id']}:{room}"
                current_hits.add(key)
                if key in self._active:
                    continue
                self._active.add(key)
                description = rule.get("description") or "未命名"
                events.append(
                    {
                        "rule_id": rule["id"],
                        "room": room,
                        "rule_description": description,
                        "summary": f"{ROOM_CN.get(room, room)}：命中规则「{description}」",
                    }
                )

        self._active = current_hits
        return events
