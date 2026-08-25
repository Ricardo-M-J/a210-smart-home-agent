"""
生成补充展示 demo：火灾烟雾报警、健康助手联动。

这些 demo 只负责 VirtualHome 展示侧和接口占位：
- 输出 1280x720 / 10fps MP4；
- 同步输出逐帧 JPG，给 YOLO/A210 作为图像流替代输入；
- 同步输出 external result、VirtualHome feedback、BLE action JSONL；
- 不连接真实蓝牙设备，不真实拨号，不真实发短信。

Run:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\scripted_showcase_demos.py --scenario all
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOM_CAMERA_DIR = REPO_ROOT / "outputs" / "room_cameras"
PANEL_OUTPUT_DIR = REPO_ROOT / "outputs" / "showcase_panel"
MUSIC_DIR = REPO_ROOT / "assets" / "music"
DEFAULT_KITCHEN = ROOM_CAMERA_DIR / "kitchen_normal.png"
DEFAULT_BEDROOM_WITH_PERSON = REPO_ROOT / "assets" / "demo_sources" / "bedroom_character_source_720p.jpg"
HEALTH_MUSIC_START = 8.0
HEALTH_MUSIC_END = 38.0


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def read_image(path: Path, width: int, height: int) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"image not found or unreadable: {path}")
    if image.shape[1] != width or image.shape[0] != height:
        image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    return image


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def write_jsonl(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def frame_manifest_row(
    jpg_path: Path,
    scene: str,
    room: str,
    stream_id: str,
    frame_index: int,
    fps: int,
    width: int,
    height: int,
) -> Dict[str, object]:
    return {
        "schema": "virtualhome.frame.v1",
        "stream_id": stream_id,
        "scene": scene,
        "room": room,
        "camera_id": 0,
        "frame_index": frame_index,
        "timestamp": round(frame_index / fps, 3),
        "resolution": [width, height],
        "fps": fps,
        "image": {
            "encoding": "jpg",
            "mime": "image/jpeg",
            "path": relative_path(jpg_path),
        },
    }


def alpha_blend_overlay(frame: np.ndarray, overlay: np.ndarray, alpha: float) -> np.ndarray:
    alpha = min(1.0, max(0.0, alpha))
    return cv2.addWeighted(frame, 1.0 - alpha, overlay, alpha, 0)


def draw_panel(frame: np.ndarray, x: int, y: int, w: int, h: int, accent: Tuple[int, int, int]) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), (12, 19, 28), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), accent, 2)


def write_demo_outputs(
    output_dir: Path,
    scene: str,
    room: str,
    stream_id: str,
    raw_frames: List[np.ndarray],
    display_frames: List[np.ndarray],
    external_rows: List[Dict[str, object]],
    feedback_rows: List[Dict[str, object]],
    bluetooth_rows: List[Dict[str, object]],
    fps: int,
    width: int,
    height: int,
    video_name: str,
    external_name: str,
    feedback_name: str,
    bluetooth_name: str,
    manifest_name: str,
    metadata_name: str,
    jpg_quality: int,
    note: str,
) -> Dict[str, Path]:
    if fps < 10:
        raise ValueError("showcase demos are defined for at least 10fps")

    output_dir.mkdir(parents=True, exist_ok=True)
    jpg_dir = output_dir / "jpg" / room
    jpg_dir.mkdir(parents=True, exist_ok=True)

    video_path = output_dir / video_name
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {video_path}")

    manifest_rows: List[Dict[str, object]] = []
    for frame_index, (raw, display) in enumerate(zip(raw_frames, display_frames)):
        jpg_path = jpg_dir / f"frame_{frame_index:06d}.jpg"
        cv2.imwrite(str(jpg_path), raw, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
        manifest_rows.append(frame_manifest_row(jpg_path, scene, room, stream_id, frame_index, fps, width, height))
        writer.write(display)

    writer.release()

    external_path = output_dir / external_name
    feedback_path = output_dir / feedback_name
    bluetooth_path = output_dir / bluetooth_name
    manifest_path = output_dir / manifest_name
    metadata_path = output_dir / metadata_name

    write_jsonl(external_path, external_rows)
    write_jsonl(feedback_path, feedback_rows)
    write_jsonl(bluetooth_path, bluetooth_rows)
    write_jsonl(manifest_path, manifest_rows)

    metadata = {
        "schema": "virtualhome.showcase_metadata.v1",
        "scene": scene,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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
        "note": note,
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


def draw_smoke(frame: np.ndarray, timestamp: float) -> Optional[List[int]]:
    """用烟雾叠加模拟火灾烟雾报警；当前 VirtualHome Python API 没有火焰/粒子接口。"""
    if timestamp < 1.0:
        return None

    progress = smoothstep((timestamp - 1.0) / 2.0)
    overlay = frame.copy()
    center_x, center_y = 690, 265
    rng_phase = timestamp * 5.0
    for index in range(10):
        angle = index * 0.95 + rng_phase * 0.1
        radius_x = int(math.cos(angle) * 44 * progress)
        radius_y = int(math.sin(angle) * 22 * progress - index * 10 * progress)
        cloud_center = (center_x + radius_x, center_y - int(18 * index * progress) + radius_y)
        axes = (int((30 + index * 8) * progress), int((20 + index * 5) * progress))
        if axes[0] > 3 and axes[1] > 3:
            cv2.ellipse(overlay, cloud_center, axes, 0, 0, 360, (168, 176, 180), -1)

    frame[:] = alpha_blend_overlay(frame, overlay, 0.38)

    return [570, 82, 820, 335]


def build_fire_smoke_demo(
    output_dir: Path,
    background_path: Path,
    fps: int,
    width: int,
    height: int,
    duration: float,
    jpg_quality: int,
) -> Dict[str, Path]:
    background = read_image(background_path, width, height)
    raw_frames: List[np.ndarray] = []
    display_frames: List[np.ndarray] = []
    external_rows: List[Dict[str, object]] = []
    feedback_rows: List[Dict[str, object]] = []
    bluetooth_rows: List[Dict[str, object]] = []
    feedback_sent = False

    total_frames = int(round(duration * fps))
    for frame_index in range(total_frames):
        timestamp = round(frame_index / fps, 3)
        raw = background.copy()
        bbox = draw_smoke(raw, timestamp)
        detected = bbox is not None and timestamp >= 1.6

        detections = []
        if detected and bbox is not None:
            detections.append(
                {
                    "label": "fire_smoke",
                    "class_id": 9001,
                    "confidence": 0.91,
                    "bbox_xyxy": bbox,
                }
            )

        external_rows.append(
            {
                "schema": "external.vision_result.v1",
                "source": "placeholder_yolov11_or_a210",
                "scene": "fire_smoke",
                "room": "kitchen",
                "stream_id": "kitchen_camera_0",
                "frame_index": frame_index,
                "timestamp": timestamp,
                "person_count": 0,
                "hazard_detected": detected,
                "hazard_type": "fire_smoke" if detected else "none",
                "risk_level": "critical" if detected else "normal",
                "event": "fire_smoke_detected" if detected else "clear",
                "detections": detections,
            }
        )

        if detected and not feedback_sent:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "fire_smoke",
                    "room": "kitchen",
                    "timestamp": timestamp,
                    "action": "raise_alert",
                    "target": "fire_alarm",
                    "value": "fire_smoke_detected",
                    "reason": "person_count=0_and_smoke_detected",
                    "payload": {"severity": "critical", "suggested_action": "notify_and_start_fire_alarm", "transport": "ble_placeholder"},
                }
            )
            bluetooth_rows.append(
                {
                    "schema": "virtualhome.bluetooth_action.v1",
                    "scene": "fire_smoke",
                    "timestamp": timestamp,
                    "transport": "ble_placeholder",
                    "device_type": "mobile_phone",
                    "device_id": "phone_demo_01",
                    "action": "notify",
                    "payload": {
                        "title": "Fire smoke alert",
                        "hazard_type": "fire_smoke",
                        "mode": "demo_only",
                    },
                }
            )
            feedback_sent = True

        display = raw.copy()
        accent = (30, 70, 255) if detected else (90, 120, 135)
        draw_panel(display, 0, 0, width, 96, accent)
        cv2.putText(display, "Fire smoke alarm | 720p JPG stream @ 10fps", (24, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (242, 250, 255), 2)
        cv2.putText(display, f"person_count=0 | hazard={detected} | frame={frame_index:04d}", (24, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (110, 230, 255) if not detected else (90, 120, 255), 2)
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            cv2.rectangle(display, (x0, y0), (x1, y1), accent, 3)
            cv2.putText(display, "YOLO fire smoke", (x0, max(28, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.68, accent, 2)
        if feedback_sent:
            draw_panel(display, 910, 126, 340, 190, (30, 70, 255))
            cv2.putText(display, "PHONE ALERT", (940, 166), cv2.FONT_HERSHEY_SIMPLEX, 0.76, (242, 250, 255), 2)
            cv2.putText(display, "fire smoke detected", (940, 206), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (110, 210, 255), 2)
            cv2.putText(display, "agent: alarm + notify", (940, 242), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (120, 240, 190), 2)
            cv2.putText(display, "BLE placeholder only", (940, 278), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (210, 220, 230), 2)

        raw_frames.append(raw)
        display_frames.append(display)

    return write_demo_outputs(
        output_dir=output_dir,
        scene="fire_smoke",
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
        video_name="fire_smoke_alarm.mp4",
        external_name="fire_smoke_external_detections.jsonl",
        feedback_name="fire_smoke_feedback_actions.jsonl",
        bluetooth_name="fire_smoke_bluetooth_actions.jsonl",
        manifest_name="fire_smoke_frame_manifest.jsonl",
        metadata_name="fire_smoke_metadata.json",
        jpg_quality=jpg_quality,
        note="Current VirtualHome Python API has no stable fire/smoke particle effect call; this demo uses smoke-only visual overlay for end-to-end fire-smoke alarm testing.",
    )


def midi_to_hz(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def generate_relief_audio(path: Path, duration: float = 30.0, sample_rate: int = 22050) -> Path:
    """生成一个可播放的舒缓音乐占位音频，用于健康助手 demo 联动。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    chord_progression = [
        (61, 65, 68, 72),
        (58, 61, 65, 70),
        (56, 60, 63, 68),
        (53, 56, 61, 65),
        (54, 58, 61, 66),
        (56, 60, 63, 68),
    ]
    total_samples = int(duration * sample_rate)
    samples = bytearray()
    for sample_index in range(total_samples):
        t = sample_index / sample_rate
        chord = chord_progression[int(t / 5.0) % len(chord_progression)]
        local = t % 5.0
        envelope = min(1.0, local / 1.2) * min(1.0, (5.0 - local) / 1.0)
        value = 0.0
        for note_index, note in enumerate(chord):
            freq = midi_to_hz(note)
            value += math.sin(2.0 * math.pi * freq * t) * (0.18 / (note_index + 1))
            value += math.sin(2.0 * math.pi * freq * 2.0 * t) * (0.025 / (note_index + 1))
        value += math.sin(2.0 * math.pi * midi_to_hz(chord[-1] + 12) * t) * 0.025
        value *= envelope * 0.72
        samples.extend(struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767)))

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(samples))
    return path


