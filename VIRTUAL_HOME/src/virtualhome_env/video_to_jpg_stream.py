"""
Export a demo video into a VirtualHome-style JPG frame stream.

This is useful for archived/demo-only scenes where we keep the MP4 but still
need a 720p/10fps JPG stream contract for external YOLO/A210 integration tests.

Run:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\video_to_jpg_stream.py ^
        --video .\\outputs\\showcase_panel\\virtualhome_api_pet\\kitchen_pet\\kitchen_pet_api_detection.mp4 ^
        --jpg-dir .\\outputs\\showcase_panel\\virtualhome_api_pet\\kitchen_pet\\jpg\\kitchen ^
        --manifest .\\outputs\\showcase_panel\\virtualhome_api_pet\\kitchen_pet\\frame_manifest.jsonl ^
        --scene kitchen_pet --room kitchen --stream-id kitchen_camera_0
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import cv2


REPO_ROOT = Path(__file__).resolve().parents[2]


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def frame_message(
    jpg_path: Path,
    scene: str,
    room: str,
    stream_id: str,
    camera_id: int,
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
        "camera_id": camera_id,
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


def export_video_to_jpg_stream(
    video_path: Path,
    jpg_dir: Path,
    manifest_path: Path,
    scene: str,
    room: str,
    stream_id: str,
    camera_id: int = 0,
    width: int = 1280,
    height: int = 720,
    fps: int = 10,
    jpg_quality: int = 95,
) -> int:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise FileNotFoundError(f"could not open video: {video_path}")

    jpg_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with manifest_path.open("w", encoding="utf-8") as manifest:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

            jpg_path = jpg_dir / f"frame_{count:06d}.jpg"
            cv2.imwrite(str(jpg_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality])
            manifest.write(
                json.dumps(
                    frame_message(jpg_path, scene, room, stream_id, camera_id, count, fps, width, height),
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1

    capture.release()
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a demo video to JPG frame stream")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--jpg-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--stream-id", required=True)
    parser.add_argument("--camera-id", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--jpg-quality", type=int, default=95)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = export_video_to_jpg_stream(
        video_path=args.video,
        jpg_dir=args.jpg_dir,
        manifest_path=args.manifest,
        scene=args.scene,
        room=args.room,
        stream_id=args.stream_id,
        camera_id=args.camera_id,
        width=args.width,
        height=args.height,
        fps=args.fps,
        jpg_quality=args.jpg_quality,
    )
    print(f"exported {count} JPG frames")


if __name__ == "__main__":
    main()
