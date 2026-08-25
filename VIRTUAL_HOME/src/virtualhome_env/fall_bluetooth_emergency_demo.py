"""
生成“跌倒检测 + 蓝牙手表/手机应急联动”展示 demo。

这个脚本只负责 VirtualHome 展示侧：
- 生成 1280x720 / 10fps 的视频；
- 同步导出逐帧 JPG，作为 YOLO/A210 的输入替代；
- 写出视觉检测结果、蓝牙联动事件、VirtualHome 反馈动作 JSONL；
- 不真实拨号、不真实发短信，避免误触发真实联系人。

Run:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\fall_bluetooth_emergency_demo.py
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = REPO_ROOT / "assets" / "demo_sources"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "showcase_panel" / "fall_bluetooth_emergency"
DEFAULT_BACKGROUND = DEFAULT_SOURCE_DIR / "bedroom_empty_720p.jpg"
DEFAULT_PERSON_FRAME = DEFAULT_SOURCE_DIR / "bedroom_character_source_720p.jpg"


@dataclass
class FallDetectionRecord:
    schema: str
    scene: str
    room: str
    stream_id: str
    frame_index: int
    timestamp: float
    source: str
    person_count: int
    fall_detected: bool
    fall_confidence: float
    posture: str
    detections: List[Dict[str, object]]


@dataclass
class BluetoothActionRecord:
    schema: str
    scene: str
    timestamp: float
    transport: str
    device_type: str
    device_id: str
    action: str
    payload: Dict[str, object]


@dataclass
class FeedbackActionRecord:
    schema: str
    source: str
    scene: str
    room: str
    timestamp: float
    action: str
    target: str
    value: str
    reason: str
    payload: Dict[str, object]


@dataclass
class FrameManifestRecord:
    schema: str
    stream_id: str
    scene: str
    room: str
    camera_id: int
    frame_index: int
    timestamp: float
    resolution: List[int]
    fps: int
    image: Dict[str, str]


def ensure_720p(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    if (width, height) == (1280, 720):
        return image
    return cv2.resize(image, (1280, 720), interpolation=cv2.INTER_AREA)


def read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"image not found or unreadable: {path}")
    return ensure_720p(image)


def extract_character_rgba(background: np.ndarray, person_frame: np.ndarray) -> np.ndarray:
    """从已有 VirtualHome 截图里抠出官方人物素材，用于 Python-only 演示。"""
    diff = cv2.absdiff(background, person_frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 18, 255, cv2.THRESH_BINARY)

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if num_labels <= 1:
        raise RuntimeError("could not extract character from source frames")

    candidates = []
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < 500:
            continue
        aspect = h / max(w, 1)
        center_x = x + w / 2
        score = area
        if 420 <= center_x <= 700 and aspect > 1.4:
            score *= 2.0
        candidates.append((score, x, y, w, h))

    if not candidates:
        raise RuntimeError("no usable character component found")

    _, x, y, w, h = max(candidates, key=lambda item: item[0])
    pad = 14
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(person_frame.shape[1], x + w + pad)
    y1 = min(person_frame.shape[0], y + h + pad)

    crop = person_frame[y0:y1, x0:x1].copy()
    alpha = cv2.GaussianBlur(mask[y0:y1, x0:x1], (7, 7), 0)
    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    return rgba


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def rotate_rgba(rgba: np.ndarray, angle_degrees: float) -> np.ndarray:
    """旋转人物 RGBA，用横向姿态模拟跌倒后的地面状态。"""
    height, width = rgba.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    cos_value = abs(matrix[0, 0])
    sin_value = abs(matrix[0, 1])
    new_width = int(height * sin_value + width * cos_value)
    new_height = int(height * cos_value + width * sin_value)
    matrix[0, 2] += new_width / 2.0 - center[0]
    matrix[1, 2] += new_height / 2.0 - center[1]
    return cv2.warpAffine(rgba, matrix, (new_width, new_height), borderValue=(0, 0, 0, 0))


def overlay_rgba(
    frame: np.ndarray,
    rgba: np.ndarray,
    bottom_center_x: float,
    bottom_y: float,
    scale: float,
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    src_h, src_w = rgba.shape[:2]
    target_w = max(1, int(src_w * scale))
    target_h = max(1, int(src_h * scale))
    resized = cv2.resize(rgba, (target_w, target_h), interpolation=cv2.INTER_AREA)

    x0 = int(round(bottom_center_x - target_w / 2))
    y0 = int(round(bottom_y - target_h))
    x1 = x0 + target_w
    y1 = y0 + target_h

    frame_h, frame_w = frame.shape[:2]
    clip_x0 = max(0, x0)
    clip_y0 = max(0, y0)
    clip_x1 = min(frame_w, x1)
    clip_y1 = min(frame_h, y1)
    if clip_x0 >= clip_x1 or clip_y0 >= clip_y1:
        return frame, (0, 0, 0, 0)

    src_x0 = clip_x0 - x0
    src_y0 = clip_y0 - y0
    src_x1 = src_x0 + (clip_x1 - clip_x0)
    src_y1 = src_y0 + (clip_y1 - clip_y0)

    patch = resized[src_y0:src_y1, src_x0:src_x1]
    alpha = patch[:, :, 3:4].astype(np.float32) / 255.0
    foreground = patch[:, :, :3].astype(np.float32)
    background = frame[clip_y0:clip_y1, clip_x0:clip_x1].astype(np.float32)
    frame[clip_y0:clip_y1, clip_x0:clip_x1] = (foreground * alpha + background * (1.0 - alpha)).astype(np.uint8)

    return frame, visible_bbox(patch[:, :, 3], clip_x0, clip_y0)


def visible_bbox(alpha: np.ndarray, offset_x: int, offset_y: int) -> Tuple[int, int, int, int]:
    ys, xs = np.where(alpha > 35)
    if len(xs) == 0 or len(ys) == 0:
        return (0, 0, 0, 0)
    return (
        int(xs.min() + offset_x),
        int(ys.min() + offset_y),
        int(xs.max() + offset_x),
        int(ys.max() + offset_y),
    )


def character_state(timestamp: float) -> Tuple[float, float, float, float, str, bool, float]:
    """返回人物位置、旋转角、姿态和跌倒置信度。"""
    if timestamp < 1.4:
        idle = math.sin(timestamp * math.pi * 2.0) * 2.0
        return 555 + idle, 590, 1.0, 0.0, "standing", False, 0.05

    if timestamp < 2.5:
        progress = smoothstep((timestamp - 1.4) / 1.1)
        x = 555 + 68 * progress
        bottom = 590 + 56 * progress
        angle = 82 * progress
        confidence = 0.25 + 0.68 * progress
        return x, bottom, 1.0, angle, "falling", progress > 0.62, confidence

    confidence = 0.96 + math.sin(timestamp * 4.0) * 0.01
    return 623, 648, 0.98, 82.0, "fallen", True, confidence


def draw_glow_panel(frame: np.ndarray, x: int, y: int, w: int, h: int, color: Tuple[int, int, int]) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), (12, 18, 28), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)


def draw_visualization(
    frame: np.ndarray,
    record: FallDetectionRecord,
    bluetooth_triggered: bool,
    emergency_sent: bool,
) -> np.ndarray:
    canvas = frame.copy()

    # 视频上只画英文 HUD，避免 OpenCV 默认字体无法稳定显示中文。
    if record.detections:
        x0, y0, x1, y1 = record.detections[0]["bbox_xyxy"]
        color = (40, 60, 255) if record.fall_detected else (60, 235, 80)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 3)
        label = "YOLO fall" if record.fall_detected else "YOLO person"
        cv2.putText(canvas, label, (x0, max(28, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.72, color, 2)

    draw_glow_panel(canvas, 0, 0, 1280, 96, (72, 220, 255))
    title = "Fall emergency demo | 720p JPG stream @ 10fps | BLE watch/mobile link"
    cv2.putText(canvas, title, (24, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (242, 250, 255), 2)
    info = f"posture={record.posture} | fall={record.fall_detected} | confidence={record.fall_confidence:.2f}"
    cv2.putText(canvas, info, (24, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (110, 230, 255), 2)

    draw_glow_panel(canvas, 930, 128, 320, 170, (72, 220, 255))
    cv2.putText(canvas, "BLE DEVICES", (956, 166), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (242, 250, 255), 2)
    cv2.putText(canvas, "watch: connected", (956, 204), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (120, 240, 190), 2)
    cv2.putText(canvas, "phone: connected", (956, 238), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (120, 240, 190), 2)
    cv2.putText(canvas, "transport: BLE", (956, 272), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (110, 210, 255), 2)

    if record.fall_detected:
        draw_glow_panel(canvas, 930, 326, 320, 214, (32, 64, 255))
        cv2.putText(canvas, "EMERGENCY", (956, 365), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (90, 120, 255), 2)
        cv2.putText(canvas, "fall confirmed", (956, 404), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (245, 245, 245), 2)
        cv2.putText(canvas, "watch vibration", (956, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (120, 240, 190), 2)
        call_state = "calling contact" if emergency_sent else "call pending"
        msg_state = "sms sent" if emergency_sent else "sms pending"
        cv2.putText(canvas, call_state, (956, 476), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (110, 210, 255), 2)
        cv2.putText(canvas, msg_state, (956, 512), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (110, 210, 255), 2)
    elif bluetooth_triggered:
        cv2.putText(canvas, "waiting for fall confirmation", (956, 338), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (210, 220, 230), 2)

    return canvas


def write_jsonl(path: Path, rows: List[object]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            payload = asdict(row) if hasattr(row, "__dataclass_fields__") else row
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def generate_demo(
    background_path: Path,
    person_frame_path: Path,
    output_dir: Path,
    fps: int = 10,
    duration: float = 6.5,
    jpg_quality: int = 95,
) -> Dict[str, Path]:
    if fps < 10:
        raise ValueError("this showcase demo is defined for at least 10fps")

    output_dir.mkdir(parents=True, exist_ok=True)
    jpg_dir = output_dir / "jpg" / "bedroom"
    jpg_dir.mkdir(parents=True, exist_ok=True)

    background = read_image(background_path)
    person_frame = read_image(person_frame_path)
    character_rgba = extract_character_rgba(background, person_frame)

    video_path = output_dir / "fall_bluetooth_emergency.mp4"
    detections_path = output_dir / "fall_yolo_detections.jsonl"
    bluetooth_path = output_dir / "fall_bluetooth_actions.jsonl"
    feedback_path = output_dir / "fall_virtualhome_feedback_actions.jsonl"
    manifest_path = output_dir / "fall_frame_manifest.jsonl"
    metadata_path = output_dir / "fall_metadata.json"

    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (1280, 720))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {video_path}")

    detections: List[FallDetectionRecord] = []
    bluetooth_actions: List[BluetoothActionRecord] = []
    feedback_actions: List[FeedbackActionRecord] = []
    manifest: List[FrameManifestRecord] = []

    total_frames = int(round(duration * fps))
    bluetooth_triggered = False
    emergency_sent = False

    for frame_index in range(total_frames):
        timestamp = round(frame_index / fps, 3)
        frame = background.copy()

        x, bottom, scale, angle, posture, fall_detected, confidence = character_state(timestamp)
        pose_rgba = rotate_rgba(character_rgba, angle) if abs(angle) > 0.01 else character_rgba
        frame, bbox = overlay_rgba(frame, pose_rgba, x, bottom, scale)

        detections_for_frame: List[Dict[str, object]] = []
        if bbox != (0, 0, 0, 0):
            x0, y0, x1, y1 = bbox
            detections_for_frame.append(
                {
                    "label": "person_fall" if fall_detected else "person",
                    "class_id": 0,
                    "confidence": round(confidence, 3),
                    "bbox_xyxy": [x0, y0, x1, y1],
                    "posture": posture,
                }
            )

        record = FallDetectionRecord(
            schema="external.vision_result.v1",
            scene="fall_bluetooth_emergency",
            room="bedroom",
            stream_id="bedroom_camera_0",
            frame_index=frame_index,
            timestamp=timestamp,
            source="placeholder_yolov11_or_a210",
            person_count=1,
            fall_detected=fall_detected,
            fall_confidence=round(confidence, 3),
            posture=posture,
            detections=detections_for_frame,
        )
        detections.append(record)

        # 这里模拟“视觉确认跌倒后，边缘侧通过蓝牙通知手表和手机”。
        if fall_detected and not bluetooth_triggered and timestamp >= 2.6:
            bluetooth_actions.extend(
                [
                    BluetoothActionRecord(
                        schema="virtualhome.bluetooth_action.v1",
                        scene="fall_bluetooth_emergency",
                        timestamp=timestamp,
                        transport="ble_placeholder",
                        device_type="smart_watch",
                        device_id="watch_primary",
                        action="vibrate_and_prompt",
                        payload={
                            "prompt": "fall_detected_confirm_status",
                            "timeout_seconds": 15,
                        },
                    ),
                    BluetoothActionRecord(
                        schema="virtualhome.bluetooth_action.v1",
                        scene="fall_bluetooth_emergency",
                        timestamp=timestamp,
                        transport="ble_placeholder",
                        device_type="mobile_phone",
                        device_id="phone_primary",
                        action="prepare_emergency_contact",
                        payload={
                            "contact_group": "emergency_contacts",
                            "location_source": "virtualhome_room_context",
                        },
                    ),
                ]
            )
            bluetooth_triggered = True

        # 演示中把“无人确认 + 高置信跌倒”视为触发拨号和短信的决策结果。
        if fall_detected and not emergency_sent and timestamp >= 3.3:
            bluetooth_actions.extend(
                [
                    BluetoothActionRecord(
                        schema="virtualhome.bluetooth_action.v1",
                        scene="fall_bluetooth_emergency",
                        timestamp=timestamp,
                        transport="ble_placeholder",
                        device_type="mobile_phone",
                        device_id="phone_primary",
                        action="place_call",
                        payload={
                            "target": "emergency_contact_primary",
                            "mode": "demo_only",
                        },
                    ),
                    BluetoothActionRecord(
                        schema="virtualhome.bluetooth_action.v1",
                        scene="fall_bluetooth_emergency",
                        timestamp=round(timestamp + 0.1, 3),
                        transport="ble_placeholder",
                        device_type="mobile_phone",
                        device_id="phone_primary",
                        action="send_message",
                        payload={
                            "target": "emergency_contacts",
                            "template": "fall_detected_room_location",
                            "mode": "demo_only",
                        },
                    ),
                ]
            )
            feedback_actions.extend(
                [
                    FeedbackActionRecord(
                        schema="virtualhome.feedback.v1",
                        source="external_agent_placeholder",
                        scene="fall_bluetooth_emergency",
                        room="bedroom",
                        timestamp=timestamp,
                        action="notify_bluetooth_device",
                        target="smart_watch",
                        value="fall_alert_vibration",
                        reason="fall_confidence_above_threshold",
                        payload={"transport": "ble_placeholder", "device_id": "watch_primary"},
                    ),
                    FeedbackActionRecord(
                        schema="virtualhome.feedback.v1",
                        source="external_agent_placeholder",
                        scene="fall_bluetooth_emergency",
                        room="bedroom",
                        timestamp=timestamp,
                        action="place_call",
                        target="mobile_phone",
                        value="emergency_contact_primary",
                        reason="fall_detected_no_manual_cancel",
                        payload={"transport": "ble_placeholder", "contact": "emergency_contact_primary"},
                    ),
                    FeedbackActionRecord(
                        schema="virtualhome.feedback.v1",
                        source="external_agent_placeholder",
                        scene="fall_bluetooth_emergency",
                        room="bedroom",
                        timestamp=timestamp,
                        action="send_message",
                        target="mobile_phone",
                        value="sms_to_emergency_contacts",
                        reason="fall_detected_no_manual_cancel",
                        payload={
                            "transport": "ble_placeholder",
                            "template": "fall_detected_room_location",
                            "room": "bedroom",
                        },
                    ),
                ]
            )
            emergency_sent = True

        jpg_path = jpg_dir / f"frame_{frame_index:06d}.jpg"
        cv2.imwrite(str(jpg_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
        manifest.append(
            FrameManifestRecord(
                schema="virtualhome.frame.v1",
                stream_id="bedroom_camera_0",
                scene="fall_bluetooth_emergency",
                room="bedroom",
                camera_id=0,
                frame_index=frame_index,
                timestamp=timestamp,
                resolution=[1280, 720],
                fps=fps,
                image={
                    "encoding": "jpg",
                    "mime": "image/jpeg",
                    "path": str(jpg_path.relative_to(REPO_ROOT)),
                },
            )
        )

        writer.write(draw_visualization(frame, record, bluetooth_triggered, emergency_sent))

    writer.release()
    write_jsonl(detections_path, detections)
    write_jsonl(bluetooth_path, bluetooth_actions)
    write_jsonl(feedback_path, feedback_actions)
    write_jsonl(manifest_path, manifest)

    metadata = {
        "schema": "virtualhome.showcase_metadata.v1",
        "scene": "fall_bluetooth_emergency",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resolution": [1280, 720],
        "fps": fps,
        "duration_seconds": duration,
        "outputs": {
            "video": str(video_path.relative_to(REPO_ROOT)),
            "jpg_dir": str(jpg_dir.relative_to(REPO_ROOT)),
            "detections": str(detections_path.relative_to(REPO_ROOT)),
            "bluetooth_actions": str(bluetooth_path.relative_to(REPO_ROOT)),
            "feedback_actions": str(feedback_path.relative_to(REPO_ROOT)),
            "frame_manifest": str(manifest_path.relative_to(REPO_ROOT)),
        },
        "note": "Demo-only BLE/call/SMS actions. Real devices must be connected by an external module.",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "video": video_path,
        "jpg_dir": jpg_dir,
        "detections": detections_path,
        "bluetooth_actions": bluetooth_path,
        "feedback_actions": feedback_path,
        "frame_manifest": manifest_path,
        "metadata": metadata_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate fall/BLE emergency showcase demo")
    parser.add_argument("--background", type=Path, default=DEFAULT_BACKGROUND)
    parser.add_argument("--person-frame", type=Path, default=DEFAULT_PERSON_FRAME)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--duration", type=float, default=6.5)
    parser.add_argument("--jpg-quality", type=int, default=95)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = generate_demo(
        background_path=args.background,
        person_frame_path=args.person_frame,
        output_dir=args.output_dir,
        fps=args.fps,
        duration=args.duration,
        jpg_quality=args.jpg_quality,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
