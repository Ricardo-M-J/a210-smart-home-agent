"""
使用 VirtualHome 官方 Python API 生成更自然的人物动画 demo。

这个脚本和之前的 Python 合成视频不同：它不手工平移人物贴图，而是把活动脚本交给
VirtualHome/Unity 的 render_script 执行，让角色使用模拟器内置动画自然行走和坐下。

注意：
- VirtualHome Python 侧图执行器中有 [walk]、[sit]、[lie]、[standup] 等动作；
- 当前本地预编译 Unity 渲染器没有开放 [fall]，并且实测 [lie] 会解析失败；
- 因此“跌倒”只能先自动降级为 [walk] + [sit] 的异常静止姿态展示；
- 若要真实“摔倒到地面”的动画，需要在 Unity 源码项目中增加 fall 动画/状态机后重新构建 exe。

Run:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\virtualhome_api_motion_demo.py --scenario bedroom_walk_light
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\virtualhome_api_motion_demo.py --scenario fall_lie_ble
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_REPO = REPO_ROOT / "virtualhome"
DEFAULT_SIMULATOR = REPO_ROOT / "windows_exec" / "windows_exec.v2.2.4" / "VirtualHome.exe"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "showcase_panel" / "virtualhome_api_motion"

sys.path.insert(0, str(PACKAGE_REPO))

from virtualhome.simulation.unity_simulator import comm_unity


def resolve_simulator_path(cli_path: Optional[Path]) -> Path:
    """优先使用命令行，其次使用环境变量，最后使用仓库内默认 exe。"""
    if cli_path is not None:
        return cli_path
    env_path = os.environ.get("VIRTUALHOME_SIMULATOR_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_SIMULATOR


def connect(args: argparse.Namespace):
    """启动或连接 VirtualHome simulator。"""
    if args.attach:
        return comm_unity.UnityCommunication(
            port=args.port,
            logging=False,
            timeout_wait=args.timeout_wait,
        )

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
    """兼容新旧 VirtualHome 可执行文件的 reset 行为。"""
    try:
        ok = comm.reset(scene_id)
        print(f"comm.reset({scene_id}) -> {ok}")
        if ok:
            return
    except Exception as exc:
        print(f"comm.reset({scene_id}) failed: {exc}")

    try:
        ok = comm.reset()
        print(f"comm.reset() -> {ok}")
    except Exception as exc:
        print(f"comm.reset() failed, continue with currently loaded scene: {exc}")


def get_graph(comm) -> Dict[str, object]:
    ok, graph = comm.environment_graph()
    if not ok:
        raise RuntimeError("environment_graph failed")
    return graph


def room_of_node(graph: Dict[str, object], node_id: int) -> Optional[str]:
    """根据 INSIDE 边粗略判断物体所在房间。"""
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
    """从环境图中找一个适合脚本动作的目标物体。"""
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


def script_line(action: str, node: Optional[Dict[str, object]]) -> str:
    if node is None:
        raise ValueError(f"cannot build [{action}] line with empty node")
    return f"<char0> [{action}] <{node['class_name']}> ({node['id']})"


def parse_camera_id(message: str) -> Optional[int]:
    """从 Unity 返回的 'New camera created. Id:79' 中解析固定摄像头 id。"""
    match = re.search(r"Id:(\d+)", message or "")
    if not match:
        return None
    return int(match.group(1))


def compute_room_camera_pose(room_node: Dict[str, object], height_ratio: float = 0.38) -> Tuple[List[float], List[float]]:
    """根据房间 bounding box 放置一个固定角落摄像头，朝向房间中心。"""
    box = room_node.get("bounding_box") or {}
    center_x, center_y, center_z = box.get("center")
    size_x, size_y, size_z = box.get("size")

    position = [
        center_x - size_x * 0.28,
        center_y + size_y * height_ratio,
        center_z - size_z * 0.28,
    ]
    target = [center_x, center_y + size_y * 0.06, center_z]

    dx = target[0] - position[0]
    dy = target[1] - position[1]
    dz = target[2] - position[2]
    horizontal = math.sqrt(dx * dx + dz * dz)

    pitch = math.degrees(math.atan2(-dy, horizontal))
    yaw = math.degrees(math.atan2(dx, dz))
    return position, [pitch, yaw, 0]


def add_fixed_room_camera(
    comm,
    graph: Dict[str, object],
    room_name: str,
    output_dir: Path,
    field_view: float,
    height_ratio: float,
) -> int:
    """添加一个固定房间摄像头，并返回可传给 render_script(camera_mode=...) 的 id。"""
    room_node = find_room(graph, [room_name])
    if room_node is None:
        raise RuntimeError(f"room not found: {room_name}")

    before_ok, before_count = comm.camera_count()
    if not before_ok:
        raise RuntimeError("camera_count failed before add_camera")

    position, rotation = compute_room_camera_pose(room_node, height_ratio=height_ratio)
    ok, message = comm.add_camera(position=position, rotation=rotation, field_view=field_view)
    if not ok:
        raise RuntimeError(f"add fixed room camera failed: {message}")

    camera_index = parse_camera_id(message) or before_count
    camera_config = {
        "room": room_name,
        "camera_index": camera_index,
        "position": position,
        "rotation": rotation,
        "field_view": field_view,
        "height_ratio": height_ratio,
        "source_message": message,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "fixed_camera_config.json").write_text(
        json.dumps(camera_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"fixed camera for {room_name}: index={camera_index}, position={position}, rotation={rotation}")
    return camera_index


def build_bedroom_walk_script(graph: Dict[str, object]) -> List[str]:
    """人物自然进入卧室再离开，用于替换之前的贴图平移动作。"""
    bedroom = find_room(graph, ["bedroom"])
    livingroom = find_room(graph, ["livingroom", "living_room"])
    bed = find_node(graph, ["bed"], preferred_room="bedroom", required_property="LIEABLE")
    bedroom_chair = find_node(graph, ["chair", "sofa", "couch", "bench"], preferred_room="bedroom")
    living_target = find_node(graph, ["sofa", "couch", "chair"], preferred_room="livingroom")

    enter_target = bed or bedroom_chair or bedroom
    leave_target = living_target or livingroom

    if enter_target is None or leave_target is None:
        # find_solution=True 可以让模拟器按 class_name 自动补实例，这里给一个最通用的备用脚本。
        return [
            "<char0> [walk] <bedroom> (1)",
            "<char0> [walk] <livingroom> (1)",
        ]

    return [
        script_line("walk", enter_target),
        script_line("walk", leave_target),
    ]


def build_fall_lie_script(graph: Dict[str, object]) -> List[str]:
    """优先尝试 [lie]。注意：当前 windows_exec.v2.2.4 可能不支持这个渲染动作。"""
    bedroom = find_room(graph, ["bedroom"])
    bed = find_node(graph, ["bed"], preferred_room="bedroom", required_property="LIEABLE")
    sofa = find_node(graph, ["sofa", "couch", "bench"], preferred_room="livingroom", required_property="LIEABLE")
    lie_target = bed or sofa or bedroom

    if lie_target is None:
        return [
            "<char0> [walk] <bed> (1)",
            "<char0> [lie] <bed> (1)",
            "<char0> [sleep]",
        ]

    return [
        script_line("walk", lie_target),
        script_line("lie", lie_target),
        "<char0> [sleep]",
    ]


def build_fall_sit_fallback_script(graph: Dict[str, object]) -> List[str]:
    """当预编译 Unity 渲染器不支持 [lie] 时，用 [sit] 表达异常静止姿态。"""
    bedroom = find_room(graph, ["bedroom"])
    bed = find_node(graph, ["bed"], preferred_room="bedroom", required_property="SITTABLE")
    sofa = find_node(graph, ["sofa", "couch", "bench", "chair"], preferred_room="livingroom", required_property="SITTABLE")
    sit_target = bed or sofa or bedroom

    if sit_target is None:
        return [
            "<char0> [walk] <bed> (1)",
            "<char0> [sit] <bed> (1)",
        ]

    return [
        script_line("walk", sit_target),
        script_line("sit", sit_target),
    ]


def render(comm, script: List[str], output_dir: Path, prefix: str, args: argparse.Namespace):
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / f"{prefix}_script.txt"
    script_path.write_text("\n".join(script) + "\n", encoding="utf-8")

    print("Rendering script:")
    for line in script:
        print(f"  {line}")

    ok, message = comm.render_script(
        script=script,
        recording=True,
        find_solution=True,
        output_folder=str(output_dir),
        file_name_prefix=prefix,
        frame_rate=args.fps,
        image_width=args.width,
        image_height=args.height,
        camera_mode=args.camera_mode,
        skip_animation=False,
        time_scale=args.time_scale,
        processing_time_limit=args.processing_time_limit,
    )

    message_path = output_dir / f"{prefix}_render_message.json"
    message_path.write_text(json.dumps({"success": ok, "message": message}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not ok:
        raise RuntimeError(f"render_script failed: {message}")
    postprocess_render_frames(
        output_dir=output_dir,
        prefix=prefix,
        scene=f"virtualhome_api_{prefix}",
        room="bedroom",
        stream_id="bedroom_camera_0",
        fps=args.fps,
        width=args.width,
        height=args.height,
        jpg_quality=args.jpg_quality,
    )
    return message


def render_with_fallbacks(
    comm,
    script_candidates: List[Tuple[str, List[str]]],
    output_dir: Path,
    final_prefix: str,
    args: argparse.Namespace,
) -> None:
    """按顺序尝试渲染脚本；前一个动作不被 Unity 支持时自动降级。"""
    last_error = None
    for attempt_index, (attempt_name, script) in enumerate(script_candidates):
        prefix = final_prefix if attempt_index == len(script_candidates) - 1 else f"{final_prefix}_{attempt_name}"
        try:
            render(comm, script, output_dir, prefix, args)
            if attempt_index > 0:
                fallback_path = output_dir / f"{final_prefix}_fallback_note.json"
                fallback_path.write_text(
                    json.dumps(
                        {
                            "used_fallback": True,
                            "fallback": attempt_name,
                            "reason": str(last_error),
                            "note": "The current prebuilt Unity renderer does not expose a native fall/lie animation.",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            return
        except RuntimeError as exc:
            last_error = exc
            print(f"Render attempt {attempt_name!r} failed: {exc}")
            continue
    raise RuntimeError(f"all render attempts failed: {last_error}")



def postprocess_render_frames(
    output_dir: Path,
    prefix: str,
    scene: str,
    room: str,
    stream_id: str,
    fps: int,
    width: int,
    height: int,
    jpg_quality: int,
) -> None:
    """把 render_script 输出的 PNG 帧整理成 MP4 和 JPG 图像流。"""
    output_dir = output_dir.resolve()
    source_root = output_dir / prefix
    frames = sorted(source_root.rglob("*_normal.png"))
    if not frames:
        frames = sorted(source_root.rglob("*.png"))
    if not frames:
        print(f"No rendered PNG frames found under: {source_root}")
        return

    video_path = output_dir / f"{prefix}_api_recording.mp4"
    jpg_dir = output_dir / "jpg" / room
    manifest_path = output_dir / "frame_manifest.jsonl"
    jpg_dir.mkdir(parents=True, exist_ok=True)

    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {video_path}")

    manifest_rows = []
    for index, frame_path in enumerate(frames):
        image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        if image.shape[1] != width or image.shape[0] != height:
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

        writer.write(image)
        jpg_path = jpg_dir / f"frame_{index:06d}.jpg"
        cv2.imwrite(str(jpg_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
        manifest_rows.append(
            {
                "schema": "virtualhome.frame.v1",
                "stream_id": stream_id,
                "scene": scene,
                "room": room,
                "camera_id": 0,
                "frame_index": index,
                "timestamp": round(index / fps, 3),
                "resolution": [width, height],
                "fps": fps,
                "image": {
                    "encoding": "jpg",
                    "mime": "image/jpeg",
                    "path": str(jpg_path.relative_to(REPO_ROOT)),
                },
            }
        )

    writer.release()
    write_jsonl(manifest_path, manifest_rows)
    print(f"Postprocessed frames: {len(manifest_rows)}")
    print(f"MP4: {video_path}")
    print(f"JPG stream: {jpg_dir}")
    print(f"Frame manifest: {manifest_path}")

    if scene == "virtualhome_api_bedroom_walk_light":
        write_bedroom_yolo_light_sync(
            output_dir=output_dir,
            frames=frames,
            fps=fps,
            width=width,
            height=height,
            room=room,
            stream_id=stream_id,
        )


def detect_person_bbox(background: object, frame: object) -> Optional[List[int]]:
    """用固定摄像头背景差分模拟 YOLO person 检测框。"""
    diff = cv2.absdiff(background, frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    _, mask = cv2.threshold(gray, 28, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    num_labels, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < 1800 or h < 60:
            continue
        score = int(area * (1.4 if h > w else 1.0))
        if best is None or score > best[0]:
            best = (score, int(x), int(y), int(x + w), int(y + h))

    if best is None:
        return None
    return [best[1], best[2], best[3], best[4]]


def apply_bedroom_only_light_off(frame: object) -> object:
    """只压暗卧室主体区域，门口能看到的其他房间保持亮度。"""
    height, width = frame.shape[:2]
    dark = np.clip(frame.astype(np.float32) * 0.34, 0, 255).astype(np.uint8)
    cool = np.zeros_like(dark)
    cool[:, :, 0] = 18
    dark = cv2.addWeighted(dark, 0.92, cool, 0.08, 0)

    mask = np.full((height, width), 255, dtype=np.uint8)
    # 摄像头能通过两个门口看到其他空间；这些区域不参与“卧室关灯”压暗。
    protected_openings = [
        np.array([[520, 190], [620, 198], [620, 390], [520, 372]], dtype=np.int32),
        np.array([[860, 196], [990, 214], [990, 468], [858, 438]], dtype=np.int32),
    ]
    for polygon in protected_openings:
        cv2.fillPoly(mask, [polygon], 0)
    mask = cv2.GaussianBlur(mask, (51, 51), 0)
    alpha = (mask.astype(np.float32) / 255.0 * 0.74)[:, :, None]
    return np.clip(frame.astype(np.float32) * (1.0 - alpha) + dark.astype(np.float32) * alpha, 0, 255).astype(np.uint8)


def write_bedroom_yolo_light_sync(
    output_dir: Path,
    frames: List[Path],
    fps: int,
    width: int,
    height: int,
    room: str,
    stream_id: str,
) -> None:
    """把固定摄像头帧、YOLO 替代检测、agent 关灯反馈同步到同一条时间线。"""
    if not frames:
        return

    first_frame = cv2.imread(str(frames[0]), cv2.IMREAD_COLOR)
    if first_frame is None:
        return
    if first_frame.shape[1] != width or first_frame.shape[0] != height:
        first_frame = cv2.resize(first_frame, (width, height), interpolation=cv2.INTER_AREA)

    raw_frames: List[object] = []
    raw_bboxes: List[Optional[List[int]]] = []
    for frame_path in frames:
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        raw_frames.append(frame)
        raw_bboxes.append(detect_person_bbox(first_frame, frame))

    raw_present = [bbox is not None for bbox in raw_bboxes]
    segments: List[Tuple[int, int]] = []
    start = None
    last_true = None
    max_gap = 10
    for index, present in enumerate(raw_present):
        if present:
            if start is None:
                start = index
            last_true = index
        elif start is not None and last_true is not None and index - last_true > max_gap:
            segments.append((start, last_true))
            start = None
            last_true = None
    if start is not None and last_true is not None:
        segments.append((start, last_true))

    if segments:
        # 只保留固定房间摄像头中最主要的人物出现区间，避免远处/光照变化造成零散误检。
        presence_start, presence_end = max(segments, key=lambda item: item[1] - item[0])
        light_off_frame: Optional[int] = min(len(raw_frames) - 1, presence_end + 5)
    else:
        presence_start, presence_end = -1, -1
        light_off_frame = None

    yolo_rows: List[Dict[str, object]] = []
    feedback_rows: List[Dict[str, object]] = []
    last_bbox: Optional[List[int]] = None

    overlay_video = output_dir / "bedroom_walk_light_yolo_light_feedback.mp4"
    writer = cv2.VideoWriter(str(overlay_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {overlay_video}")

    for index, frame in enumerate(raw_frames):
        raw_bbox = raw_bboxes[index]
        if raw_bbox is not None:
            last_bbox = raw_bbox

        person_count = 1 if presence_start <= index <= presence_end else 0
        bbox = raw_bbox if raw_bbox is not None else (last_bbox if person_count else None)
        timestamp = round(index / fps, 3)

        if light_off_frame == index:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "virtualhome_api_bedroom_walk_light",
                    "room": room,
                    "timestamp": timestamp,
                    "action": "set_light",
                    "target": "bedroom_ceiling_light",
                    "value": "off",
                    "reason": "person_count=0_after_person_left",
                    "payload": {
                        "room_scope": "bedroom_only",
                        "unaffected_rooms": ["kitchen", "bathroom", "livingroom"],
                        "trigger_frame_index": index,
                        "stream_id": stream_id,
                    },
                }
            )

        event = "person_present" if person_count else "room_empty"
        if person_count == 1 and len(yolo_rows) > 0 and yolo_rows[-1].get("person_count") == 0:
            event = "person_entered"
        if light_off_frame == index:
            event = "person_left_light_off"

        detections = []
        if bbox:
            detections.append(
                {
                    "label": "person",
                    "class_id": 0,
                    "confidence": 0.88,
                    "bbox_xyxy": bbox,
                }
            )

        yolo_rows.append(
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_from_fixed_camera_frames",
                "scene": "virtualhome_api_bedroom_walk_light",
                "room": room,
                "stream_id": stream_id,
                "frame_index": index,
                "timestamp": timestamp,
                "person_count": person_count,
                "event": event,
                "detections": detections,
            }
        )

        display = frame.copy()
        if light_off_frame is not None and index >= light_off_frame:
            display = apply_bedroom_only_light_off(display)

        panel_color = (20, 32, 44)
        accent = (60, 230, 255) if person_count else (80, 110, 125)
        cv2.rectangle(display, (0, 0), (1280, 94), panel_color, -1)
        cv2.rectangle(display, (0, 0), (1280, 94), accent, 2)
        cv2.putText(display, "Person count + bedroom-only light control", (24, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (242, 250, 255), 2)
        light_state = "OFF" if light_off_frame is not None and index >= light_off_frame else "ON"
        cv2.putText(display, f"person_count={person_count} | bedroom_light={light_state} | frame={index:04d}", (24, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.72, accent, 2)
        if bbox:
            x0, y0, x1, y1 = bbox
            cv2.rectangle(display, (x0, y0), (x1, y1), (80, 240, 120), 3)
            cv2.putText(display, "YOLO person", (x0, max(28, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (80, 240, 120), 2)
        if light_off_frame == index:
            cv2.putText(display, "AGENT: set bedroom light off", (790, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (80, 180, 255), 2)

        writer.write(display)

    writer.release()

    if not feedback_rows:
        last_timestamp = round((len(yolo_rows) - 1) / fps, 3)
        feedback_rows.append(
            {
                "schema": "virtualhome.feedback.v1",
                "source": "external_agent",
                "scene": "virtualhome_api_bedroom_walk_light",
                "room": room,
                "timestamp": last_timestamp,
                "action": "none",
                "target": "bedroom_ceiling_light",
                "value": "unchanged",
                "reason": "person_exit_not_detected_in_demo_frames",
            }
        )

    write_jsonl(output_dir / "yolo_person_count.jsonl", yolo_rows)
    write_jsonl(output_dir / "external_result.jsonl", yolo_rows)
    write_jsonl(output_dir / "feedback_actions.jsonl", feedback_rows)

    metadata = {
        "schema": "virtualhome.sync_demo_metadata.v1",
        "scene": "virtualhome_api_bedroom_walk_light",
        "room": room,
        "fixed_camera": True,
        "source_frames": len(raw_frames),
        "fps": fps,
        "resolution": [width, height],
        "presence_interval": [presence_start, presence_end],
        "raw_presence_segments": segments,
        "light_off_frame": light_off_frame,
        "outputs": {
            "yolo_results": str((output_dir / "yolo_person_count.jsonl").relative_to(REPO_ROOT)),
            "feedback_actions": str((output_dir / "feedback_actions.jsonl").relative_to(REPO_ROOT)),
            "overlay_video": str(overlay_video.relative_to(REPO_ROOT)),
        },
    }
    (output_dir / "sync_timeline_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"YOLO presence interval: {presence_start}..{presence_end}")
    print(f"YOLO sync results: {output_dir / 'yolo_person_count.jsonl'}")
    print(f"Light feedback: {output_dir / 'feedback_actions.jsonl'}")
    print(f"Overlay demo video: {overlay_video}")


def write_jsonl(path: Path, rows: List[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_placeholder_contracts(scenario: str, output_dir: Path) -> None:
    """把 API 动画 demo 对应的外部检测/反馈接口也落盘，方便和旧面板联动。"""
    if scenario == "bedroom_walk_light":
        external_rows = [
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "room": "bedroom",
                "person_count": 1,
                "event": "person_entered",
            },
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "room": "bedroom",
                "person_count": 0,
                "event": "person_left",
            },
        ]
        feedback_rows = [
            {
                "schema": "virtualhome.feedback.v1",
                "source": "external_agent",
                "scene": "virtualhome_api_bedroom_walk_light",
                "room": "bedroom",
                "timestamp": 0.0,
                "action": "set_light",
                "target": "bedroom_ceiling_light",
                "value": "off",
                "reason": "person_count=0",
                "payload": {"room_scope": "bedroom_only"},
            }
        ]
        write_jsonl(output_dir / "external_result.jsonl", external_rows)
        write_jsonl(output_dir / "feedback_actions.jsonl", feedback_rows)
    else:
        external_rows = [
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "room": "bedroom",
                "person_count": 1,
                "fall_detected": True,
                "fall_confidence": 0.9,
                "posture": "lying_or_sitting_still",
                "risk_level": "critical",
                "event": "fall_like_or_abnormal_posture_detected",
            }
        ]
        feedback_rows = [
            {
                "schema": "virtualhome.feedback.v1",
                "source": "external_agent",
                "scene": "virtualhome_api_fall_lie_ble",
                "room": "bedroom",
                "timestamp": 0.0,
                "action": "notify_bluetooth_device",
                "target": "watch_and_phone",
                "value": "emergency_call_and_message",
                "reason": "fall_like_or_abnormal_posture_detected",
                "payload": {
                    "transport": "ble_placeholder",
                    "devices": ["smart_watch", "mobile_phone"],
                    "mode": "demo_only",
                },
            }
        ]
        bluetooth_rows = [
            {
                "schema": "virtualhome.bluetooth_action.v1",
                "scene": "virtualhome_api_fall_lie_ble",
                "timestamp": 0.0,
                "transport": "ble_placeholder",
                "device_type": "smart_watch",
                "device_id": "watch_demo_01",
                "action": "vibrate_and_prompt",
                "payload": {"prompt": "fall_detected_confirm_status", "mode": "demo_only"},
            },
            {
                "schema": "virtualhome.bluetooth_action.v1",
                "scene": "virtualhome_api_fall_lie_ble",
                "timestamp": 0.1,
                "transport": "ble_placeholder",
                "device_type": "mobile_phone",
                "device_id": "phone_demo_01",
                "action": "place_call",
                "payload": {"target": "emergency_contact_primary", "mode": "demo_only"},
            },
            {
                "schema": "virtualhome.bluetooth_action.v1",
                "scene": "virtualhome_api_fall_lie_ble",
                "timestamp": 0.2,
                "transport": "ble_placeholder",
                "device_type": "mobile_phone",
                "device_id": "phone_demo_01",
                "action": "send_message",
                "payload": {
                    "target": "emergency_contacts",
                    "template": "fall_detected_room_location",
                    "mode": "demo_only",
                },
            },
        ]
        write_jsonl(output_dir / "external_result.jsonl", external_rows)
        write_jsonl(output_dir / "feedback_actions.jsonl", feedback_rows)
        write_jsonl(output_dir / "bluetooth_actions.jsonl", bluetooth_rows)


def run_scenario(comm, args: argparse.Namespace) -> None:
    reset_best_effort(comm, args.scene_id)
    ok = comm.add_character(args.character, initial_room=args.initial_room)
    print(f"add_character({args.character!r}, initial_room={args.initial_room!r}) -> {ok}")
    if not ok:
        raise RuntimeError("add_character failed")

    graph = get_graph(comm)
    graph_path = args.output_dir / args.scenario / "environment_graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    scenario_dir = args.output_dir / args.scenario
    if args.scenario == "bedroom_walk_light":
        if args.fixed_room_camera:
            camera_index = add_fixed_room_camera(
                comm=comm,
                graph=graph,
                room_name=args.fixed_camera_room,
                output_dir=scenario_dir,
                field_view=args.fixed_camera_fov,
                height_ratio=args.fixed_camera_height_ratio,
            )
            # render_script 要求 camera_mode 是字符串列表，场景相机 id 也按字符串传入。
            args.camera_mode = [str(camera_index)]
        script = build_bedroom_walk_script(graph)
        render(comm, script, scenario_dir, args.scenario, args)
    elif args.scenario == "fall_lie_ble":
        render_with_fallbacks(
            comm=comm,
            script_candidates=[
                ("lie_attempt", build_fall_lie_script(graph)),
                ("sit_fallback", build_fall_sit_fallback_script(graph)),
            ],
            output_dir=scenario_dir,
            final_prefix=args.scenario,
            args=args,
        )
    else:
        raise ValueError(f"unknown scenario: {args.scenario}")

    if args.scenario != "bedroom_walk_light":
        write_placeholder_contracts(args.scenario, scenario_dir)
    print(f"Outputs written to: {scenario_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VirtualHome API natural character motion demo")
    parser.add_argument("--scenario", choices=["bedroom_walk_light", "fall_lie_ble"], default="bedroom_walk_light")
    parser.add_argument("--simulator-path", type=Path, default=None, help="Path to VirtualHome.exe")
    parser.add_argument("--attach", action="store_true", help="Attach to an already running simulator/editor")
    parser.add_argument("--port", default="8080")
    parser.add_argument("--timeout-wait", type=int, default=30)
    parser.add_argument("--scene-id", type=int, default=0)
    parser.add_argument("--character", default="Chars/Female2")
    parser.add_argument("--initial-room", default="livingroom", choices=["kitchen", "bedroom", "livingroom", "bathroom"])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--camera-mode", nargs="+", default=["AUTO"])
    parser.add_argument("--no-fixed-room-camera", dest="fixed_room_camera", action="store_false")
    parser.set_defaults(fixed_room_camera=True)
    parser.add_argument("--fixed-camera-room", default="bedroom")
    parser.add_argument("--fixed-camera-fov", type=float, default=58.0)
    parser.add_argument("--fixed-camera-height-ratio", type=float, default=0.38)
    parser.add_argument("--time-scale", type=float, default=1.35)
    parser.add_argument("--processing-time-limit", type=int, default=60)
    parser.add_argument("--jpg-quality", type=int, default=95)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    comm = None
    try:
        comm = connect(args)
        connected = comm.check_connection()
        print(f"Communication link: {connected}")
        if not connected:
            raise RuntimeError("VirtualHome simulator did not respond")
        run_scenario(comm, args)
    finally:
        if comm is not None and not args.attach:
            comm.close()


if __name__ == "__main__":
    main()
