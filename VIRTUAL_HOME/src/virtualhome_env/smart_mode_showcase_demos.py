"""
生成 04/07 两个模式联动样本：

04 普通模式：宠物一直在厨房，主人离开后，YOLO 替代结果变成
person_count=0 + pet_count=1，agent 占位反馈触发告警并关闭厨房灯。

07 离家模式：系统状态为 away_mode，陌生人进入后触发安防告警和手机通知。

这些视频是展示层样本，目标是稳定输出 1280x720 / 10fps MP4、逐帧 JPG、
视觉检测 JSONL、VirtualHome feedback JSONL 和手机/BLE 占位 JSONL。
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from scripted_showcase_demos import (
    PANEL_OUTPUT_DIR,
    REPO_ROOT,
    ROOM_CAMERA_DIR,
    draw_panel,
    read_image,
    relative_path,
    smoothstep,
    write_demo_outputs,
)


DEFAULT_PERSON_FRAME_DIR = PANEL_OUTPUT_DIR / "virtualhome_api_motion" / "bedroom_walk_light" / "jpg" / "bedroom"
DEFAULT_PET_FRAME_DIR = PANEL_OUTPUT_DIR / "virtualhome_api_pet" / "kitchen_pet" / "jpg" / "kitchen"
DEFAULT_AWAY_BACKGROUND = ROOM_CAMERA_DIR / "full_scene_overview_normal.png"


@dataclass(frozen=True)
class Cutout:
    image: np.ndarray
    alpha: np.ndarray
    source_bbox: List[int]


def read_background_cover(path: Path, width: int, height: int) -> np.ndarray:
    """按 cover 方式缩放背景，避免 4:3 截图直接拉伸成 16:9。"""
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"background not found or unreadable: {path}")
    src_h, src_w = image.shape[:2]
    scale = max(width / src_w, height / src_h)
    resized = cv2.resize(image, (int(round(src_w * scale)), int(round(src_h * scale))), interpolation=cv2.INTER_CUBIC)
    top = max(0, (resized.shape[0] - height) // 2)
    left = max(0, (resized.shape[1] - width) // 2)
    return resized[top : top + height, left : left + width].copy()


def sorted_frame_paths(frame_dir: Path) -> List[Path]:
    paths = sorted(frame_dir.glob("frame_*.jpg"))
    if paths:
        return paths
    return sorted(frame_dir.rglob("*_normal.png"))


def changed_bbox_and_mask(
    background: np.ndarray,
    frame: np.ndarray,
    min_area: int,
    min_height: int,
) -> Tuple[Optional[List[int]], Optional[np.ndarray]]:
    diff = cv2.absdiff(background, frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    _, mask = cv2.threshold(gray, 26, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    num_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    best: Optional[Tuple[float, int, int, int, int, int]] = None
    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < min_area or h < min_height:
            continue
        aspect = h / max(1, w)
        vertical_bonus = 1.35 if aspect > 1.05 else 1.0
        score = float(area) * vertical_bonus
        if best is None or score > best[0]:
            best = (score, int(x), int(y), int(w), int(h), int(label))

    if best is None:
        return None, None

    _score, x, y, w, h, label = best
    component = np.zeros_like(mask)
    component[labels == label] = 255
    x0 = max(0, x - 10)
    y0 = max(0, y - 10)
    x1 = min(frame.shape[1], x + w + 10)
    y1 = min(frame.shape[0], y + h + 10)
    return [x0, y0, x1, y1], component


def load_person_cutouts(frame_dir: Path, width: int, height: int) -> List[Cutout]:
    paths = sorted_frame_paths(frame_dir)
    if len(paths) < 2:
        raise FileNotFoundError(f"person walk frames are missing: {frame_dir}")

    background = read_image(paths[0], width, height)
    cutouts: List[Cutout] = []
    for path in paths[8:220:3]:
        frame = read_image(path, width, height)
        bbox, mask = changed_bbox_and_mask(background, frame, min_area=1500, min_height=80)
        if bbox is None or mask is None:
            continue
        x0, y0, x1, y1 = bbox
        crop = frame[y0:y1, x0:x1].copy()
        alpha = mask[y0:y1, x0:x1].copy()
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)), iterations=2)
        alpha = cv2.dilate(alpha, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)
        alpha = cv2.GaussianBlur(alpha, (9, 9), 0)
        if crop.size == 0 or alpha.mean() < 8:
            continue
        cutouts.append(Cutout(crop, alpha, bbox))

    if not cutouts:
        raise RuntimeError("could not extract a VirtualHome character cutout from bedroom walk frames")
    return cutouts


def paste_cutout(
    frame: np.ndarray,
    cutout: Cutout,
    foot_x: float,
    foot_y: float,
    target_height: int,
    flip: bool = False,
) -> Optional[List[int]]:
    image = cutout.image
    alpha = cutout.alpha
    if flip:
        image = cv2.flip(image, 1)
        alpha = cv2.flip(alpha, 1)

    scale = target_height / max(1, image.shape[0])
    target_width = max(8, int(round(image.shape[1] * scale)))
    resized_image = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)
    resized_alpha = cv2.resize(alpha, (target_width, target_height), interpolation=cv2.INTER_AREA)

    x0 = int(round(foot_x - target_width / 2))
    y0 = int(round(foot_y - target_height))
    x1 = x0 + target_width
    y1 = y0 + target_height

    dst_x0 = max(0, x0)
    dst_y0 = max(0, y0)
    dst_x1 = min(frame.shape[1], x1)
    dst_y1 = min(frame.shape[0], y1)
    if dst_x0 >= dst_x1 or dst_y0 >= dst_y1:
        return None

    src_x0 = dst_x0 - x0
    src_y0 = dst_y0 - y0
    src_x1 = src_x0 + (dst_x1 - dst_x0)
    src_y1 = src_y0 + (dst_y1 - dst_y0)

    roi = frame[dst_y0:dst_y1, dst_x0:dst_x1]
    fg = resized_image[src_y0:src_y1, src_x0:src_x1]
    a = (resized_alpha[src_y0:src_y1, src_x0:src_x1].astype(np.float32) / 255.0)[:, :, None]
    roi[:] = np.clip(roi.astype(np.float32) * (1.0 - a) + fg.astype(np.float32) * a, 0, 255).astype(np.uint8)
    return [dst_x0, dst_y0, dst_x1, dst_y1]


def apply_kitchen_light_off(frame: np.ndarray, strength: float = 0.58) -> np.ndarray:
    """当前 04 使用厨房单摄像头，因此关灯效果只作用在这一路厨房画面。"""
    dark = cv2.convertScaleAbs(frame, alpha=0.42, beta=0)
    cool = np.zeros_like(dark)
    cool[:, :, 0] = 26
    dark = cv2.addWeighted(dark, 0.92, cool, 0.08, 0)
    return cv2.addWeighted(frame, 1.0 - strength, dark, strength, 0)


def detect_pet_bbox(empty_kitchen: np.ndarray, pet_kitchen: np.ndarray) -> List[int]:
    bbox, _mask = changed_bbox_and_mask(empty_kitchen, pet_kitchen, min_area=90, min_height=12)
    return bbox or [280, 420, 390, 500]


def draw_corner_marks(frame: np.ndarray, bbox: Sequence[int], color: Tuple[int, int, int], label: str) -> None:
    x0, y0, x1, y1 = [int(v) for v in bbox]
    cv2.rectangle(frame, (x0, y0), (x1, y1), color, 2)
    cv2.putText(frame, label, (x0, max(28, y0 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, color, 2)


def build_kitchen_pet_owner_leave_demo(
    output_dir: Path,
    pet_frame_dir: Path,
    person_frame_dir: Path,
    fps: int,
    width: int,
    height: int,
    duration: float,
    jpg_quality: int,
) -> Dict[str, Path]:
    empty_path = pet_frame_dir / "frame_000000.jpg"
    pet_path = pet_frame_dir / "frame_000020.jpg"
    if not empty_path.exists() or not pet_path.exists():
        raise FileNotFoundError(
            "04 需要先生成 VirtualHome 真实宠物模型帧：运行 demo/virtualhome/11_generate_kitchen_pet_alert.bat"
        )

    empty = read_image(empty_path, width, height)
    pet_base = read_image(pet_path, width, height)
    pet_bbox = detect_pet_bbox(empty, pet_base)
    person_cutouts = load_person_cutouts(person_frame_dir, width, height)

    total_frames = int(round(duration * fps))
    exit_start = int(round(4.1 * fps))
    exit_end = int(round(6.2 * fps))
    alert_frame = min(total_frames - 1, exit_end + int(round(0.5 * fps)))

    raw_frames: List[np.ndarray] = []
    display_frames: List[np.ndarray] = []
    external_rows: List[Dict[str, object]] = []
    feedback_rows: List[Dict[str, object]] = []
    bluetooth_rows: List[Dict[str, object]] = []
    feedback_sent = False

    for frame_index in range(total_frames):
        timestamp = round(frame_index / fps, 3)
        light_off = frame_index >= alert_frame
        raw = pet_base.copy()
        person_bbox: Optional[List[int]] = None

        if frame_index < exit_end:
            if frame_index < int(1.4 * fps):
                progress = smoothstep(frame_index / max(1.0, 1.4 * fps))
                foot_x = 1288 - 300 * progress
            elif frame_index < exit_start:
                foot_x = 988 + math.sin(frame_index * 0.22) * 18
            else:
                progress = smoothstep((frame_index - exit_start) / max(1, exit_end - exit_start))
                foot_x = 988 + 332 * progress
            foot_y = 650 + math.sin(frame_index * 0.16) * 3
            cutout = person_cutouts[(frame_index * 2) % len(person_cutouts)]
            person_bbox = paste_cutout(raw, cutout, foot_x=foot_x, foot_y=foot_y, target_height=250, flip=True)

        if light_off:
            raw = apply_kitchen_light_off(raw)

        person_count = 1 if person_bbox is not None else 0
        event = "owner_present_pet_supervised" if person_count else "kitchen_unmanned_pet_present"
        if frame_index == 0:
            event = "owner_entered_kitchen"
        if exit_start <= frame_index < exit_end:
            event = "owner_leaving_kitchen"
        if light_off:
            event = "pet_unattended_alert_light_off"

        detections: List[Dict[str, object]] = [
            {"label": "cat", "class_id": 15, "confidence": 0.88, "bbox_xyxy": pet_bbox}
        ]
        if person_bbox is not None:
            detections.append({"label": "person", "class_id": 0, "confidence": 0.90, "bbox_xyxy": person_bbox})

        external_rows.append(
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "scene": "kitchen_pet",
                "room": "kitchen",
                "stream_id": "kitchen_camera_0",
                "frame_index": frame_index,
                "timestamp": timestamp,
                "smart_home_mode": "normal",
                "person_count": person_count,
                "pet_type": "cat",
                "pet_count": 1,
                "room_occupied": person_count > 0,
                "kitchen_light": "off" if light_off else "on",
                "event": event,
                "detections": detections,
            }
        )

        if light_off and not feedback_sent:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "kitchen_pet",
                    "room": "kitchen",
                    "timestamp": timestamp,
                    "action": "raise_alert_and_set_light",
                    "target": "kitchen_pet_guard_and_light",
                    "value": "alert_on_light_off",
                    "reason": "normal_mode_person_count=0_pet_count=1",
                    "payload": {
                        "mode": "normal",
                        "alert": "pet_unattended_in_kitchen",
                        "set_light": {"target": "kitchen_ceiling_light", "value": "off"},
                        "agent_interface": "placeholder_feedback_jsonl",
                    },
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
                    "payload": {
                        "title": "厨房宠物告警",
                        "message": "普通模式下厨房无人，但检测到猫仍在厨房，已关闭厨房灯并发出提醒。",
                        "mode": "normal",
                        "pet_type": "cat",
                        "pet_count": 1,
                    },
                }
            )
            feedback_sent = True

        display = raw.copy()
        accent = (80, 240, 120) if person_count else ((40, 80, 255) if light_off else (90, 160, 190))
        draw_panel(display, 0, 0, width, 106, accent)
        cv2.putText(display, "04 Normal mode | pet in kitchen + owner leaves", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (242, 250, 255), 2)
        cv2.putText(
            display,
            f"mode=NORMAL | person_count={person_count} | pet_count=1 | kitchen_light={'OFF' if light_off else 'ON'} | frame={frame_index:04d}",
            (24, 78),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.70,
            accent,
            2,
        )
        draw_corner_marks(display, pet_bbox, (0, 186, 255), "YOLO cat")
        if person_bbox is not None:
            draw_corner_marks(display, person_bbox, (80, 240, 120), "YOLO person")
        if light_off:
            draw_panel(display, 860, 134, 392, 204, (40, 80, 255))
            cv2.putText(display, "PHONE / AGENT", (892, 176), cv2.FONT_HERSHEY_SIMPLEX, 0.74, (242, 250, 255), 2)
            cv2.putText(display, "Unmanned kitchen", (892, 218), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 230, 245), 2)
            cv2.putText(display, "cat_count=1", (892, 254), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 186, 255), 2)
            cv2.putText(display, "agent: alert + light off", (892, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (90, 180, 255), 2)

        raw_frames.append(raw)
        display_frames.append(display)

    outputs = write_demo_outputs(
        output_dir=output_dir,
        scene="kitchen_pet",
        room="kitchen",
        stream_id="kitchen_camera_0",
        raw_frames=raw_frames,
        display_frames=display_frames,
        external_rows=external_rows,
        feedback_rows=feedback_rows,
        bluetooth_rows=bluetooth_rows,
        fps=fps,
        width=width,
        height=height,
        video_name="kitchen_pet_owner_leave_alert.mp4",
        external_name="kitchen_pet_owner_leave_external_result.jsonl",
        feedback_name="kitchen_pet_owner_leave_feedback_actions.jsonl",
        bluetooth_name="kitchen_pet_owner_leave_bluetooth_actions.jsonl",
        manifest_name="kitchen_pet_owner_leave_frame_manifest.jsonl",
        metadata_name="kitchen_pet_owner_leave_metadata.json",
        jpg_quality=jpg_quality,
        note=(
            "Cat frames come from VirtualHome expand_scene real pet output. "
            "Owner motion uses VirtualHome API-rendered character cutouts from demo 03 so the showcase remains runnable without Unity source editing."
        ),
    )
    metadata_path = outputs["metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["timeline"] = {
        "mode": "normal",
        "pet_state": "cat_present_from_start",
        "owner_exit_start_frame": exit_start,
        "owner_exit_end_frame": exit_end,
        "alert_and_light_off_frame": alert_frame,
    }
    metadata["sources"] = {
        "real_pet_frame": relative_path(pet_path),
        "empty_kitchen_frame": relative_path(empty_path),
        "person_walk_frames": relative_path(person_frame_dir),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return outputs


def build_away_mode_stranger_demo(
    output_dir: Path,
    background_path: Path,
    person_frame_dir: Path,
    fps: int,
    width: int,
    height: int,
    duration: float,
    jpg_quality: int,
) -> Dict[str, Path]:
    base = read_background_cover(background_path, width, height)
    cutouts = load_person_cutouts(person_frame_dir, width, height)

    total_frames = int(round(duration * fps))
    enter_start = int(round(1.2 * fps))
    alert_frame = int(round(2.2 * fps))

    raw_frames: List[np.ndarray] = []
    display_frames: List[np.ndarray] = []
    external_rows: List[Dict[str, object]] = []
    feedback_rows: List[Dict[str, object]] = []
    bluetooth_rows: List[Dict[str, object]] = []
    feedback_sent = False

    for frame_index in range(total_frames):
        timestamp = round(frame_index / fps, 3)
        raw = base.copy()
        person_bbox: Optional[List[int]] = None

        if frame_index >= enter_start:
            progress = smoothstep((frame_index - enter_start) / max(1, total_frames - enter_start - 8))
            foot_x = 1305 - 355 * progress
            foot_y = 660 - 36 * progress
            target_height = int(round(205 + 25 * progress))
            cutout = cutouts[(frame_index * 2) % len(cutouts)]
            person_bbox = paste_cutout(raw, cutout, foot_x=foot_x, foot_y=foot_y, target_height=target_height, flip=True)

        stranger_detected = person_bbox is not None
        alarm_active = frame_index >= alert_frame and stranger_detected
        event = "away_mode_clear"
        if stranger_detected:
            event = "unknown_person_entered"
        if alarm_active:
            event = "away_mode_stranger_alert"

        detections: List[Dict[str, object]] = []
        if person_bbox is not None:
            detections.append(
                {
                    "label": "person",
                    "class_id": 0,
                    "confidence": 0.91,
                    "bbox_xyxy": person_bbox,
                    "tracking_id": "unknown_person_01",
                    "identity": "unknown",
                }
            )

        external_rows.append(
            {
                "schema": "external.security_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "scene": "away_mode_stranger",
                "room": "all_rooms",
                "stream_id": "whole_home_overview_camera",
                "frame_index": frame_index,
                "timestamp": timestamp,
                "smart_home_mode": "away",
                "person_count": 1 if stranger_detected else 0,
                "known_resident_count": 0,
                "unknown_person_count": 1 if stranger_detected else 0,
                "alarm_active": alarm_active,
                "event": event,
                "detections": detections,
            }
        )

        if alarm_active and not feedback_sent:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "away_mode_stranger",
                    "room": "all_rooms",
                    "timestamp": timestamp,
                    "action": "raise_alert",
                    "target": "home_security_alarm",
                    "value": "stranger_detected",
                    "reason": "away_mode_unknown_person_detected",
                    "payload": {
                        "mode": "away",
                        "severity": "critical",
                        "message": "away_mode_stranger_detected",
                        "agent_interface": "placeholder_feedback_jsonl",
                    },
                }
            )
            bluetooth_rows.append(
                {
                    "schema": "virtualhome.bluetooth_action.v1",
                    "scene": "away_mode_stranger",
                    "timestamp": timestamp,
                    "transport": "ble_placeholder",
                    "device_type": "mobile_phone",
                    "device_id": "phone_demo_01",
                    "action": "notify",
                    "payload": {
                        "title": "离家模式告警",
                        "message": "检测到陌生人进入住宅，已触发安防告警并通知紧急联系人。",
                        "mode": "away",
                        "unknown_person_count": 1,
                    },
                }
            )
            feedback_sent = True

        display = raw.copy()
        accent = (40, 80, 255) if alarm_active else ((80, 220, 255) if stranger_detected else (100, 145, 170))
        draw_panel(display, 0, 0, width, 108, accent)
        cv2.putText(display, "07 Away mode | unknown person intrusion", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.82, (242, 250, 255), 2)
        cv2.putText(
            display,
            f"mode=AWAY | person_count={1 if stranger_detected else 0} | unknown={1 if stranger_detected else 0} | alarm={'ON' if alarm_active else 'READY'} | frame={frame_index:04d}",
            (24, 78),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.70,
            accent,
            2,
        )
        if person_bbox is not None:
            draw_corner_marks(display, person_bbox, (60, 220, 255) if not alarm_active else (40, 80, 255), "YOLO unknown")
        if alarm_active:
            overlay = display.copy()
            cv2.rectangle(overlay, (0, 0), (width, height), (0, 0, 120), 16)
            display[:] = cv2.addWeighted(display, 0.88, overlay, 0.12, 0)
            draw_panel(display, 848, 136, 404, 224, (40, 80, 255))
            cv2.putText(display, "PHONE / SECURITY", (884, 178), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (242, 250, 255), 2)
            cv2.putText(display, "Away mode active", (884, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 230, 245), 2)
            cv2.putText(display, "Unknown person detected", (884, 256), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 180, 255), 2)
            cv2.putText(display, "agent: alarm + notify", (884, 292), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 220, 255), 2)
            cv2.putText(display, "contacts notified (placeholder)", (884, 326), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 220, 230), 1)

        raw_frames.append(raw)
        display_frames.append(display)

    outputs = write_demo_outputs(
        output_dir=output_dir,
        scene="away_mode_stranger",
        room="all_rooms",
        stream_id="whole_home_overview_camera",
        raw_frames=raw_frames,
        display_frames=display_frames,
        external_rows=external_rows,
        feedback_rows=feedback_rows,
        bluetooth_rows=bluetooth_rows,
        fps=fps,
        width=width,
        height=height,
        video_name="away_mode_stranger_alert.mp4",
        external_name="away_mode_stranger_external_result.jsonl",
        feedback_name="away_mode_stranger_feedback_actions.jsonl",
        bluetooth_name="away_mode_stranger_bluetooth_actions.jsonl",
        manifest_name="away_mode_stranger_frame_manifest.jsonl",
        metadata_name="away_mode_stranger_metadata.json",
        jpg_quality=jpg_quality,
        note=(
            "Away-mode security sample uses the whole-home VirtualHome overview plus API-rendered character cutouts. "
            "The stranger decision, alarm, phone push, and emergency-contact action are placeholders for later agent integration."
        ),
    )
    metadata_path = outputs["metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["timeline"] = {
        "mode": "away",
        "enter_start_frame": enter_start,
        "alert_frame": alert_frame,
        "alarm": "home_security_alarm",
    }
    metadata["sources"] = {
        "background": relative_path(background_path),
        "person_walk_frames": relative_path(person_frame_dir),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate smart-home mode showcase demos 04 and 07")
    parser.add_argument("--scenario", choices=["all", "kitchen_pet_owner_leave", "away_mode_stranger"], default="all")
    parser.add_argument("--pet-frame-dir", type=Path, default=DEFAULT_PET_FRAME_DIR)
    parser.add_argument("--person-frame-dir", type=Path, default=DEFAULT_PERSON_FRAME_DIR)
    parser.add_argument("--away-background", type=Path, default=DEFAULT_AWAY_BACKGROUND)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--kitchen-duration", type=float, default=9.0)
    parser.add_argument("--away-duration", type=float, default=8.0)
    parser.add_argument("--jpg-quality", type=int, default=95)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs: Dict[str, Dict[str, Path]] = {}

    if args.scenario in {"all", "kitchen_pet_owner_leave"}:
        outputs["kitchen_pet_owner_leave"] = build_kitchen_pet_owner_leave_demo(
            output_dir=PANEL_OUTPUT_DIR / "kitchen_pet_owner_leave",
            pet_frame_dir=args.pet_frame_dir,
            person_frame_dir=args.person_frame_dir,
            fps=args.fps,
            width=args.width,
            height=args.height,
            duration=args.kitchen_duration,
            jpg_quality=args.jpg_quality,
        )

    if args.scenario in {"all", "away_mode_stranger"}:
        outputs["away_mode_stranger"] = build_away_mode_stranger_demo(
            output_dir=PANEL_OUTPUT_DIR / "away_mode_stranger",
            background_path=args.away_background,
            person_frame_dir=args.person_frame_dir,
            fps=args.fps,
            width=args.width,
            height=args.height,
            duration=args.away_duration,
            jpg_quality=args.jpg_quality,
        )

    for scenario, paths in outputs.items():
        print(f"[{scenario}]")
        for name, path in paths.items():
            print(f"{name}: {path}")


if __name__ == "__main__":
    main()
