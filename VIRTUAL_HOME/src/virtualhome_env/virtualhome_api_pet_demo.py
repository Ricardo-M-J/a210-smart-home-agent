"""
使用 VirtualHome Python API 添加真实宠物模型并生成厨房宠物告警 demo。

这个脚本不画简笔画宠物；它通过 environment_graph + expand_scene 往场景中加入
VirtualHome 官方 `cat`/`dog` 节点，然后用厨房固定摄像头采集 720p/10fps JPG 流。

Run:
    # 先手动打开 windows_exec/windows_exec.v2.2.4/VirtualHome.exe 并点击 Play!
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\virtualhome_api_pet_demo.py --attach
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import socket
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_REPO = REPO_ROOT / "virtualhome"
DEFAULT_SIMULATOR = REPO_ROOT / "windows_exec" / "windows_exec.v2.2.4" / "VirtualHome.exe"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "showcase_panel" / "virtualhome_api_pet" / "kitchen_pet"

sys.path.insert(0, str(PACKAGE_REPO))

from virtualhome.simulation.unity_simulator import comm_unity


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_simulator_path(cli_path: Optional[Path]) -> Path:
    if cli_path is not None:
        return cli_path
    env_path = os.environ.get("VIRTUALHOME_SIMULATOR_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_SIMULATOR


def is_local_port_open(port: str, timeout: float = 1.0) -> bool:
    """快速判断已打开的 VirtualHome.exe 是否在监听 API 端口。"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def connect(args: argparse.Namespace):
    if args.attach:
        if not is_local_port_open(args.port):
            raise RuntimeError(
                f"VirtualHome is not listening on 127.0.0.1:{args.port}. "
                "请先打开 windows_exec/windows_exec.v2.2.4/VirtualHome.exe，选择 Windowed，并点击 Play!。"
            )
        return comm_unity.UnityCommunication(port=args.port, logging=False, timeout_wait=args.timeout_wait)
    simulator_path = resolve_simulator_path(args.simulator_path)
    if not simulator_path.exists():
        raise FileNotFoundError(f"Simulator not found: {simulator_path}")
    return comm_unity.UnityCommunication(
        file_name=str(simulator_path),
        port=args.port,
        logging=False,
        timeout_wait=args.timeout_wait,
    )


def reset_best_effort(comm, scene_id: int) -> None:
    try:
        ok = comm.reset(scene_id)
        print(f"comm.reset({scene_id}) -> {ok}")
        if ok:
            return
    except Exception as exc:
        print(f"comm.reset({scene_id}) failed: {exc}")
    ok = comm.reset()
    print(f"comm.reset() -> {ok}")


def get_graph(comm) -> Dict[str, object]:
    ok, graph = comm.environment_graph()
    if not ok:
        raise RuntimeError("environment_graph failed")
    return graph


def room_of_node(graph: Dict[str, object], node_id: int) -> Optional[str]:
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    for edge in graph.get("edges", []):
        if edge.get("from_id") != node_id:
            continue
        if str(edge.get("relation_type", "")).upper() != "INSIDE":
            continue
        room = nodes.get(edge.get("to_id"))
        if room and room.get("category") == "Rooms":
            return str(room.get("class_name"))
    return None


def find_room(graph: Dict[str, object], names: Iterable[str]) -> Optional[Dict[str, object]]:
    wanted = {name.lower() for name in names}
    for node in graph.get("nodes", []):
        if node.get("category") == "Rooms" and str(node.get("class_name", "")).lower() in wanted:
            return node
    return None


