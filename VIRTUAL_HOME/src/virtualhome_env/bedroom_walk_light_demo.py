"""
Generate a Python-panel bedroom walk-in/walk-out light-off demo.

This is a VirtualHome-side presentation substitute while Unity Editor scene
editing is not ready:
- use a clean VirtualHome bedroom frame as the background;
- extract the official VirtualHome character from an existing frame;
- move the character smoothly through the room;
- save clean 720p/10fps JPG frames for YOLO/A210 input;
- save a visualization MP4 with a YOLO tracking box and light state;
- write JSONL logs for detections and external feedback actions.

Run:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\bedroom_walk_light_demo.py
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = REPO_ROOT / "assets" / "demo_sources"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "showcase_panel" / "bedroom_walk_light"
DEFAULT_BACKGROUND = DEFAULT_SOURCE_DIR / "bedroom_empty_720p.jpg"
DEFAULT_PERSON_FRAME = DEFAULT_SOURCE_DIR / "bedroom_character_source_720p.jpg"


@dataclass
class DetectionRecord:
    schema: str
    scene: str
    room: str
    stream_id: str
    frame_index: int
    timestamp: float
    source: str
    person_count: int
    detections: List[Dict[str, object]]


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


def extract_character_rgba(background: np.ndarray, person_frame: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    diff = cv2.absdiff(background, person_frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 18, 255, cv2.THRESH_BINARY)

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if num_labels <= 1:
        raise RuntimeError("could not extract the character from source frames")

    # Prefer a person-sized component near the center floor area.
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
    alpha = mask[y0:y1, x0:x1].copy()
    alpha = cv2.GaussianBlur(alpha, (7, 7), 0)

    rgba = cv2.cvtColor(crop, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    return rgba, (x0, y0, x1, y1)


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def interpolate(a: float, b: float, progress: float) -> float:
    return a + (b - a) * smoothstep(progress)


def character_pose(timestamp: float) -> Optional[Tuple[float, float, float]]:
    """Return bottom-center x, bottom y, and scale for the character."""
    if timestamp < 0.8:
        return None
    if timestamp < 2.7:
        progress = (timestamp - 0.8) / 1.9
        x = interpolate(980, 555, progress)
        bottom = interpolate(545, 590, progress)
        scale = interpolate(0.78, 1.0, progress)
        return x, bottom, scale
    if timestamp < 4.2:
        idle = math.sin(timestamp * math.pi * 2.0) * 2.0
        return 555 + idle, 590, 1.0
    if timestamp < 6.1:
        progress = (timestamp - 4.2) / 1.9
        x = interpolate(555, 1010, progress)
        bottom = interpolate(590, 548, progress)
        scale = interpolate(1.0, 0.76, progress)
        return x, bottom, scale
    return None


def light_level(timestamp: float, light_off_time: float = 6.2, fade_seconds: float = 0.8) -> float:
    if timestamp < light_off_time:
        return 1.0
    progress = smoothstep((timestamp - light_off_time) / fade_seconds)
    return 1.0 - progress * 0.58


def overlay_rgba(frame: np.ndarray, rgba: np.ndarray, bottom_center_x: float, bottom_y: float, scale: float) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
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

    bbox = character_visible_bbox(patch[:, :, 3], clip_x0, clip_y0)
    return frame, bbox


def character_visible_bbox(alpha: np.ndarray, offset_x: int, offset_y: int) -> Tuple[int, int, int, int]:
    ys, xs = np.where(alpha > 35)
    if len(xs) == 0 or len(ys) == 0:
        return (0, 0, 0, 0)
    return (
        int(xs.min() + offset_x),
        int(ys.min() + offset_y),
        int(xs.max() + offset_x),
        int(ys.max() + offset_y),
    )


def apply_light(frame: np.ndarray, level: float) -> np.ndarray:
    if level >= 0.999:
        return frame
    dark = np.clip(frame.astype(np.float32) * level, 0, 255).astype(np.uint8)
    cool_overlay = np.zeros_like(dark)
    cool_overlay[:, :, 0] = 24
    return cv2.addWeighted(dark, 0.92, cool_overlay, 0.08, 0)


def draw_visualization(frame: np.ndarray, record: DetectionRecord, light_state: str, feedback_sent: bool) -> np.ndarray:
    canvas = frame.copy()
    for item in record.detections:
        x0, y0, x1, y1 = item["bbox_xyxy"]
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (60, 235, 80), 3)
        cv2.putText(canvas, "YOLO person", (x0, max(28, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (60, 235, 80), 2)

    panel_h = 92
    cv2.rectangle(canvas, (0, 0), (1280, panel_h), (18, 22, 28), -1)
    cv2.putText(
        canvas,
        "Bedroom safety demo | 720p JPG stream @ 10fps",
        (24, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.86,
        (245, 245, 245),
        2,
    )
    info = f"YOLO person_count={record.person_count} | light={light_state}"
    if feedback_sent:
        info += " | feedback: set_light(off)"
    cv2.putText(canvas, info, (24, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.74, (115, 210, 255), 2)
    return canvas


def write_jsonl(path: Path, rows: List[object]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            if hasattr(row, "__dataclass_fields__"):
                payload = asdict(row)
            else:
                payload = row
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def generate_demo(
    background_path: Path,
    person_frame_path: Path,
    output_dir: Path,
    fps: int = 10,
    duration: float = 7.5,
    jpg_quality: int = 95,
) -> Dict[str, Path]:
    if fps < 10:
        raise ValueError("this showcase demo is defined for at least 10fps")

    output_dir.mkdir(parents=True, exist_ok=True)
    jpg_dir = output_dir / "jpg" / "bedroom"
    jpg_dir.mkdir(parents=True, exist_ok=True)

    background = read_image(background_path)
    person_frame = read_image(person_frame_path)
    character_rgba, source_bbox = extract_character_rgba(background, person_frame)

    video_path = output_dir / "bedroom_natural_walk_light_off.mp4"
    detections_path = output_dir / "bedroom_natural_walk_yolo_detections.jsonl"
    actions_path = output_dir / "bedroom_natural_walk_feedback_actions.jsonl"
    manifest_path = output_dir / "bedroom_natural_walk_frame_manifest.jsonl"
    metadata_path = output_dir / "bedroom_natural_walk_metadata.json"

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, fps, (1280, 720))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {video_path}")

    detections: List[DetectionRecord] = []
    actions: List[FeedbackActionRecord] = []
    manifest: List[FrameManifestRecord] = []

    total_frames = int(round(duration * fps))
    light_off_sent = False
    light_off_time = 6.2

    for frame_index in range(total_frames):
        timestamp = round(frame_index / fps, 3)
        frame = background.copy()
        pose = character_pose(timestamp)
        bbox = (0, 0, 0, 0)
        if pose is not None:
            x, bottom, scale = pose
            bob = math.sin(timestamp * math.pi * 5.2) * 2.8
            frame, bbox = overlay_rgba(frame, character_rgba, x, bottom + bob, scale)

        level = light_level(timestamp, light_off_time=light_off_time)
        frame = apply_light(frame, level)
        light_state = "on" if level > 0.74 else "off"

        detections_for_frame: List[Dict[str, object]] = []
        if bbox != (0, 0, 0, 0):
            x0, y0, x1, y1 = bbox
            detections_for_frame.append(
                {
                    "label": "person",
                    "class_id": 0,
                    "confidence": 0.93,
                    "bbox_xyxy": [x0, y0, x1, y1],
                }
            )

        record = DetectionRecord(
            schema="external.vision_result.v1",
            scene="bedroom_natural_walk_light_off",
            room="bedroom",
            stream_id="bedroom_camera_0",
            frame_index=frame_index,
            timestamp=timestamp,
            source="scripted_yolo_tracking_from_virtualhome_character",
            person_count=len(detections_for_frame),
            detections=detections_for_frame,
        )
        detections.append(record)

        if not light_off_sent and timestamp >= light_off_time:
            actions.append(
                FeedbackActionRecord(
                    schema="virtualhome.feedback.v1",
                    source="external_agent_placeholder",
                    scene="bedroom_natural_walk_light_off",
                    room="bedroom",
                    timestamp=timestamp,
                    action="set_light",
                    target="bedroom_ceiling_light",
                    value="off",
                    reason="person_count changed from 1 to 0",
                )
            )
            light_off_sent = True

        jpg_path = jpg_dir / f"frame_{frame_index:06d}.jpg"
        cv2.imwrite(str(jpg_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
        manifest.append(
            FrameManifestRecord(
                schema="virtualhome.frame.v1",
                stream_id="bedroom_camera_0",
                scene="bedroom_natural_walk_light_off",
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

        visual = draw_visualization(frame, record, light_state, light_off_sent)
        writer.write(visual)

    writer.release()
    write_jsonl(detections_path, detections)
    write_jsonl(actions_path, actions)
    write_jsonl(manifest_path, manifest)

    metadata = {
        "schema": "virtualhome.showcase_metadata.v1",
        "scene": "bedroom_natural_walk_light_off",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resolution": [1280, 720],
        "fps": fps,
        "duration_seconds": duration,
        "source_background": str(background_path.relative_to(REPO_ROOT)),
        "source_person_frame": str(person_frame_path.relative_to(REPO_ROOT)),
        "source_person_bbox_xyxy": [int(value) for value in source_bbox],
        "outputs": {
            "video": str(video_path.relative_to(REPO_ROOT)),
            "jpg_dir": str(jpg_dir.relative_to(REPO_ROOT)),
            "detections": str(detections_path.relative_to(REPO_ROOT)),
            "feedback_actions": str(actions_path.relative_to(REPO_ROOT)),
            "frame_manifest": str(manifest_path.relative_to(REPO_ROOT)),
        },
        "note": "Python-only display substitute. Unity Editor should replace this with true character animation later.",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "video": video_path,
        "jpg_dir": jpg_dir,
        "detections": detections_path,
        "feedback_actions": actions_path,
        "frame_manifest": manifest_path,
        "metadata": metadata_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Python-panel bedroom walk/light-off demo")
    parser.add_argument("--background", type=Path, default=DEFAULT_BACKGROUND)
    parser.add_argument("--person-frame", type=Path, default=DEFAULT_PERSON_FRAME)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--duration", type=float, default=7.5)
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
