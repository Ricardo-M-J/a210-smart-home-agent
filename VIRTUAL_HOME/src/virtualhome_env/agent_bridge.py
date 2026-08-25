r"""Bridge VirtualHome frame streams to the A210 smart-home agent.

Examples:
    .\vhome\Scripts\python.exe .\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --scene kitchen_pet
    .\vhome\Scripts\python.exe .\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --scene all --loop
    .\vhome\Scripts\python.exe .\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --live-file .\outputs\showcase_panel\live_camera\latest_overview_camera.jpg
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "outputs" / "showcase_panel" / "interface_samples"
FRAME_STREAM_FILE = SAMPLE_DIR / "virtualhome_frame_stream_sample.jsonl"
EXTERNAL_RESULT_FILE = SAMPLE_DIR / "external_result_sample.jsonl"
BRIDGE_OUTPUT_DIR = REPO_ROOT / "outputs" / "agent_bridge"
DEFAULT_LIVE_FILE = REPO_ROOT / "outputs" / "showcase_panel" / "live_overview" / "latest_overview_camera.jpg"
ROOMS = ("living_room", "bedroom", "kitchen", "bathroom")
LIGHT_DEFAULTS = {f"{room}_ceiling_light": "on" for room in ROOMS}
WHOLE_HOME_SPEAKER = "whole_home_speaker"
MUSIC_DIR = REPO_ROOT / "assets" / "music"
MUSIC_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(value, ensure_ascii=False) + "\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def relative_to_repo(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def available_music_tracks() -> list[str]:
    if not MUSIC_DIR.exists():
        return []
    try:
        return [
            path.stem
            for path in sorted(MUSIC_DIR.iterdir())
            if path.is_file() and path.suffix.lower() in MUSIC_EXTENSIONS
        ]
    except OSError:
        return []


def normalize_music_query(text: str) -> str:
    normalized = str(text or "").strip().lower().replace(" ", "")
    for token in ("play", "music", "track", "song", "speaker"):
        normalized = normalized.replace(token, "")
    for token in ("-", "_", ",", ".", ":", ";", "\"", "'"):
        normalized = normalized.replace(token, "")
    return normalized


def resolve_music_track(value: str | None) -> str:
    requested = normalize_music_query(str(value or ""))
    if not requested:
        return ""
    for track in available_music_tracks():
        candidate = normalize_music_query(track)
        if requested == candidate or requested in candidate or candidate in requested:
            return track
    return ""


def normalize_device_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(state) if isinstance(state, dict) else {}
    normalized.setdefault("schema", "virtualhome.device_state.v1")
    normalized.setdefault("updated_at", 0)
    normalized.setdefault("alerts", [])
    normalized.setdefault("environment", {})

    lights = normalized.get("lights") if isinstance(normalized.get("lights"), dict) else {}
    for target, value in LIGHT_DEFAULTS.items():
        lights.setdefault(target, value)
    normalized["lights"] = lights

    speakers = normalized.get("speakers") if isinstance(normalized.get("speakers"), dict) else {}
    whole = speakers.get(WHOLE_HOME_SPEAKER)
    if not isinstance(whole, dict):
        whole = {}
    state_text = str(whole.get("state") or "stop").lower()
    if state_text in {"play", "on"}:
        state_text = "playing"
    elif state_text in {"off", "stopped"}:
        state_text = "stop"
    if state_text not in {"playing", "pause", "stop"}:
        state_text = "stop"
    track = str(whole.get("track") or "")
    if state_text == "stop":
        track = ""
    elif state_text == "playing":
        track = resolve_music_track(track)
        if not track:
            state_text = "stop"
    normalized["speakers"] = {
        WHOLE_HOME_SPEAKER: {
            "state": state_text,
            "track": track,
            "scope": "whole_home",
            "source": str(whole.get("source") or ""),
            "music_dir": str(MUSIC_DIR),
            "available_tracks": available_music_tracks(),
        }
    }
    normalized["music_library"] = {
        "dir": str(MUSIC_DIR),
        "supported_extensions": list(MUSIC_EXTENSIONS),
        "tracks": [{"name": name} for name in available_music_tracks()],
    }
    return normalized


def post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/api/virtualhome/frame",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    value = json.loads(body)
    return value if isinstance(value, dict) else {"status": "error", "raw": value}


def load_sample_packets(scene: str) -> list[dict[str, Any]]:
    frames = read_jsonl(FRAME_STREAM_FILE)
    external_results = read_jsonl(EXTERNAL_RESULT_FILE)
    packets: list[dict[str, Any]] = []

    for index, frame in enumerate(frames):
        frame_scene = frame.get("scene")
        if scene != "all" and frame_scene != scene:
            continue
        external = external_results[index] if index < len(external_results) else {}
        packets.append(
            {
                "schema": "virtualhome.agent_bridge_packet.v1",
                "source": "virtualhome_sample_stream",
                "scene": frame_scene,
                "frame": frame,
                "external_result": external,
            }
        )
    return packets


def apply_feedback_preview(feedback: dict[str, Any]) -> dict[str, Any]:
    """Maintain a local device-state preview from agent feedback actions."""
    state_path = BRIDGE_OUTPUT_DIR / "simulated_device_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except json.JSONDecodeError:
        state = {}

    state = normalize_device_state(state)
    state["updated_at"] = time.time()

    action = feedback.get("action")
    target = str(feedback.get("target") or "")
    value = str(feedback.get("value") or "")
    payload = feedback.get("payload") if isinstance(feedback.get("payload"), dict) else {}

    if action == "set_light" and target:
        state["lights"][target] = value
    elif action == "raise_alert_and_set_light":
        set_light = payload.get("set_light") if isinstance(payload.get("set_light"), dict) else {}
        light_target = str(set_light.get("target") or target)
        light_value = str(set_light.get("value") or "off")
        if light_target:
            state["lights"][light_target] = light_value
        state["alerts"].append(feedback)
    elif action == "set_environment" and target:
        state.setdefault("environment", {})[target] = value
        if payload.get("music"):
            music_value = str(payload.get("music") or "").strip()
            music_state = "stop" if music_value.lower() in {"off", "stop", "false", "0"} else "pause" if music_value.lower() == "pause" else "playing"
            music_track = resolve_music_track(music_value)
            if music_state == "playing" and not music_track:
                music_state = "stop"
            state["speakers"] = {
                WHOLE_HOME_SPEAKER: {
                    "state": music_state,
                    "track": music_track if music_state == "playing" else "",
                    "scope": "whole_home",
                    "source": str(payload.get("music_source") or "health_event"),
                    "music_dir": str(MUSIC_DIR),
                    "available_tracks": available_music_tracks(),
                }
            }
    elif action == "set_device" and target:
        if "speaker" in target or "music" in target:
            music_state = "playing" if value in {"play", "playing", "on"} else value
            music_track = resolve_music_track(str(payload.get("track") or ""))
            if music_state == "playing" and not music_track:
                music_state = "stop"
            state["speakers"] = {
                WHOLE_HOME_SPEAKER: {
                    "state": music_state,
                    "track": music_track if music_state == "playing" else "",
                    "scope": "whole_home",
                    "source": str(payload.get("music_source") or "user_music"),
                    "music_dir": str(MUSIC_DIR),
                    "available_tracks": available_music_tracks(),
                }
            }
        else:
            state.setdefault("devices", {})[target] = value
    elif action == "raise_alert":
        state["alerts"].append(feedback)

    write_json(state_path, state)
    return state


def emit_response(response: dict[str, Any]) -> None:
    feedback = response.get("feedback_action") if isinstance(response.get("feedback_action"), dict) else {}
    append_jsonl(BRIDGE_OUTPUT_DIR / "agent_responses.jsonl", response)
    if feedback:
        append_jsonl(BRIDGE_OUTPUT_DIR / "agent_feedback_actions.jsonl", feedback)
        device_state = apply_feedback_preview(feedback)
    else:
        device_state = {}
    print(
        "[bridge] scene={scene} status={status} action={action} target={target} value={value}".format(
            scene=response.get("scene"),
            status=response.get("status"),
            action=feedback.get("action"),
            target=feedback.get("target"),
            value=feedback.get("value"),
        )
    )
    if device_state:
        print(f"[bridge] device_state={BRIDGE_OUTPUT_DIR / 'simulated_device_state.json'}")


def stream_samples(args: argparse.Namespace) -> None:
    packets = load_sample_packets(args.scene)
    if not packets:
        raise SystemExit(f"No sample packets found for scene={args.scene!r}")

    sent = 0
    while True:
        for packet in packets:
            response = post_json(args.agent_url, packet, args.timeout)
            emit_response(response)
            sent += 1
            if args.max_frames and sent >= args.max_frames:
                return
            time.sleep(args.interval)
        if not args.loop:
            return


def stream_live_file(args: argparse.Namespace) -> None:
    image_path = Path(args.live_file)
    frame_index = 0
    last_mtime = None
    print(f"[bridge] watching live file: {image_path}")
    while True:
        if not image_path.exists():
            time.sleep(args.interval)
            continue
        mtime = image_path.stat().st_mtime
        if mtime == last_mtime:
            time.sleep(args.interval)
            continue
        last_mtime = mtime
        frame = {
            "schema": "virtualhome.frame.v1",
            "stream_id": "whole_home_overview_camera",
            "scene": args.scene if args.scene != "all" else "whole_home_overview",
            "room": "all_rooms",
            "camera_id": 0,
            "frame_index": frame_index,
            "timestamp": time.time(),
            "resolution": [1280, 720],
            "fps": max(1, round(1 / args.interval)),
            "image": {"encoding": "jpg", "mime": "image/jpeg", "path": relative_to_repo(image_path)},
        }
        packet = {
            "schema": "virtualhome.agent_bridge_packet.v1",
            "source": "virtualhome_live_file",
            "scene": frame["scene"],
            "frame": frame,
        }
        response = post_json(args.agent_url, packet, args.timeout)
        emit_response(response)
        frame_index += 1
        if args.max_frames and frame_index >= args.max_frames:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream VirtualHome frames to the A210 agent")
    parser.add_argument("--agent-url", default="http://127.0.0.1:8019", help="Agent web URL")
    parser.add_argument("--scene", default="all", help="sample scene name, or all")
    parser.add_argument("--loop", action="store_true", help="repeat sample packets")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between frames")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    parser.add_argument("--max-frames", type=int, default=0, help="stop after N frames; 0 means no explicit limit")
    parser.add_argument(
        "--live-file",
        default=None,
        help=f"watch a live camera JPG file instead of sample JSONL; default candidate is {DEFAULT_LIVE_FILE}",
    )
    parser.add_argument("--use-default-live-file", action="store_true", help="watch the showcase panel live overview JPG")
    args = parser.parse_args()

    BRIDGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if args.use_default_live_file and not args.live_file:
            args.live_file = str(DEFAULT_LIVE_FILE)
        if args.live_file:
            stream_live_file(args)
        else:
            stream_samples(args)
    except urllib.error.URLError as exc:
        raise SystemExit(f"Agent endpoint is not reachable: {exc}") from exc


if __name__ == "__main__":
    main()
