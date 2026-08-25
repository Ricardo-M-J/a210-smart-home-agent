"""VirtualHome backend adapter for the A210 smart-home agent.

The adapter supports two data paths:

1. Sample mode: read the exported JSONL files under
   VIRTUAL_HOME/outputs/showcase_panel/interface_samples.
2. Live bridge mode: receive frame packets through /api/virtualhome/frame and
   map each packet to the agent's current home-state contract immediately.
"""

from __future__ import annotations

import copy
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import config
from rooms import ROOM_CN, ROOMS, empty_rooms, normalize_room

DEFAULT_SCENE_PRIORITY = ("kitchen_pet", "bedroom_person", "away_mode_stranger", "fire_smoke")
LIGHT_DEFAULTS = {f"{room}_ceiling_light": "on" for room in ROOMS}
MUSIC_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
WHOLE_HOME_SPEAKER = "whole_home_speaker"
HEALTH_RELIEF_TRACK = "伊藤サチコ - いつも何度でも"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False) + "\n")


def _last_timeline_value(result: dict[str, Any], key: str) -> Any:
    timeline = result.get("timeline")
    if not isinstance(timeline, list):
        return None
    for item in reversed(timeline):
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def _positive_count(value: Any) -> bool | None:
    count = _count_or_none(value)
    if count is None:
        return None
    return count > 0


def _count_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count_from_detections(result: dict[str, Any], labels: set[str]) -> int | None:
    detections = result.get("detections") or result.get("objects")
    if not isinstance(detections, list):
        return None

    count = 0
    for item in detections:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("class") or item.get("class_name") or "").lower()
        if label in labels:
            count += 1
    return count


COUNT_SIGNAL_FIELDS = (
    "person_count",
    "cat_count",
    "dog_count",
    "pet_count",
    "unknown_person_count",
    "known_resident_count",
    "live_object_count",
)
BOOL_SIGNAL_FIELDS = (
    "has_person",
    "has_cat",
    "has_dog",
    "fall_like",
    "hazard_detected",
    "health_event",
    "health_recovered",
    "unknown_person",
)
HEALTH_SIGNAL_FIELDS = ("heart_rate", "anxiety_score", "health_state")
CAMERA_RESULT_KEYS = ("camera_results", "room_camera_results", "yolo_camera_results")


def _room_from_stream_id(stream_id: Any) -> str | None:
    text = str(stream_id or "").strip().lower().replace("-", "_")
    if not text:
        return None
    for suffix in ("_camera", "_cam", "_stream"):
        if suffix in text:
            text = text.split(suffix, 1)[0]
            break
    return normalize_room(text)