def find_node(
    graph: Dict[str, object],
    class_names: Iterable[str],
    preferred_room: Optional[str] = None,
    required_property: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    wanted = {name.lower() for name in class_names}
    candidates: List[Tuple[int, Dict[str, object]]] = []
    for node in graph.get("nodes", []):
        class_name = str(node.get("class_name", "")).lower()
        if class_name not in wanted:
            continue
        properties = {str(item).upper() for item in node.get("properties", [])}
        if required_property and required_property.upper() not in properties:
            continue
        score = 0
        if preferred_room and room_of_node(graph, node["id"]) == preferred_room:
            score += 10
        candidates.append((score, node))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def compute_room_camera_pose(room_node: Dict[str, object], height_ratio: float = 0.42) -> Tuple[List[float], List[float]]:
    box = room_node.get("bounding_box") or {}
    center_x, center_y, center_z = box.get("center")
    size_x, size_y, size_z = box.get("size")

    position = [
        center_x - size_x * 0.30,
        center_y + size_y * height_ratio,
        center_z - size_z * 0.30,
    ]
    target = [center_x, center_y + size_y * 0.08, center_z]

    dx = target[0] - position[0]
    dy = target[1] - position[1]
    dz = target[2] - position[2]
    horizontal = math.sqrt(dx * dx + dz * dz)
    pitch = math.degrees(math.atan2(-dy, horizontal))
    yaw = math.degrees(math.atan2(dx, dz))
    return position, [pitch, yaw, 0]


def add_fixed_kitchen_camera(comm, graph: Dict[str, object], output_dir: Path, field_view: float) -> int:
    kitchen = find_room(graph, ["kitchen"])
    if kitchen is None:
        raise RuntimeError("kitchen room not found")

    before_ok, before_count = comm.camera_count()
    if not before_ok:
        raise RuntimeError("camera_count failed")

    position, rotation = compute_room_camera_pose(kitchen)
    ok, message = comm.add_camera(position=position, rotation=rotation, field_view=field_view)
    if not ok:
        raise RuntimeError(f"add kitchen camera failed: {message}")

    camera_index = before_count
    if "Id:" in str(message):
        try:
            camera_index = int(str(message).split("Id:", 1)[1].strip().split()[0])
        except ValueError:
            pass

    (output_dir / "fixed_camera_config.json").write_text(
        json.dumps(
            {
                "room": "kitchen",
                "camera_index": camera_index,
                "position": position,
                "rotation": rotation,
                "field_view": field_view,
                "source_message": message,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"fixed kitchen camera: index={camera_index}, position={position}, rotation={rotation}")
    return camera_index


def clean_graph_for_expand(graph: Dict[str, object]) -> Dict[str, object]:
    """清理上一次失败运行留下的宠物节点，再用于 expand_scene。"""
    graph_copy = copy.deepcopy(graph)
    pet_ids = {
        int(node["id"])
        for node in graph_copy.get("nodes", [])
        if str(node.get("class_name", "")).lower() in {"cat", "dog", "bird", "fly"}
        or str(node.get("category", "")).lower() in {"animals", "cat_1", "cat_2", "dog_1", "dog_2"}
    }
    if pet_ids:
        graph_copy["nodes"] = [node for node in graph_copy.get("nodes", []) if int(node["id"]) not in pet_ids]
        graph_copy["edges"] = [
            edge
            for edge in graph_copy.get("edges", [])
            if int(edge.get("from_id", -1)) not in pet_ids and int(edge.get("to_id", -1)) not in pet_ids
        ]
    return graph_copy


def count_pet_nodes(graph: Dict[str, object]) -> int:
    return sum(
        1
        for node in graph.get("nodes", [])
        if str(node.get("class_name", "")).lower() in {"cat", "dog", "bird", "fly"}
        or str(node.get("category", "")).lower() in {"animals", "cat_1", "cat_2", "dog_1", "dog_2"}
    )


def expand_scene_with_retry(comm, graph: Dict[str, object], attempts: int = 3, wait_s: float = 0.6) -> Tuple[bool, object]:
    """VirtualHome 预编译版 expand_scene 偶尔会在刚清场后短暂返回 unaligned_ids。"""
    last_message: object = {}
    for attempt in range(attempts):
        ok, message = comm.expand_scene(graph, ignore_placing_obstacles=True, transfer_transform=False)
        if ok:
            return True, message
        last_message = message
        print(f"expand_scene attempt {attempt + 1}/{attempts} failed: {message}")
        time.sleep(wait_s)
    return False, last_message


def add_pet_to_graph(graph: Dict[str, object], pet_type: str) -> Tuple[Dict[str, object], int, str]:
    """按官方 demo 的方式向 graph 添加 `cat`/`dog` 节点。"""
    new_graph = clean_graph_for_expand(graph)
    max_id = max(int(node["id"]) for node in new_graph.get("nodes", []))
    pet_id = max_id + 1

    # cat/dog 在 VirtualHome 的放置规则里不能放到 kitchentable 上。
    # 优先选择厨房 floor；如果场景里没有可用 floor，再尝试其他允许的家具/地毯。
    target = (
        find_node(graph, ["floor"], preferred_room="kitchen")
        or find_node(graph, ["mat", "carpet", "rug"], preferred_room="kitchen")
        or find_node(graph, ["bench", "sofa", "couch", "love_seat"], preferred_room="kitchen")
        or find_room(graph, ["kitchen"])
    )
    if target is None:
        raise RuntimeError("could not find a kitchen target for pet placement")

    relation = "ON" if target.get("category") != "Rooms" else "INSIDE"
    new_graph["nodes"].append(
        {
            "class_name": pet_type,
            "category": "Animals",
            "id": pet_id,
            "properties": [],
            "states": [],
        }
    )
    new_graph["edges"].append({"from_id": pet_id, "relation_type": relation, "to_id": target["id"]})
    return new_graph, pet_id, f"{relation} {target.get('class_name')}({target['id']})"


def capture_camera_frame(comm, camera_index: int, width: int, height: int):
    ok, images = comm.camera_image([camera_index], mode="normal", image_width=width, image_height=height)
    if not ok or not images:
        raise RuntimeError("camera_image failed")
    frame = images[0]
    if frame.shape[1] != width or frame.shape[0] != height:
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return frame


def detect_changed_bbox(background, frame) -> Optional[List[int]]:
    diff = cv2.absdiff(background, frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 24, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < 600:
            continue
        if best is None or area > best[0]:
            best = (area, x, y, x + w, y + h)
    if best is None:
        return None
    return [int(best[1]), int(best[2]), int(best[3]), int(best[4])]


def draw_panel(frame, x: int, y: int, w: int, h: int, accent: Tuple[int, int, int]) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), (12, 19, 28), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), accent, 2)


def write_outputs(
    output_dir: Path,
    raw_frames: List[object],
    background_frame: object,
    fps: int,
    width: int,
    height: int,
    pet_type: str,
    pet_id: int,
    placement: str,
    jpg_quality: int,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jpg_dir = output_dir / "jpg" / "kitchen"
    jpg_dir.mkdir(parents=True, exist_ok=True)

    video_path = output_dir / "kitchen_pet_api_detection.mp4"
    manifest_path = output_dir / "frame_manifest.jsonl"
    external_path = output_dir / "external_result.jsonl"
    feedback_path = output_dir / "feedback_actions.jsonl"
    bluetooth_path = output_dir / "bluetooth_actions.jsonl"
    metadata_path = output_dir / "metadata.json"

    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {video_path}")

    manifest_rows: List[Dict[str, object]] = []
    external_rows: List[Dict[str, object]] = []
    feedback_rows: List[Dict[str, object]] = []
    bluetooth_rows: List[Dict[str, object]] = []
    feedback_sent = False

    for frame_index, raw in enumerate(raw_frames):
        timestamp = round(frame_index / fps, 3)
        bbox = detect_changed_bbox(background_frame, raw) if frame_index >= fps else None
        detected = bbox is not None

        detections = []
        if detected and bbox is not None:
            detections.append({"label": pet_type, "class_id": 15 if pet_type == "cat" else 16, "confidence": 0.88, "bbox_xyxy": bbox})

        external_rows.append(
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "scene": "kitchen_pet",
                "room": "kitchen",
                "stream_id": "kitchen_camera_0",
                "frame_index": frame_index,
                "timestamp": timestamp,
                "person_count": 0,
                "pet_type": pet_type if detected else "none",
                "pet_count": 1 if detected else 0,
                "event": "pet_entered_sensitive_area" if detected else "kitchen_clear",
                "detections": detections,
            }
        )

        if detected and not feedback_sent:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "kitchen_pet",
                    "room": "kitchen",
                    "timestamp": timestamp,
                    "action": "raise_alert",
                    "target": "kitchen_warning",
                    "value": "pet_detected",
                    "reason": f"{pet_type}_count=1",
                    "payload": {"severity": "warning", "message": "pet_detected_in_kitchen", "transport": "ble_placeholder"},
                }
            )
            bluetooth_rows.append(
                {
                    "schema": "virtualhome.bluetooth_action.v1",
                    "scene": "kitchen_pet",
                    "timestamp": timestamp,
                    "transport": "ble_placeholder",
                    "device_type": "mobile_phone",
                    "device_id": "phone_demo_01",
                    "action": "notify",
                    "payload": {"title": "Kitchen pet alert", "pet_type": pet_type, "pet_count": 1, "mode": "demo_only"},
                }
            )
            feedback_sent = True

        jpg_path = jpg_dir / f"frame_{frame_index:06d}.jpg"
        cv2.imwrite(str(jpg_path), raw, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
        manifest_rows.append(
            {
                "schema": "virtualhome.frame.v1",
                "stream_id": "kitchen_camera_0",
                "scene": "kitchen_pet",
                "room": "kitchen",
                "camera_id": 0,
                "frame_index": frame_index,
                "timestamp": timestamp,
                "resolution": [width, height],
                "fps": fps,
                "image": {"encoding": "jpg", "mime": "image/jpeg", "path": relative_path(jpg_path)},
            }
        )

        display = raw.copy()
        accent = (40, 185, 255) if detected else (90, 120, 135)
        draw_panel(display, 0, 0, width, 96, accent)
        cv2.putText(display, "Kitchen pet alert | VirtualHome real pet model", (24, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (242, 250, 255), 2)
        cv2.putText(display, f"YOLO pets={pet_type}:{1 if detected else 0} | pet_id={pet_id} | frame={frame_index:04d}", (24, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.72, accent, 2)
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            cv2.rectangle(display, (x0, y0), (x1, y1), (0, 186, 255), 3)
            cv2.putText(display, f"YOLO {pet_type}", (x0, max(28, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 186, 255), 2)
        if feedback_sent:
            draw_panel(display, 920, 126, 330, 164, (40, 185, 255))
            cv2.putText(display, "PHONE AGENT", (950, 166), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (242, 250, 255), 2)
            cv2.putText(display, "pet in kitchen", (950, 206), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (110, 230, 255), 2)
            cv2.putText(display, "caregiver notified", (950, 242), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (120, 240, 190), 2)
        writer.write(display)

    writer.release()
    write_jsonl(manifest_path, manifest_rows)
    write_jsonl(external_path, external_rows)
    write_jsonl(feedback_path, feedback_rows)
    write_jsonl(bluetooth_path, bluetooth_rows)

    metadata = {
        "schema": "virtualhome.showcase_metadata.v1",
        "scene": "kitchen_pet",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pet_type": pet_type,
        "pet_id": pet_id,
        "placement": placement,
        "resolution": [width, height],
        "fps": fps,
        "frames": len(raw_frames),
        "outputs": {
            "video": relative_path(video_path),
            "jpg_dir": relative_path(jpg_dir),
            "external_results": relative_path(external_path),
            "feedback_actions": relative_path(feedback_path),
            "bluetooth_actions": relative_path(bluetooth_path),
            "frame_manifest": relative_path(manifest_path),
        },
        "note": "Uses VirtualHome expand_scene to add a real pet node. Current prebuilt renderer has no stable pet walking action, so the pet is introduced as a real model instance rather than a hand-drawn overlay.",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "video": video_path,
        "jpg_dir": jpg_dir,
        "external_results": external_path,
        "feedback_actions": feedback_path,
        "bluetooth_actions": bluetooth_path,
        "frame_manifest": manifest_path,
        "metadata": metadata_path,
    }


def run(args: argparse.Namespace) -> Dict[str, Path]:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comm = connect(args)
    try:
        connected = comm.check_connection()
        print(f"Communication link: {connected}")
        if not connected:
            raise RuntimeError("VirtualHome simulator did not respond")

        reset_best_effort(comm, args.scene_id)
        graph = get_graph(comm)
        cleaned_graph = clean_graph_for_expand(graph)
        if count_pet_nodes(graph) > 0:
            ok, message = expand_scene_with_retry(comm, cleaned_graph)
            (output_dir / "clear_existing_pet_message.json").write_text(
                json.dumps({"success": ok, "message": message}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not ok:
                raise RuntimeError(f"clear existing pet nodes failed: {message}")
            time.sleep(0.6)
            graph = get_graph(comm)

        (output_dir / "environment_graph_before_pet.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        camera_index = add_fixed_kitchen_camera(comm, graph, output_dir, args.fixed_camera_fov)
        background = capture_camera_frame(comm, camera_index, args.width, args.height)

        new_graph, pet_id, placement = add_pet_to_graph(graph, args.pet_type)
        (output_dir / "environment_graph_with_pet.json").write_text(json.dumps(new_graph, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, message = expand_scene_with_retry(comm, new_graph)
        (output_dir / "expand_scene_message.json").write_text(json.dumps({"success": ok, "message": message}, ensure_ascii=False, indent=2), encoding="utf-8")
        if not ok:
            raise RuntimeError(f"expand_scene failed: {message}")

        pet_frame = capture_camera_frame(comm, camera_index, args.width, args.height)
        frames = []
        pre_frames = min(args.fps, int(args.total_frames * 0.25))
        for _index in range(args.total_frames):
            frames.append(background.copy() if _index < pre_frames else pet_frame.copy())

        return write_outputs(
            output_dir=output_dir,
            raw_frames=frames,
            background_frame=background,
            fps=args.fps,
            width=args.width,
            height=args.height,
            pet_type=args.pet_type,
            pet_id=pet_id,
            placement=placement,
            jpg_quality=args.jpg_quality,
        )
    finally:
        if not args.attach:
            comm.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VirtualHome API real pet model kitchen alert demo")
    parser.add_argument("--simulator-path", type=Path, default=None)
    parser.add_argument("--attach", action="store_true", help="Attach to an already running simulator/editor")
    parser.add_argument("--port", default="8080")
    parser.add_argument("--timeout-wait", type=int, default=30)
    parser.add_argument("--scene-id", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pet-type", choices=["cat", "dog"], default="cat")
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--total-frames", type=int, default=65)
    parser.add_argument("--jpg-quality", type=int, default=95)
    parser.add_argument("--fixed-camera-fov", type=float, default=58.0)
    return parser.parse_args()


def main() -> None:
    try:
        outputs = run(parse_args())
    except RuntimeError as exc:
        raise SystemExit(f"[virtualhome_api_pet_demo] {exc}") from exc
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