def anxiety_state_at(timestamp: float) -> Tuple[int, float, str]:
    if timestamp < 5.0:
        return 76 + int(math.sin(timestamp * 2.0) * 2), 0.10, "normal_warm"
    if timestamp < HEALTH_MUSIC_START:
        progress = smoothstep((timestamp - 5.0) / (HEALTH_MUSIC_START - 5.0))
        heart_rate = int(78 + 40 * progress + math.sin(timestamp * 6.0) * 2)
        anxiety = 0.18 + 0.70 * progress
        return heart_rate, anxiety, "anxiety_detected" if heart_rate >= 112 else "heart_rate_rising"
    if timestamp < HEALTH_MUSIC_END:
        progress = smoothstep((timestamp - HEALTH_MUSIC_START) / (HEALTH_MUSIC_END - HEALTH_MUSIC_START))
        heart_rate = int(118 - 35 * progress + math.sin(timestamp * 2.2) * 2)
        anxiety = 0.88 - 0.65 * progress
        return heart_rate, anxiety, "relief_active"
    return 78 + int(math.sin(timestamp * 2.0) * 2), 0.12, "recovered_warm"


def apply_health_environment(frame: np.ndarray, state: str) -> np.ndarray:
    overlay = frame.copy()
    if state in {"normal_warm", "recovered_warm"}:
        overlay[:, :, 1] = np.clip(overlay[:, :, 1].astype(np.int16) + 18, 0, 255)
        overlay[:, :, 2] = np.clip(overlay[:, :, 2].astype(np.int16) + 42, 0, 255)
        return alpha_blend_overlay(frame, overlay, 0.18)
    overlay[:, :, 0] = np.clip(overlay[:, :, 0].astype(np.int16) + 54, 0, 255)
    overlay[:, :, 1] = np.clip(overlay[:, :, 1].astype(np.int16) + 8, 0, 255)
    return alpha_blend_overlay(frame, overlay, 0.30)


