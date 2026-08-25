"""Control real VirtualHome Unity scene devices through the Python API.

This module attaches to an already running VirtualHome.exe HTTP API. It does
not launch or reset the simulator. The main use is Agent -> VirtualHome device
control: change room light states in the actual Unity environment graph.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_REPO = REPO_ROOT / "virtualhome"
sys.path.insert(0, str(PACKAGE_REPO))

from virtualhome.simulation.unity_simulator import comm_unity


ROOM_TO_VIRTUALHOME = {
    "living_room": "livingroom",
    "livingroom": "livingroom",
    "bedroom": "bedroom",
    "kitchen": "kitchen",
    "bathroom": "bathroom",
}

ROOM_LABELS = {
    "living_room": "客厅",
    "bedroom": "卧室",
    "kitchen": "厨房",
    "bathroom": "卫生间",
}

LIGHT_HINTS = ("lightswitch", "lamp", "light")
MEDIA_PRIORITY = ("speaker", "radio", "stereo", "tv", "computer")
SWITCH_STATES = {"ON", "OFF"}


class UnityDeviceControlError(RuntimeError):
    pass


class UnityDeviceController:
    def __init__(self, port: str = "8080", timeout_wait: int = 5) -> None:
        self.port = str(port)
        self.timeout_wait = int(timeout_wait)
        self.comm = comm_unity.UnityCommunication(
            port=self.port,
            logging=False,
            timeout_wait=self.timeout_wait,
        )

    def check(self) -> None:
        if not self.comm.check_connection():
            raise UnityDeviceControlError(f"VirtualHome API on port {self.port} did not respond")

    def control(self, room: str, device: str, command: str, value: str = "") -> dict[str, Any]:
        self.check()
        room_keys = self._target_rooms(room)
        if not room_keys:
            raise UnityDeviceControlError(f"unknown room: {room}")

        device = str(device or "").strip().lower()
        command = str(command or "").strip().lower()
        if device == "light":
            desired_state = self._light_command_to_state(command)
        elif device == "speaker":
            desired_state = self._speaker_command_to_state(command)
        else:
            raise UnityDeviceControlError(f"unsupported device: {device}")

        ok, graph = self.comm.environment_graph()
        if not ok:
            raise UnityDeviceControlError("environment_graph failed")

        broad_graph = copy.deepcopy(graph)
        broad_targets = self._apply_to_graph(broad_graph, room_keys, device, desired_state, strict=False)
        if not broad_targets:
            raise UnityDeviceControlError(f"no {device} targets found for room={room}")

        success, message = self._expand_scene(broad_graph)
        targets = broad_targets
        used_strict_retry = False

        if not success:
            strict_graph = copy.deepcopy(graph)
            strict_targets = self._apply_to_graph(strict_graph, room_keys, device, desired_state, strict=True)
            if not strict_targets:
                raise UnityDeviceControlError(f"expand_scene failed and no strict targets are available: {message}")
            success, message = self._expand_scene(strict_graph)
            targets = strict_targets
            used_strict_retry = True

        if not success:
            raise UnityDeviceControlError(f"expand_scene failed: {message}")

        verified = self._verify_targets(targets, desired_state)
        return {
            "status": "ok",
            "port": self.port,
            "room": room,
            "rooms": room_keys,
            "device": device,
            "command": command,
            "state": desired_state,
            "targets": targets,
            "verified": verified,
            "method": "expand_scene",
            "strict_retry": used_strict_retry,
            "message": message,
            "value": value,
        }

    def _expand_scene(self, graph: dict[str, Any]) -> tuple[bool, Any]:
        try:
            return self.comm.expand_scene(
                graph,
                randomize=False,
                ignore_placing_obstacles=True,
                transfer_transform=True,
            )
        except Exception as exc:
            return False, str(exc)

    def _verify_targets(self, targets: list[dict[str, Any]], desired_state: str) -> dict[str, Any]:
        ok, graph = self.comm.environment_graph()
        if not ok:
            return {"ok": False, "detail": "environment_graph verification failed"}
        node_by_id = {node.get("id"): node for node in graph.get("nodes", [])}
        rows = []
        checked = 0
        all_match = True
        for target in targets:
            node = node_by_id.get(target.get("id"))
            states = list(node.get("states", [])) if isinstance(node, dict) else []
            verifiable = bool(target.get("verifiable"))
            matched = desired_state in states if verifiable else None
            if verifiable:
                checked += 1
                all_match = all_match and bool(matched)
            rows.append(
                {
                    "id": target.get("id"),
                    "class_name": target.get("class_name"),
                    "states": states,
                    "verifiable": verifiable,
                    "matched": matched,
                }
            )
        return {"ok": checked > 0 and all_match, "checked": checked, "targets": rows}

    @staticmethod
    def _target_rooms(room: str) -> list[str]:
        raw = str(room or "").strip().lower().replace("-", "_")
        if raw in {"all", "all_rooms", "whole_home", "home", "全部", "全屋", "所有房间"}:
            return ["living_room", "bedroom", "kitchen", "bathroom"]
        canonical = {
            "living_room": "living_room",
            "livingroom": "living_room",
            "客厅": "living_room",
            "bedroom": "bedroom",
            "卧室": "bedroom",
            "kitchen": "kitchen",
            "厨房": "kitchen",
            "bathroom": "bathroom",
            "卫生间": "bathroom",
            "洗手间": "bathroom",
        }.get(raw)
        return [canonical] if canonical else []

    @staticmethod
    def _light_command_to_state(command: str) -> str:
        if command in {"on", "open", "turn_on", "play"}:
            return "ON"
        if command in {"off", "close", "turn_off", "stop", "pause"}:
            return "OFF"
        raise UnityDeviceControlError(f"unsupported light command: {command}")

    @staticmethod
    def _speaker_command_to_state(command: str) -> str:
        if command in {"play", "on", "open", "turn_on"}:
            return "ON"
        if command in {"stop", "pause", "off", "close", "turn_off"}:
            return "OFF"
        raise UnityDeviceControlError(f"unsupported speaker command: {command}")

    def _apply_to_graph(
        self,
        graph: dict[str, Any],
        room_keys: list[str],
        device: str,
        desired_state: str,
        strict: bool,
    ) -> list[dict[str, Any]]:
        room_ids = self._room_ids(graph)
        node_room = self._node_room_map(graph, room_ids)
        targets: list[dict[str, Any]] = []

        for room_key in room_keys:
            virtualhome_room = ROOM_TO_VIRTUALHOME[room_key]
            room_media_candidates: list[tuple[int, dict[str, Any]]] = []
            for node in graph.get("nodes", []):
                if node_room.get(node.get("id")) != virtualhome_room:
                    continue
                if device == "light" and not self._is_light_target(node, strict=strict):
                    continue
                if device == "speaker":
                    score = self._media_score(node)
                    if score is None:
                        continue
                    room_media_candidates.append((score, node))
                    continue
                verifiable = self._has_verifiable_switch_state(node)
                self._set_switch_state(node, desired_state)
                targets.append(
                    {
                        "id": node.get("id"),
                        "class_name": node.get("class_name"),
                        "room": room_key,
                        "room_label": ROOM_LABELS.get(room_key, room_key),
                        "states": list(node.get("states", [])),
                        "verifiable": verifiable,
                    }
                )

            if device == "speaker" and room_media_candidates:
                _score, node = sorted(room_media_candidates, key=lambda item: item[0])[0]
                verifiable = self._has_verifiable_switch_state(node)
                self._set_switch_state(node, desired_state)
                targets.append(
                    {
                        "id": node.get("id"),
                        "class_name": node.get("class_name"),
                        "room": room_key,
                        "room_label": ROOM_LABELS.get(room_key, room_key),
                        "states": list(node.get("states", [])),
                        "verifiable": verifiable,
                    }
                )

        return targets

    @staticmethod
    def _room_ids(graph: dict[str, Any]) -> dict[int, str]:
        rooms: dict[int, str] = {}
        for node in graph.get("nodes", []):
            if node.get("category") == "Rooms":
                rooms[int(node["id"])] = str(node.get("class_name", "")).lower()
        return rooms

    @staticmethod
    def _node_room_map(graph: dict[str, Any], room_ids: dict[int, str]) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for edge in graph.get("edges", []):
            if str(edge.get("relation_type", "")).upper() != "INSIDE":
                continue
            to_id = edge.get("to_id")
            from_id = edge.get("from_id")
            if to_id in room_ids and from_id is not None:
                mapping[int(from_id)] = room_ids[int(to_id)]
        return mapping

    @staticmethod
    def _is_light_target(node: dict[str, Any], strict: bool) -> bool:
        class_name = str(node.get("class_name", "")).lower()
        properties = {str(item).upper() for item in node.get("properties", [])}
        states = {str(item).upper() for item in node.get("states", [])}
        if not any(hint in class_name for hint in LIGHT_HINTS):
            return False
        if not strict:
            return True
        return "HAS_SWITCH" in properties or bool(states & SWITCH_STATES)

    @staticmethod
    def _is_media_target(node: dict[str, Any]) -> bool:
        return UnityDeviceController._media_score(node) is not None

    @staticmethod
    def _media_score(node: dict[str, Any]) -> int | None:
        class_name = str(node.get("class_name", "")).lower()
        properties = {str(item).upper() for item in node.get("properties", [])}
        if "HAS_SWITCH" not in properties:
            return None
        for index, hint in enumerate(MEDIA_PRIORITY):
            if hint in class_name:
                return index
        return None

    @staticmethod
    def _set_switch_state(node: dict[str, Any], desired_state: str) -> None:
        states = [str(item).upper() for item in node.get("states", []) if str(item).upper() not in SWITCH_STATES]
        states.append(desired_state)
        node["states"] = states

    @staticmethod
    def _has_verifiable_switch_state(node: dict[str, Any]) -> bool:
        properties = {str(item).upper() for item in node.get("properties", [])}
        states = {str(item).upper() for item in node.get("states", [])}
        return "HAS_SWITCH" in properties or bool(states & SWITCH_STATES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control devices in a running VirtualHome.exe through Python API")
    parser.add_argument("--port", default="8080", help="VirtualHome HTTP API port")
    parser.add_argument("--timeout", type=int, default=5, help="HTTP timeout in seconds")
    parser.add_argument("--room", required=True, help="living_room/bedroom/kitchen/bathroom/all_rooms")
    parser.add_argument("--device", required=True, choices=["light", "speaker"])
    parser.add_argument("--command", required=True, help="light: on/off; speaker: play/stop/pause")
    parser.add_argument("--value", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        controller = UnityDeviceController(port=args.port, timeout_wait=args.timeout)
        result = controller.control(args.room, args.device, args.command, args.value)
    except Exception as exc:
        result = {
            "status": "error",
            "port": args.port,
            "room": args.room,
            "device": args.device,
            "command": args.command,
            "detail": str(exc),
        }
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