def _merge_camera_result(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result") or item.get("external_result") or item.get("vision_result")
    merged = copy.deepcopy(result) if isinstance(result, dict) else {}
    for key, value in item.items():
        if key not in {"result", "external_result", "vision_result"}:
            merged.setdefault(key, value)
    return merged


def _iter_camera_results(result: dict[str, Any]):
    for key in CAMERA_RESULT_KEYS:
        rows = result.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                yield _merge_camera_result(item)


def _iter_room_count_results(result: dict[str, Any]):
    room_counts = result.get("room_person_counts")
    if not isinstance(room_counts, dict):
        return
    for room_key, count in room_counts.items():
        room = normalize_room(room_key)
        if room:
            yield {
                "schema": "external.vision_result.v1",
                "source": result.get("source") or "room_person_counts",
                "room": room,
                "person_count": count,
            }


def _iter_room_results(result: dict[str, Any]):
    rows = result.get("room_results")
    if isinstance(rows, dict):
        for room_key, value in rows.items():
            room = normalize_room(room_key)
            if not room:
                continue
            if isinstance(value, dict):
                item = copy.deepcopy(value)
                item.setdefault("room", room)
            else:
                item = {"room": room, "person_count": value}
            item.setdefault("schema", "external.vision_result.v1")
            item.setdefault("source", result.get("source") or "room_results")
            yield item
    elif isinstance(rows, list):
        for value in rows:
            if isinstance(value, dict):
                yield value


def _merge_room_signals(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for field in COUNT_SIGNAL_FIELDS:
        target[field] = max(_count_or_none(target.get(field)) or 0, _count_or_none(incoming.get(field)) or 0)

    for field in BOOL_SIGNAL_FIELDS:
        target[field] = bool(target.get(field) or incoming.get(field))

    if incoming.get("hazard_type"):
        target["hazard_type"] = incoming.get("hazard_type")
    for field in HEALTH_SIGNAL_FIELDS:
        value = incoming.get(field)
        if value not in (None, ""):
            target[field] = value

    target["has_person"] = target["has_person"] or target["person_count"] > 0
    target["has_cat"] = target["has_cat"] or target["cat_count"] > 0
    target["has_dog"] = target["has_dog"] or target["dog_count"] > 0
    target["pet_count"] = max(target["pet_count"], target["cat_count"] + target["dog_count"])
    target["live_object_count"] = max(target["live_object_count"], target["person_count"] + target["pet_count"])


class VirtualHomeAdapter:
    def __init__(
        self,
        root_dir: str | Path | None = None,
        frame_stream_file: str | Path | None = None,
        external_result_file: str | Path | None = None,
        feedback_sample_file: str | Path | None = None,
        feedback_output_file: str | Path | None = None,
    ) -> None:
        self.root_dir = Path(root_dir or config.VIRTUAL_HOME_DIR)
        self.frame_stream_file = Path(frame_stream_file or config.VIRTUAL_HOME_FRAME_STREAM_FILE)
        self.external_result_file = Path(external_result_file or config.VIRTUAL_HOME_EXTERNAL_RESULT_FILE)
        self.feedback_sample_file = Path(feedback_sample_file or config.VIRTUAL_HOME_FEEDBACK_SAMPLE_FILE)
        self.feedback_output_file = Path(feedback_output_file or config.VIRTUAL_HOME_FEEDBACK_FILE)
        self.bridge_dir = self.root_dir / "outputs" / "agent_bridge"
        self.current_packet_file = self.bridge_dir / "current_virtualhome_packet.json"
        self.device_state_file = self.bridge_dir / "simulated_device_state.json"
        self.music_dir = Path(config.VIRTUAL_HOME_MUSIC_DIR)

    @classmethod
    def from_config(cls) -> "VirtualHomeAdapter":
        return cls()

    def list_scenes(self) -> list[str]:
        return sorted(self._scene_records().keys())

    def current_scene(self) -> str:
        from memory import Memory

        scenes = self.list_scenes()
        if not scenes:
            return config.VIRTUAL_HOME_SCENE or "virtualhome_empty"

        stored = Memory().get_setting("virtualhome_scene", "")
        if stored in scenes:
            return stored

        configured = config.VIRTUAL_HOME_SCENE
        if configured in scenes:
            return configured

        for preferred in DEFAULT_SCENE_PRIORITY:
            if preferred in scenes:
                return preferred
        return scenes[0]

    def set_scene(self, scene: str) -> bool:
        if scene not in self.list_scenes():
            return False
        from memory import Memory

        Memory().set_setting("virtualhome_scene", scene)
        return True

    def latest_frame(self) -> dict[str, Any]:
        scene = self.current_scene()
        record = self._scene_records().get(scene, {})
        frame = record.get("frame") or {}
        image_path = self._frame_image_path(frame)
        return {
            "status": "ok" if frame else "error",
            "backend": "virtualhome",
            "scene": scene,
            "frame_id": f"virtualhome:{scene}:{frame.get('frame_index', 'latest')}",
            "stream_id": frame.get("stream_id"),
            "room": frame.get("room"),
            "image_path": str(image_path) if image_path else "",
            "image_exists": bool(image_path and image_path.exists()),
            "frame": frame,
            "external_result": record.get("external_result") or {},
            "scene_feedback": record.get("feedback_sample") or {},
            "live": bool(record.get("live")),
            "note": "VirtualHome virtual camera frame",
        }

    def capture(self) -> dict[str, Any]:
        result = self.latest_frame()
        if result.get("status") == "ok":
            result["captured_at_ms"] = int(time.time() * 1000)
        return result

    def infer(self) -> dict[str, Any]:
        state = self.home_state()
        scene = state.get("virtualhome", {}).get("scene", self.current_scene())
        record = self._scene_records().get(scene, {})
        return {
            "status": "ok",
            "backend": "virtualhome",
            "timestamp_ms": state.get("timestamp_ms"),
            "rooms": state.get("rooms", {}),
            "scene": scene,
            "frame": record.get("frame") or {},
            "external_result": record.get("external_result") or {},
            "scene_feedback": record.get("feedback_sample") or {},
            "live": bool(record.get("live")),
            "note": "VirtualHome frame stream is mapped to the A210 home-state contract.",
        }

    def home_state(self, record_override: dict[str, Any] | None = None) -> dict[str, Any]:
        scene = self.current_scene()
        record = record_override or self._scene_records().get(scene, {})
        frame = record.get("frame") or {}
        external = record.get("external_result") or {}
        feedback = record.get("feedback_sample") or {}
        scene = str(frame.get("scene") or external.get("scene") or feedback.get("scene") or scene)

        home_mode = self._home_mode()
        rooms = self._rooms_from_external_result(scene, external, frame, home_mode)

        timestamp_ms = int(time.time() * 1000)
        return {
            "timestamp_ms": timestamp_ms,
            "rooms": rooms,
            "virtualhome": {
                "scene": scene,
                "room_model": list(ROOMS),
                "frame_stream_file": str(self.frame_stream_file),
                "external_result_file": str(self.external_result_file),
                "feedback_output_file": str(self.feedback_output_file),
                "frame": frame,
                "external_result": external,
                "scene_feedback": feedback,
                "live": bool(record.get("live")),
                "home_mode": home_mode,
                "device_state": self.device_state(),
            },
        }

    def _rooms_from_external_result(
        self,
        scene: str,
        external: dict[str, Any],
        frame: dict[str, Any],
        home_mode: str,
    ) -> dict[str, dict[str, Any]]:
        rooms = empty_rooms()
        used_room_specific_result = False

        for result in self._iter_room_level_results(external):
            room = normalize_room(result.get("room")) or _room_from_stream_id(result.get("stream_id"))
            if not room:
                continue
            signals = self._signals_from_external_result(result)
            signals = self._apply_home_mode_to_signals(scene, result, signals, home_mode)
            _merge_room_signals(rooms[room], signals)
            used_room_specific_result = True

        target_room = normalize_room(external.get("room")) or normalize_room(frame.get("room"))
        top_level_signals = self._signals_from_external_result(external)
        top_level_signals = self._apply_home_mode_to_signals(scene, external, top_level_signals, home_mode)

        if target_room:
            _merge_room_signals(rooms[target_room], top_level_signals)
        elif any(top_level_signals.values()) and not used_room_specific_result:
            # Whole-home messages do not locate the object. Keep the signal in a
            # representative area while preserving the original room in metadata.
            _merge_room_signals(rooms["living_room"], top_level_signals)

        return rooms

    @staticmethod
    def _iter_room_level_results(external: dict[str, Any]):
        yield from _iter_camera_results(external)
        yield from _iter_room_count_results(external)
        yield from _iter_room_results(external)

    def ingest_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Ingest one VirtualHome frame packet and return an agent response."""
        frame = self._extract_frame(payload)
        external = self._extract_external_result(payload, frame)
        scene = str(
            frame.get("scene")
            or external.get("scene")
            or payload.get("scene")
            or self.current_scene()
        )
        feedback_sample = self._feedback_sample_for_scene(scene)
        packet = {
            "schema": "a210.virtualhome_packet.v1",
            "ingested_at": time.time(),
            "scene": scene,
            "frame": frame,
            "external_result": external,
            "feedback_sample": feedback_sample,
            "live": True,
        }
        _write_json(self.current_packet_file, packet)

        from memory import Memory

        Memory().set_setting("virtualhome_scene", scene)
        state = self.home_state(packet)
        feedback = self._feedback_from_record(scene, packet, state)
        device_update = self._apply_feedback_to_device_state(feedback)
        if device_update:
            payload = feedback.setdefault("payload", {})
            if isinstance(payload, dict):
                payload["agent_device_update"] = device_update
        _append_jsonl(self.feedback_output_file, feedback)
        _append_jsonl(self.bridge_dir / "agent_feedback_actions.jsonl", feedback)

        return {
            "schema": "a210.agent_response.v1",
            "status": "ok",
            "backend": "virtualhome",
            "scene": scene,
            "home_state": state,
            "feedback_action": feedback,
            "feedback_path": str(self.feedback_output_file),
        }

    def latest_feedback(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = _read_jsonl(self.feedback_output_file)
        if limit <= 0:
            return rows
        return rows[-limit:]

    def device_state(self) -> dict[str, Any]:
        raw_state = _read_json(self.device_state_file)
        state = self._normalize_device_state(raw_state)
        if state != raw_state:
            _write_json(self.device_state_file, state)
        return state

    def _normalize_device_state(self, state: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(state) if isinstance(state, dict) else {}
        normalized.setdefault("schema", "virtualhome.device_state.v1")
        normalized.setdefault("updated_at", 0)
        normalized.setdefault("alerts", [])
        normalized.setdefault("environment", {})

        lights = normalized.get("lights") if isinstance(normalized.get("lights"), dict) else {}
        for target, value in LIGHT_DEFAULTS.items():
            lights.setdefault(target, value)
        for target, raw_value in list(lights.items()):
            text = str(raw_value or "").strip().lower()
            lights[target] = "off" if text in {"off", "close", "turn_off", "0", "false"} else "on"
        normalized["lights"] = lights
        normalized.pop("light_modes", None)

        old_speakers = normalized.get("speakers") if isinstance(normalized.get("speakers"), dict) else {}
        speaker = old_speakers.get(WHOLE_HOME_SPEAKER)
        if not isinstance(speaker, dict):
            speaker = self._migrate_whole_home_speaker(old_speakers)
        normalized["speakers"] = {WHOLE_HOME_SPEAKER: self._speaker_state_from_existing(speaker)}
        normalized["music_library"] = self._music_library()
        return normalized

    def _migrate_whole_home_speaker(self, speakers: dict[str, Any]) -> dict[str, Any]:
        return {}

    def _speaker_state_from_existing(self, speaker: dict[str, Any] | None) -> dict[str, Any]:
        library = self._music_library()
        state = str((speaker or {}).get("state") or "stop").strip().lower()
        if state in {"play", "on"}:
            state = "playing"
        elif state in {"off", "stopped"}:
            state = "stop"
        if state not in {"playing", "pause", "stop"}:
            state = "stop"

        track = str((speaker or {}).get("track") or "").strip()
        if state == "stop":
            track = ""
        return {
            "state": state,
            "track": track,
            "scope": "whole_home",
            "source": str((speaker or {}).get("source") or ""),
            "music_dir": str(self.music_dir),
            "available_tracks": [item["name"] for item in library["tracks"]],
        }

    def _music_library(self) -> dict[str, Any]:
        return {
            "dir": str(self.music_dir),
            "supported_extensions": list(MUSIC_EXTENSIONS),
            "tracks": self._available_music_tracks(),
        }

    def _available_music_tracks(self) -> list[dict[str, str]]:
        if not self.music_dir.exists():
            return []
        tracks: list[dict[str, str]] = []
        try:
            files = sorted(
                path
                for path in self.music_dir.iterdir()
                if path.is_file() and path.suffix.lower() in MUSIC_EXTENSIONS
            )
        except OSError:
            return []
        for path in files:
            tracks.append({"name": path.stem, "file": path.name, "path": str(path)})
        return tracks

    def _resolve_music_track(self, value: str | None, source_text: str | None = None) -> str:
        requested = str(value or "").strip()
        tracks = self._available_music_tracks()
        if requested:
            if self._is_health_relief_music_query(requested):
                return HEALTH_RELIEF_TRACK
            if not self._normalize_music_query(requested):
                return tracks[0]["name"] if tracks else ""
            match = self._match_music_track(requested, tracks)
            return match or requested

        source = str(source_text or "").strip()
        if source:
            if self._is_health_relief_music_query(source):
                return HEALTH_RELIEF_TRACK
            match = self._match_music_track(source, tracks)
            if match:
                return match

        return tracks[0]["name"] if tracks else ""

    @staticmethod
    def _is_health_relief_music_query(text: str) -> bool:
        normalized = str(text or "").strip().lower().replace(" ", "")
        return any(token in normalized for token in ("舒缓", "放松", "健康助手", "样本6", "样本06", "06", "scenario06"))

    @staticmethod
    def _match_music_track(text: str, tracks: list[dict[str, str]]) -> str | None:
        needle = VirtualHomeAdapter._normalize_music_query(text)
        if not needle:
            return None
        for track in tracks:
            candidates = {
                VirtualHomeAdapter._normalize_music_query(track["name"]),
                VirtualHomeAdapter._normalize_music_query(track["file"]),
                VirtualHomeAdapter._normalize_music_query(Path(track["file"]).stem),
            }
            if needle in candidates or any(candidate and (needle in candidate or candidate in needle) for candidate in candidates):
                return track["name"]
        return None

    @staticmethod
    def _normalize_music_query(text: str) -> str:
        normalized = str(text or "").strip().lower().replace(" ", "")
        for token in (
            "播放",
            "放一下",
            "放",
            "开始",
            "打开",
            "切换到",
            "切歌到",
            "换成",
            "音乐",
            "歌曲",
            "曲目",
            "歌",
            "首",
            "音箱",
            "全屋",
            "一下",
            "please",
            "play",
            "music",
            "song",
            "speaker",
        ):
            normalized = normalized.replace(token, "")
        for token in ("-", "_", "，", ",", "。", ".", "：", ":", "《", "》", "“", "”", "\"", "'"):
            normalized = normalized.replace(token, "")
        return normalized

    def control_device(
        self,
        room: str,
        device: str,
        command: str,
        value: str | None = None,
        source_text: str | None = None,
    ) -> dict[str, Any]:
        device = str(device or "").strip().lower()
        command = str(command or "").strip().lower()
        if device not in {"light", "speaker"}:
            return {"status": "error", "detail": f"不支持的设备: {device}"}
        if device == "light" and command not in {"on", "off"}:
            return {"status": "error", "detail": "灯光只支持 on/off"}
        if device == "speaker" and command not in {"play", "stop", "pause", "on", "off"}:
            return {"status": "error", "detail": "音箱只支持 play/stop/pause"}

        rooms = self._control_rooms(room)
        if device == "speaker":
            rooms = ["all_rooms"]
            room = "all_rooms"
        elif not rooms:
            return {"status": "error", "detail": f"未知房间: {room}"}

        unity_room = "all_rooms" if device == "speaker" else room
        unity_result = self._control_unity_device_for_agent(unity_room, device, command, value)
        state = self.device_state()
        state["updated_at"] = time.time()
        state["last_command"] = {
            "room": room,
            "rooms": rooms,
            "device": device,
            "command": command,
            "value": value or "",
            "source_text": source_text or "",
            "unity": unity_result,
        }

        feedback_items: list[dict[str, Any]] = []
        if device == "speaker":
            normalized_command = "play" if command == "on" else "stop" if command == "off" else command
            track = self._resolve_music_track(value, source_text)
            if normalized_command == "play" and not track:
                tracks = [item["name"] for item in self._available_music_tracks()]
                detail = "请说出要播放的曲名，例如“播放 DOUDOU”。"
                if tracks:
                    detail += " 当前可选：" + "、".join(tracks)
                return {"status": "error", "detail": detail}
            speaker_state = "playing" if normalized_command == "play" else normalized_command
            state["speakers"] = {
                WHOLE_HOME_SPEAKER: self._speaker_state_from_existing(
                    {
                        "state": speaker_state,
                        "track": track if speaker_state == "playing" else "",
                        "source": "user_music",
                    }
                )
            }
            feedback = self._control_feedback(
                room="all_rooms",
                action="set_device",
                target=WHOLE_HOME_SPEAKER,
                value=normalized_command,
                reason="agent_user_music_command",
                payload={
                    "source_text": source_text or "",
                    "room_label": "全屋",
                    "scope": "whole_home",
                    "track": track,
                    "music_dir": str(self.music_dir),
                    "music_source": "user_music",
                },
            )
            feedback_items.append(feedback)
            _append_jsonl(self.feedback_output_file, feedback)
            _append_jsonl(self.bridge_dir / "agent_feedback_actions.jsonl", feedback)
            value = track if speaker_state == "playing" else (value or "")
        else:
            for item_room in rooms:
                target = f"{item_room}_ceiling_light"
                state["lights"][target] = command
                feedback = self._control_feedback(
                    room=item_room,
                    action="set_light",
                    target=target,
                    value=command,
                    reason="agent_user_light_command",
                    payload={
                        "source_text": source_text or "",
                        "room_label": ROOM_CN.get(item_room, item_room),
                    },
                )
                feedback_items.append(feedback)
                _append_jsonl(self.feedback_output_file, feedback)
                _append_jsonl(self.bridge_dir / "agent_feedback_actions.jsonl", feedback)

        _write_json(self.device_state_file, state)
        room_labels = "全屋" if device == "speaker" else "、".join(ROOM_CN.get(item, item) for item in rooms)
        return {
            "status": "ok",
            "room": room,
            "rooms": rooms,
            "device": device,
            "command": command,
            "value": value or "",
            "device_state_path": str(self.device_state_file),
            "feedback": feedback_items,
            "unity": unity_result,
            "message": self._control_message(room_labels, device, command, value, unity_result),
        }

    def apply_feedback(self, conclusion: str, action: str, message: str, record: dict[str, Any] | None = None) -> dict:
        scene = self.current_scene()
        scene_record = self._scene_records().get(scene, {})
        external = scene_record.get("external_result") or {}
        frame = scene_record.get("frame") or {}
        room = external.get("room") or frame.get("room") or "all_rooms"

        feedback_action = "raise_alert" if action == "alert" else "none"
        value = "alert" if action == "alert" else action
        payload: dict[str, Any] = {
            "agent_conclusion": conclusion,
            "agent_message": message,
            "agent_action": action,
        }
        if record:
            payload["decision_record"] = record

        feedback = {
            "schema": "virtualhome.feedback.v1",
            "source": "a210_agent",
            "scene": scene,
            "room": room,
            "timestamp": time.time(),
            "action": feedback_action,
            "target": "agent_decision",
            "value": value,
            "reason": conclusion,
            "payload": payload,
        }
        _append_jsonl(self.feedback_output_file, feedback)
        return {"status": "ok", "path": str(self.feedback_output_file), "feedback": feedback}

    def _control_rooms(self, room: str) -> list[str]:
        raw = str(room or "").strip().lower().replace("-", "_")
        if raw in {"all", "all_rooms", "whole_home", "home", "全屋", "全部", "所有房间"}:
            return list(ROOMS)
        canonical = normalize_room(raw)
        return [canonical] if canonical else []

    def _control_feedback(
        self,
        room: str,
        action: str,
        target: str,
        value: str,
        reason: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": "virtualhome.feedback.v1",
            "source": "a210_agent",
            "scene": self.current_scene(),
            "room": room,
            "timestamp": time.time(),
            "action": action,
            "target": target,
            "value": value,
            "reason": reason,
            "payload": payload,
        }

    def _control_unity_device(
        self,
        room: str,
        device: str,
        command: str,
        value: str | None,
    ) -> dict[str, Any]:
        if not config.VIRTUAL_HOME_UNITY_CONTROL:
            return {"status": "skipped", "detail": "VIRTUAL_HOME_UNITY_CONTROL is disabled"}

        script = self.root_dir / "src" / "virtualhome_env" / "unity_device_controller.py"
        python_exe = Path(config.VIRTUAL_HOME_PYTHON)
        if not script.exists():
            return {"status": "error", "detail": f"Unity device controller not found: {script}"}
        if not python_exe.exists():
            return {"status": "error", "detail": f"VirtualHome Python not found: {python_exe}"}

        args = [
            str(python_exe),
            str(script),
            "--port",
            str(config.VIRTUAL_HOME_UNITY_PORT),
            "--timeout",
            str(max(1, int(config.VIRTUAL_HOME_UNITY_CONTROL_TIMEOUT))),
            "--room",
            room,
            "--device",
            device,
            "--command",
            command,
        ]
        if value:
            args.extend(["--value", value])

        try:
            completed = subprocess.run(
                args,
                cwd=str(self.root_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(2.0, float(config.VIRTUAL_HOME_UNITY_CONTROL_TIMEOUT)),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "error",
                "detail": f"VirtualHome Unity API control timed out after {exc.timeout}s",
                "port": config.VIRTUAL_HOME_UNITY_PORT,
            }
        except OSError as exc:
            return {"status": "error", "detail": str(exc), "port": config.VIRTUAL_HOME_UNITY_PORT}

        parsed = self._parse_unity_controller_output(completed.stdout)
        if parsed is None:
            parsed = {
                "status": "error" if completed.returncode else "unknown",
                "detail": "Unity controller did not return JSON",
                "stdout": completed.stdout[-1000:],
            }
        parsed.setdefault("returncode", completed.returncode)
        if completed.stderr:
            parsed["stderr"] = completed.stderr[-1000:]
        if completed.returncode != 0 and parsed.get("status") == "ok":
            parsed["status"] = "error"
        return parsed

    def _control_unity_device_for_agent(
        self,
        room: str,
        device: str,
        command: str,
        value: str | None,
    ) -> dict[str, Any]:
        if device == "speaker":
            normalized_command = "play" if command == "on" else "stop" if command == "off" else command
            if normalized_command in {"play", "pause"}:
                silence_result = self._control_unity_device("all_rooms", "speaker", "stop", None)
                return {
                    "status": "ok",
                    "method": "local_music_only",
                    "detail": "Folder music is played by Showcase Panel; Unity TV/radio is kept off to avoid built-in audio.",
                    "silence_unity_media": silence_result,
                }
        return self._control_unity_device(room, device, command, value)

    @staticmethod
    def _parse_unity_controller_output(stdout: str) -> dict[str, Any] | None:
        for line in reversed((stdout or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _control_message(
        room_labels: str,
        device: str,
        command: str,
        value: str | None,
        unity_result: dict[str, Any] | None = None,
    ) -> str:
        unity_status = (unity_result or {}).get("status")
        if unity_status == "ok":
            prefix = "好，已"
        elif unity_status in {"error", "unknown"}:
            detail = (unity_result or {}).get("detail") or "VirtualHome.exe 未连接或控制失败"
            prefix = "我记下了，但 VirtualHome 这边没执行成功："
            if device == "light":
                action_text = "打开" if command == "on" else "关闭"
                return f"{prefix}{detail}。目标动作是{action_text}{room_labels}的灯光。"
            if command in {"play", "on"}:
                return f"{prefix}{detail}。目标动作是播放全屋音乐。"
            if command == "pause":
                return f"{prefix}{detail}。目标动作是暂停全屋音乐。"
            return f"{prefix}{detail}。目标动作是停止全屋音乐。"
        else:
            prefix = "已"

        if device == "light":
            action_text = "打开" if command == "on" else "关闭"
            return f"{prefix}{action_text}{room_labels}的灯光。"
        if command in {"play", "on"}:
            track = f"（{value}）" if value else ""
            return f"{prefix}播放全屋音乐{track}。"
        if command == "pause":
            return f"{prefix}暂停全屋音乐。"
        return f"{prefix}停止全屋音乐。"

    def _scene_records(self) -> dict[str, dict[str, Any]]:
        records = self._sample_scene_records()
        live = _read_json(self.current_packet_file)
        scene = live.get("scene")
        if isinstance(scene, str) and scene:
            records[scene] = live
        return records

    def _sample_scene_records(self) -> dict[str, dict[str, Any]]:
        frames = _read_jsonl(self.frame_stream_file)
        external_results = _read_jsonl(self.external_result_file)
        feedback_samples = _read_jsonl(self.feedback_sample_file)

        records: dict[str, dict[str, Any]] = {}
        for index, frame in enumerate(frames):
            scene = frame.get("scene")
            if not isinstance(scene, str) or not scene:
                continue
            item = records.setdefault(scene, {})
            item["frame"] = frame
            if index < len(external_results):
                item["external_result"] = external_results[index]
            if index < len(feedback_samples):
                item["feedback_sample"] = feedback_samples[index]

        for result in external_results:
            scene = result.get("scene")
            if isinstance(scene, str) and scene:
                records.setdefault(scene, {})["external_result"] = result

        for feedback in feedback_samples:
            scene = feedback.get("scene")
            if isinstance(scene, str) and scene:
                records.setdefault(scene, {})["feedback_sample"] = feedback

        return records

    def _frame_image_path(self, frame: dict[str, Any]) -> Path | None:
        image = frame.get("image")
        if not isinstance(image, dict):
            return None
        raw_path = image.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return None
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.root_dir / path

    def _extract_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        frame = payload.get("frame")
        if isinstance(frame, dict):
            return frame
        if payload.get("schema") == "virtualhome.frame.v1":
            return payload
        return {}

    def _extract_external_result(self, payload: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
        for key in ("external_result", "result", "vision_result"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        scene = frame.get("scene") or payload.get("scene")
        if isinstance(scene, str):
            return copy.deepcopy(self._sample_scene_records().get(scene, {}).get("external_result") or {})
        return {}

    def _feedback_sample_for_scene(self, scene: str) -> dict[str, Any]:
        return copy.deepcopy(self._sample_scene_records().get(scene, {}).get("feedback_sample") or {})

    def _feedback_from_record(self, scene: str, record: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        sample = copy.deepcopy(record.get("feedback_sample") or {})
        if sample and not record.get("live"):
            feedback = sample
            feedback["source"] = "a210_agent"
            feedback["timestamp"] = time.time()
            payload = feedback.setdefault("payload", {})
            if isinstance(payload, dict):
                payload["agent_scene_state"] = self._compact_room_state(state)
                payload["agent_source"] = "a210-smart-home-agent"
            return feedback

        action, target, value, reason, room, payload = self._decide_feedback_from_state(scene, state)
        return {
            "schema": "virtualhome.feedback.v1",
            "source": "a210_agent",
            "scene": scene,
            "room": room,
            "timestamp": time.time(),
            "action": action,
            "target": target,
            "value": value,
            "reason": reason,
            "payload": payload,
        }

    @staticmethod
    def _compact_room_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            room: signals
            for room, signals in (state.get("rooms") or {}).items()
            if isinstance(signals, dict) and any(signals.values())
        }

    def _decide_feedback_from_state(
        self, scene: str, state: dict[str, Any]
    ) -> tuple[str, str, str, str, str, dict[str, Any]]:
        rooms = state.get("rooms") or {}
        virtualhome = state.get("virtualhome") if isinstance(state.get("virtualhome"), dict) else {}
        external = virtualhome.get("external_result") if isinstance(virtualhome.get("external_result"), dict) else {}
        event = str(external.get("event") or _last_timeline_value(external, "event") or "").lower()
        from memory import Memory

        home_mode = Memory().get_home_mode()
        for room_name, signals in rooms.items():
            if not isinstance(signals, dict):
                continue
            if signals.get("hazard_detected"):
                return (
                    "raise_alert",
                    "fire_alarm",
                    str(signals.get("hazard_type") or "hazard_detected"),
                    "hazard_detected",
                    room_name,
                    {"severity": "critical"},
                )
            if home_mode == "away" and self._security_intrusion_signal(scene, signals, event):
                return (
                    "raise_alert",
                    "home_security_alarm",
                    "stranger_detected",
                    "away_mode_unknown_person_detected",
                    "all_rooms",
                    {
                        "mode": home_mode,
                        "severity": "critical",
                        "person_count": _count_or_none(signals.get("person_count")) or 1,
                        "unknown_person_count": _count_or_none(signals.get("unknown_person_count")) or 0,
                    },
                )
            if signals.get("health_recovered"):
                continue
            if signals.get("health_event"):
                return (
                    "set_device",
                    WHOLE_HOME_SPEAKER,
                    "play",
                    "health_event_detected",
                    room_name,
                    {
                        "track": HEALTH_RELIEF_TRACK,
                        "music_scope": "whole_home",
                        "music_source": "health_event",
                        "heart_rate": signals.get("heart_rate"),
                        "anxiety_score": signals.get("anxiety_score"),
                    },
                )
            if (signals.get("has_cat") or signals.get("has_dog")) and not signals.get("has_person"):
                return (
                    "raise_alert_and_set_light",
                    f"{room_name}_pet_guard_and_light",
                    "alert_on_light_off",
                    "pet_present_without_person",
                    room_name,
                    {
                        "set_light": {"target": f"{room_name}_ceiling_light", "value": "off"},
                        "alert": "pet_unattended",
                    },
                )
            if signals.get("fall_like"):
                return (
                    "raise_alert",
                    "fall_detection_alarm",
                    "fall_like_detected",
                    "fall_like_detected",
                    room_name,
                    {"severity": "high"},
                )

        bedroom = rooms.get("bedroom") if isinstance(rooms.get("bedroom"), dict) else {}
        if scene == "bedroom_person" and not bedroom.get("has_person") and event in {
            "person_left",
            "person_left_light_off",
            "room_empty_after_person_left",
        }:
            return (
                "set_light",
                "bedroom_ceiling_light",
                "off",
                "person_count=0_after_person_left",
                "bedroom",
                {"room_scope": "bedroom_only"},
            )

        return ("none", "agent_feedback", "none", "no_action_needed", "all_rooms", {})

    @staticmethod
    def _security_intrusion_signal(scene: str, signals: dict[str, Any], event: str = "") -> bool:
        person_count = _count_or_none(signals.get("person_count")) or 0
        unknown_count = _count_or_none(signals.get("unknown_person_count")) or 0
        if signals.get("unknown_person") or unknown_count > 0:
            return True
        if scene == "away_mode_stranger" and person_count > 0:
            return True
        return person_count > 0 and any(token in event for token in ("unknown", "stranger", "intrusion"))

    def _apply_feedback_to_device_state(self, feedback: dict[str, Any]) -> dict[str, Any]:
        action = str(feedback.get("action") or "none")
        if action == "none":
            return {}

        state = self.device_state()
        state["updated_at"] = time.time()
        state["last_feedback_action"] = feedback

        payload = feedback.get("payload") if isinstance(feedback.get("payload"), dict) else {}
        room = normalize_room(feedback.get("room")) or normalize_room(payload.get("room")) or "living_room"
        unity_results: list[dict[str, Any]] = []

        if action == "set_light":
            target = str(feedback.get("target") or f"{room}_ceiling_light")
            command = self._feedback_light_command(feedback.get("value"))
            state["lights"][target] = command
            unity_results.append(self._control_unity_device(room, "light", command, None))
        elif action == "raise_alert_and_set_light":
            set_light = payload.get("set_light") if isinstance(payload.get("set_light"), dict) else {}
            target = str(set_light.get("target") or feedback.get("target") or f"{room}_ceiling_light")
            command = self._feedback_light_command(set_light.get("value") or feedback.get("value") or "off")
            state["lights"][target] = command
            state["alerts"].append(feedback)
            unity_results.append(self._control_unity_device(room, "light", command, None))
        elif action == "set_environment":
            target = str(feedback.get("target") or f"{room}_environment")
            value = str(feedback.get("value") or "")
            state["environment"][target] = value
            if payload.get("music"):
                music_value = str(payload.get("music") or "").strip()
                music_command = "stop" if music_value.lower() in {"off", "stop", "false", "0"} else "pause" if music_value.lower() == "pause" else "play"
                track = self._resolve_music_track(music_value, None)
                speaker_state = "playing" if music_command == "play" else music_command
                state["speakers"] = {
                    WHOLE_HOME_SPEAKER: self._speaker_state_from_existing(
                        {
                            "state": speaker_state,
                            "track": track if speaker_state == "playing" else "",
                            "source": str(payload.get("music_source") or "health_event"),
                        }
                    )
                }
                unity_results.append(self._control_unity_device_for_agent("all_rooms", "speaker", music_command, track))
        elif action == "set_device":
            target = str(feedback.get("target") or "")
            value = str(feedback.get("value") or "")
            if "speaker" in target or "music" in target:
                command = "play" if value in {"on", "play", "playing"} else "stop" if value in {"off", "stop"} else value
                track = self._resolve_music_track(payload.get("track") if isinstance(payload, dict) else None, None)
                speaker_state = "playing" if command == "play" else command
                if speaker_state == "playing" and not track:
                    speaker_state = "stop"
                state["speakers"] = {
                    WHOLE_HOME_SPEAKER: self._speaker_state_from_existing(
                        {
                            "state": speaker_state,
                            "track": track if speaker_state == "playing" else "",
                            "source": str(payload.get("music_source") or "user_music"),
                        }
                    )
                }
                unity_results.append(self._control_unity_device_for_agent("all_rooms", "speaker", command, track))
            elif target:
                state.setdefault("devices", {})[target] = value
        elif action == "raise_alert":
            state["alerts"].append(feedback)

        _write_json(self.device_state_file, state)
        return {
            "device_state_path": str(self.device_state_file),
            "unity": unity_results,
        }

    @staticmethod
    def _feedback_light_command(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"on", "open", "turn_on", "light_on", "亮", "开"}:
            return "on"
        return "off"

    @staticmethod
    def _home_mode() -> str:
        from memory import Memory

        mode = Memory().get_home_mode()
        return "away" if mode == "away" else "home"

    @staticmethod
    def _apply_home_mode_to_signals(
        scene: str,
        external: dict[str, Any],
        signals: dict[str, Any],
        home_mode: str,
    ) -> dict[str, Any]:
        if scene != "away_mode_stranger":
            return signals

        adjusted = dict(signals)
        person_count = _count_or_none(external.get("person_count"))
        if person_count is None:
            person_count = _count_or_none(adjusted.get("person_count")) or 0
        if person_count > 0:
            adjusted["person_count"] = person_count
            adjusted["has_person"] = True
            adjusted["live_object_count"] = max(_count_or_none(adjusted.get("live_object_count")) or 0, person_count)

        if home_mode != "away":
            adjusted["unknown_person_count"] = 0
            adjusted["unknown_person"] = False
            adjusted["known_resident_count"] = max(_count_or_none(adjusted.get("known_resident_count")) or 0, person_count)
            return adjusted

        if person_count > 0:
            adjusted["unknown_person_count"] = max(_count_or_none(adjusted.get("unknown_person_count")) or 0, person_count)
            adjusted["known_resident_count"] = 0
            adjusted["unknown_person"] = True
        return adjusted

    @staticmethod
    def _signals_from_external_result(result: dict[str, Any]) -> dict[str, Any]:
        signals: dict[str, Any] = {
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
            "health_recovered": False,
            "heart_rate": 0,
            "anxiety_score": 0.0,
            "health_state": "",
            "unknown_person": False,
        }

        person_count = result.get("person_count")
        if person_count is None:
            person_count = _last_timeline_value(result, "person_count")
        person_count = _count_or_none(person_count)
        if person_count is None:
            person_count = _count_from_detections(result, {"person", "human", "person_fall"})

        unknown_count = _count_or_none(result.get("unknown_person_count"))
        if unknown_count is None:
            unknown_count = _count_or_none(_last_timeline_value(result, "unknown_person_count"))
        known_count = _count_or_none(result.get("known_resident_count"))
        if known_count is None:
            known_count = _count_or_none(_last_timeline_value(result, "known_resident_count"))
        if person_count is None and (unknown_count is not None or known_count is not None):
            person_count = (unknown_count or 0) + (known_count or 0)
        if person_count is None and isinstance(result.get("has_person"), bool):
            person_count = 1 if result.get("has_person") else 0

        signals["person_count"] = person_count or 0
        signals["unknown_person_count"] = unknown_count or 0
        signals["known_resident_count"] = known_count or 0
        signals["has_person"] = signals["person_count"] > 0
        signals["unknown_person"] = signals["unknown_person_count"] > 0 or bool(result.get("unknown_person"))
        if signals["unknown_person"] and signals["person_count"] == 0:
            signals["person_count"] = max(1, signals["unknown_person_count"])
            signals["has_person"] = True

        pet_count = result.get("pet_count")
        if pet_count is None:
            pet_count = _last_timeline_value(result, "pet_count")
        pet_count = _count_or_none(pet_count)

        pet_counts = result.get("pet_counts") if isinstance(result.get("pet_counts"), dict) else {}
        cat_count = _count_or_none(result.get("cat_count"))
        dog_count = _count_or_none(result.get("dog_count"))
        if cat_count is None and pet_counts:
            cat_count = sum(_count_or_none(value) or 0 for key, value in pet_counts.items() if "cat" in str(key).lower())
        if dog_count is None and pet_counts:
            dog_count = sum(_count_or_none(value) or 0 for key, value in pet_counts.items() if "dog" in str(key).lower())
        if cat_count is None:
            cat_count = _count_from_detections(result, {"cat"})
        if dog_count is None:
            dog_count = _count_from_detections(result, {"dog"})
        if cat_count is None and isinstance(result.get("has_cat"), bool):
            cat_count = 1 if result.get("has_cat") else 0
        if dog_count is None and isinstance(result.get("has_dog"), bool):
            dog_count = 1 if result.get("has_dog") else 0

        if pet_count is None and (cat_count is not None or dog_count is not None):
            pet_count = (cat_count or 0) + (dog_count or 0)
        if pet_count is None and pet_counts:
            pet_count = sum(_count_or_none(value) or 0 for value in pet_counts.values())

        pet_type = str(result.get("pet_type") or _last_timeline_value(result, "pet_type") or "").lower()
        if pet_count and not cat_count and not dog_count:
            if "dog" in pet_type:
                dog_count = pet_count
            else:
                cat_count = pet_count

        signals["cat_count"] = cat_count or 0
        signals["dog_count"] = dog_count or 0
        signals["pet_count"] = pet_count if pet_count is not None else signals["cat_count"] + signals["dog_count"]
        signals["has_cat"] = signals["cat_count"] > 0
        signals["has_dog"] = signals["dog_count"] > 0
        signals["live_object_count"] = signals["person_count"] + signals["pet_count"]

        event = str(result.get("event") or _last_timeline_value(result, "event") or "").lower()
        posture = str(result.get("posture") or _last_timeline_value(result, "posture") or "").lower()
        signals["fall_like"] = bool(
            result.get("fall_detected")
            or "fall" in event
            or "fall" in posture
            or posture in {"lie", "lying", "fallen"}
        )

        hazard_type = str(result.get("hazard_type") or "").strip()
        if not hazard_type and ("fire" in event or "smoke" in event):
            hazard_type = "fire_smoke"
        signals["hazard_detected"] = bool(result.get("hazard_detected") or hazard_type)
        signals["hazard_type"] = hazard_type if signals["hazard_detected"] else ""

        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        schema = str(result.get("schema") or "")
        heart_rate = _count_or_none(payload.get("heart_rate") if "heart_rate" in payload else result.get("heart_rate"))
        anxiety_score = _float_or_none(payload.get("anxiety_score") if "anxiety_score" in payload else result.get("anxiety_score"))
        health_state = str(payload.get("health_state") or payload.get("state") or result.get("health_state") or "").strip().lower()
        if heart_rate is not None:
            signals["heart_rate"] = heart_rate
        if anxiety_score is not None:
            signals["anxiety_score"] = round(anxiety_score, 2)
        signals["health_state"] = health_state

        has_health_signal = bool(
            schema == "external.health_event.v1"
            or "anxiety" in event
            or "health" in event
            or "heart_rate" in payload
            or "anxiety_score" in payload
        )
        signals["health_recovered"] = has_health_signal and (
            "recover" in event
            or "recovered" in health_state
            or health_state in {"calm_recovered", "back_to_normal"}
        )
        signals["health_event"] = has_health_signal and not signals["health_recovered"] and (
            "anxiety" in event
            or "relief" in event
            or "anxiety" in health_state
            or "relief" in health_state
            or (heart_rate is not None and heart_rate >= 105)
            or (anxiety_score is not None and anxiety_score >= 0.55)
        )

        return signals