def draw_health_hud(
    display: np.ndarray,
    frame_index: int,
    heart_rate: int,
    anxiety_score: float,
    state: str,
) -> None:
    music_on = HEALTH_MUSIC_START <= frame_index / 10.0 < HEALTH_MUSIC_END
    recovered = state == "recovered_warm"
    warm_light = state in {"normal_warm", "recovered_warm"}
    accent = (90, 190, 255) if not warm_light else (80, 210, 245)
    if music_on:
        accent = (120, 240, 190)

    state_label = "normal" if state == "normal_warm" else "recovering"
    if state == "heart_rate_rising":
        state_label = "heart-rate rising"
    elif state == "anxiety_detected":
        state_label = "anxiety detected"
    elif state == "relief_active":
        state_label = "relief active"
    elif recovered:
        state_label = "back to normal"

    light_label = "warm" if warm_light else "cool blue"
    music_label = "ON" if music_on else "OFF"

    draw_panel(display, 0, 0, 1280, 112, accent)
    cv2.putText(display, "Health Assistant | warm -> cool light + music -> warm", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.84, (242, 250, 255), 2)
    cv2.putText(display, f"state={state_label} | HR={heart_rate} bpm | anxiety={anxiety_score:.2f} | music={music_label}", (24, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.76, accent, 2)

    draw_panel(display, 884, 136, 366, 286, accent)
    cv2.putText(display, "PHONE / AGENT", (914, 176), cv2.FONT_HERSHEY_SIMPLEX, 0.74, (242, 250, 255), 2)
    cv2.putText(display, f"Light: {light_label}", (914, 218), cv2.FONT_HERSHEY_SIMPLEX, 0.66, accent, 2)
    cv2.putText(display, f"Music: {music_label}", (914, 256), cv2.FONT_HERSHEY_SIMPLEX, 0.66, accent, 2)
    if music_on:
        cv2.putText(display, "Prompt: 4-7-8 breathing", (914, 296), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (210, 230, 245), 2)
        cv2.putText(display, "Relax shoulders and neck", (914, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (210, 230, 245), 2)
        remaining = max(0, int(HEALTH_MUSIC_END - frame_index / 10.0))
        cv2.putText(display, f"Music ends in {remaining:02d}s", (914, 366), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (120, 240, 190), 2)
    elif recovered:
        cv2.putText(display, "Prompt: heart rate normal", (914, 296), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (210, 230, 245), 2)
        cv2.putText(display, "Music stopped", (914, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (210, 230, 245), 2)
    else:
        cv2.putText(display, "Prompt: standby", (914, 296), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (210, 230, 245), 2)

    points = []
    start_x, start_y = 914, 476
    for i in range(52):
        x = start_x + i * 6
        wave = math.sin((frame_index + i) * 0.32) * 10
        spike = -28 if i % max(7, int(16 - heart_rate / 12)) == 0 else 0
        y = int(start_y + wave + spike)
        points.append((x, y))
    for a, b in zip(points, points[1:]):
        cv2.line(display, a, b, accent, 2)
    cv2.putText(display, "wearable stream placeholder", (914, 524), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (210, 220, 230), 1)


def build_health_event_demo(
    output_dir: Path,
    background_path: Path,
    fps: int,
    width: int,
    height: int,
    duration: float,
    jpg_quality: int,
) -> Dict[str, Path]:
    base = read_image(background_path, width, height)
    raw_frames: List[np.ndarray] = []
    display_frames: List[np.ndarray] = []
    external_rows: List[Dict[str, object]] = []
    feedback_rows: List[Dict[str, object]] = []
    bluetooth_rows: List[Dict[str, object]] = []
    intervention_sent = False
    recovery_sent = False
    audio_path = MUSIC_DIR / "伊藤サチコ - いつも何度でも.mp3"

    total_frames = int(round(duration * fps))
    for frame_index in range(total_frames):
        timestamp = round(frame_index / fps, 3)
        heart_rate, anxiety_score, state = anxiety_state_at(timestamp)
        raw = apply_health_environment(base.copy(), state)
        event = "anxiety_detected" if state == "anxiety_detected" else "health_monitoring"
        if state == "relief_active":
            event = "anxiety_relief_active"
        if state == "recovered_warm":
            event = "health_recovered"

        external_rows.append(
            {
                "schema": "external.health_event.v1",
                "source": "wearable_or_agent_placeholder",
                "scene": "health_event",
                "room": "bedroom",
                "stream_id": "bedroom_camera_0",
                "frame_index": frame_index,
                "timestamp": timestamp,
                "event": event,
                "payload": {
                    "heart_rate": heart_rate,
                    "anxiety_score": anxiety_score,
                    "confidence": 0.91 if state == "anxiety_detected" else 0.84,
                    "light_state": "warm" if state in {"normal_warm", "recovered_warm"} else "cool_blue",
                    "music_state": "on" if HEALTH_MUSIC_START <= timestamp < HEALTH_MUSIC_END else "off",
                },
            }
        )

        if timestamp >= HEALTH_MUSIC_START and not intervention_sent:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "health_event",
                    "room": "bedroom",
                    "timestamp": timestamp,
                    "action": "set_environment",
                    "target": "bedroom_ambient_light_and_whole_home_music",
                    "value": "anxiety_relief_mode",
                    "reason": "wearable_detected_anxiety_high_heart_rate",
                    "payload": {
                        "light": "cool_blue",
                        "music": "伊藤サチコ - いつも何度でも",
                        "music_scope": "whole_home",
                        "music_source": "health_event",
                        "music_path": relative_path(audio_path),
                        "duration_seconds": HEALTH_MUSIC_END - HEALTH_MUSIC_START,
                        "agent_message": "检测到心率升高。请跟随 4-7-8 呼吸，放松肩颈，音乐将在 30 秒后自动关闭。",
                        "agent_interface": "placeholder_feedback_jsonl",
                    },
                }
            )
            bluetooth_rows.append(
                {
                    "schema": "virtualhome.bluetooth_action.v1",
                    "scene": "health_event",
                    "timestamp": timestamp,
                    "transport": "ble_placeholder",
                    "device_type": "mobile_phone",
                    "device_id": "phone_demo_01",
                    "action": "notify",
                    "payload": {
                        "event": "anxiety_relief_started",
                        "title": "健康助手",
                        "message": "检测到心率升高。请跟随 4-7-8 呼吸，放松肩颈，音乐将在 30 秒后自动关闭。",
                        "heart_rate": heart_rate,
                        "anxiety_score": anxiety_score,
                        "mode": "demo_only",
                    },
                }
            )
            intervention_sent = True

        if timestamp >= HEALTH_MUSIC_END and not recovery_sent:
            feedback_rows.append(
                {
                    "schema": "virtualhome.feedback.v1",
                    "source": "external_agent",
                    "scene": "health_event",
                    "room": "bedroom",
                    "timestamp": timestamp,
                    "action": "set_environment",
                    "target": "bedroom_ambient_light_and_whole_home_music",
                    "value": "normal_warm_mode",
                    "reason": "heart_rate_back_to_normal_after_30s_music",
                    "payload": {
                        "light": "warm",
                        "music": "off",
                        "music_scope": "whole_home",
                        "music_source": "health_event",
                        "agent_interface": "placeholder_feedback_jsonl",
                    },
                }
            )
            bluetooth_rows.append(
                {
                    "schema": "virtualhome.bluetooth_action.v1",
                    "scene": "health_event",
                    "timestamp": timestamp,
                    "transport": "ble_placeholder",
                    "device_type": "mobile_phone",
                    "device_id": "phone_demo_01",
                    "action": "notify",
                    "payload": {
                        "event": "anxiety_relief_finished",
                        "title": "健康助手",
                        "message": "心率已回归正常，音乐关闭，灯光恢复暖色。",
                        "heart_rate": heart_rate,
                        "anxiety_score": anxiety_score,
                        "mode": "demo_only",
                    },
                }
            )
            recovery_sent = True

        display = raw.copy()
        draw_health_hud(display, frame_index, heart_rate, anxiety_score, state)
        raw_frames.append(raw)
        display_frames.append(display)

    outputs = write_demo_outputs(
        output_dir=output_dir,
        scene="health_event",
        room="bedroom",
        stream_id="bedroom_camera_0",
        raw_frames=raw_frames,
        display_frames=display_frames,
        external_rows=external_rows,
        feedback_rows=feedback_rows,
        bluetooth_rows=bluetooth_rows,
        fps=fps,
        width=width,
        height=height,
        video_name="health_assistant.mp4",
        external_name="health_event_external_events.jsonl",
        feedback_name="health_event_feedback_actions.jsonl",
        bluetooth_name="health_event_bluetooth_actions.jsonl",
        manifest_name="health_event_frame_manifest.jsonl",
        metadata_name="health_event_metadata.json",
        jpg_quality=jpg_quality,
        note="Health assistant demo with local playable audio. Real heart-rate, agent text, and phone transport should be integrated by external modules.",
    )
    outputs["audio"] = audio_path
    metadata_path = outputs["metadata"]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["outputs"]["audio"] = relative_path(audio_path)
    metadata["timeline"] = {
        "normal_warm_until_s": 5.0,
        "music_start_s": HEALTH_MUSIC_START,
        "music_end_s": HEALTH_MUSIC_END,
        "music_duration_s": HEALTH_MUSIC_END - HEALTH_MUSIC_START,
        "recovered_warm_after_s": HEALTH_MUSIC_END,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate scripted VirtualHome showcase demos")
    parser.add_argument("--scenario", choices=["all", "fire_smoke", "health_event"], default="all")
    parser.add_argument("--kitchen-background", type=Path, default=DEFAULT_KITCHEN)
    parser.add_argument("--bedroom-background", type=Path, default=DEFAULT_BEDROOM_WITH_PERSON)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--duration", type=float, default=None, help="Override both fire and health durations")
    parser.add_argument("--fire-duration", type=float, default=6.5)
    parser.add_argument("--health-duration", type=float, default=42.0)
    parser.add_argument("--jpg-quality", type=int, default=95)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs: Dict[str, Dict[str, Path]] = {}
    fire_duration = args.duration if args.duration is not None else args.fire_duration
    health_duration = args.duration if args.duration is not None else args.health_duration

    if args.scenario in {"all", "fire_smoke"}:
        outputs["fire_smoke"] = build_fire_smoke_demo(
            output_dir=PANEL_OUTPUT_DIR / "fire_smoke",
            background_path=args.kitchen_background,
            fps=args.fps,
            width=args.width,
            height=args.height,
            duration=fire_duration,
            jpg_quality=args.jpg_quality,
        )

    if args.scenario in {"all", "health_event"}:
        outputs["health_event"] = build_health_event_demo(
            output_dir=PANEL_OUTPUT_DIR / "health_event",
            background_path=args.bedroom_background,
            fps=args.fps,
            width=args.width,
            height=args.height,
            duration=health_duration,
            jpg_quality=args.jpg_quality,
        )

    for scenario, paths in outputs.items():
        print(f"[{scenario}]")
        for name, path in paths.items():
            print(f"{name}: {path}")


if __name__ == "__main__":
    main()
