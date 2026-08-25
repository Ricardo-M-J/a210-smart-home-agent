"""
Room-camera framework for the VirtualHome Unity simulator.

目标：
1. 启动或连接 VirtualHome Unity executable。
2. 查询当前户型环境图，并提取每个房间的信息。
3. 给每个房间添加一个顶视摄像头。
4. 同时从所有房间摄像头抓取画面，按目标 FPS 保存为多路视频。

运行示例：
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\room_camera_framework.py --duration 5 --fps 10

只查询环境和保存一张多房间预览图：
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\room_camera_framework.py --snapshot-only

如果模拟器 exe 不在默认位置：
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\room_camera_framework.py --simulator-path D:\\path\\to\\VirtualHome.exe
"""

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import cv2
import numpy as np
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_REPO = REPO_ROOT / "virtualhome"
DEFAULT_SIMULATOR = REPO_ROOT / "windows_exec" / "windows_exec.v2.2.4" / "VirtualHome.exe"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "room_cameras"

sys.path.insert(0, str(PACKAGE_REPO))

from virtualhome.simulation.unity_simulator import comm_unity


@dataclass
class RoomInfo:
    """从 environment_graph() 中提取出来的房间信息。"""

    room_id: int
    name: str
    center: List[float]
    size: List[float]


@dataclass
class RoomCamera:
    """一个房间对应一个 Unity 摄像头。"""

    room: RoomInfo
    camera_index: int
    position: List[float]
    rotation: List[float]
    field_view: float


def safe_filename(value: str) -> str:
    """把房间名转换成适合作为文件名的字符串。"""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value)
    return value or "room"


def parse_camera_id(message: str) -> Optional[int]:
    """从 Unity 返回的 'New camera created. Id:79' 中解析 camera id。"""
    match = re.search(r"Id:(\d+)", message or "")
    if not match:
        return None
    return int(match.group(1))


def bgr_to_rgb_image(image: np.ndarray) -> Image.Image:
    """camera_image 普通模式返回 BGR 图像，Pillow 需要 RGB。"""
    if image.ndim == 3 and image.shape[2] == 3:
        return Image.fromarray(image[:, :, ::-1])
    return Image.fromarray(image)


def build_contact_sheet(images: Dict[str, np.ndarray], tile_width: int, tile_height: int) -> Image.Image:
    """把每个房间的一帧图像拼成预览图，便于快速检查摄像头是否摆正。"""
    if not images:
        raise ValueError("No images available for contact sheet")

    labels = list(images.keys())
    columns = min(2, len(labels))
    rows = int(np.ceil(len(labels) / columns))
    label_height = 28

    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)

    for index, label in enumerate(labels):
        row = index // columns
        col = index % columns
        x = col * tile_width
        y = row * (tile_height + label_height)

        tile = bgr_to_rgb_image(images[label]).resize((tile_width, tile_height))
        sheet.paste(tile, (x, y + label_height))
        draw.text((x + 8, y + 7), label, fill=(20, 20, 20))

    return sheet


class RoomCameraFramework:
    """VirtualHome 房间摄像头框架。

    这个类把官方 API 拆成几个清楚的步骤：
    launch -> query_environment -> add_room_cameras -> capture_snapshot/capture_video。
    """

    def __init__(
        self,
        simulator_path: Path,
        output_dir: Path,
        port: str = "8080",
        timeout_wait: int = 10,
        launch_simulator: bool = True,
    ) -> None:
        self.simulator_path = simulator_path
        self.output_dir = output_dir
        self.port = port
        self.timeout_wait = timeout_wait
        self.launch_simulator = launch_simulator
        self.comm = None

    def launch(self) -> None:
        """启动 Unity executable 或连接已有模拟器，并建立 HTTP API 连接。"""
        if self.launch_simulator and not self.simulator_path.exists():
            raise FileNotFoundError(f"Simulator not found: {self.simulator_path}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.launch_simulator:
            self.comm = comm_unity.UnityCommunication(
                file_name=str(self.simulator_path),
                port=self.port,
                logging=False,
                timeout_wait=self.timeout_wait,
            )
        else:
            self.comm = comm_unity.UnityCommunication(
                port=self.port,
                timeout_wait=self.timeout_wait,
            )

        connected = self.comm.check_connection()
        print(f"Communication link: {connected}")
        if not connected:
            raise RuntimeError("Simulator did not respond to idle check")

    def close(self) -> None:
        """关闭由本框架启动的 Unity 进程。"""
        if self.comm is not None:
            self.comm.close()
            self.comm = None

    def query_environment(self) -> List[RoomInfo]:
        """查询当前环境图，并返回所有房间节点。"""
        ok, graph = self.comm.environment_graph()
        if not ok:
            raise RuntimeError("environment_graph failed")

        graph_path = self.output_dir / "environment_graph.json"
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")

        rooms = []
        for node in graph.get("nodes", []):
            if node.get("category") != "Rooms":
                continue
            bounding_box = node.get("bounding_box") or {}
            center = bounding_box.get("center")
            size = bounding_box.get("size")
            if not center or not size:
                continue
            rooms.append(
                RoomInfo(
                    room_id=node["id"],
                    name=node["class_name"],
                    center=list(center),
                    size=list(size),
                )
            )

        rooms.sort(key=lambda room: room.room_id)
        rooms_path = self.output_dir / "rooms.json"
        rooms_path.write_text(json.dumps([asdict(room) for room in rooms], indent=2), encoding="utf-8")

        print(f"environment nodes: {len(graph.get('nodes', []))}")
        print(f"environment edges: {len(graph.get('edges', []))}")
        print(f"rooms: {len(rooms)}")
        for room in rooms:
            print(f"  - {room.name} id={room.room_id} center={room.center} size={room.size}")

        return rooms

    def add_room_cameras(
        self,
        rooms: Iterable[RoomInfo],
        field_view: float = 85.0,
        height_ratio: float = 0.45,
        camera_style: str = "corner",
    ) -> List[RoomCamera]:
        """为每个房间创建一个摄像头。

        VirtualHome 的 add_camera 接受世界坐标 position 和欧拉角 rotation。
        corner: 房间角落高位俯视，更接近室内监控摄像头。
        topdown: 房间中心顶视，适合看平面布局，但容易被吊灯遮挡。
        """
        cameras = []

        for room in rooms:
            position, rotation = self.compute_room_camera_pose(
                room,
                height_ratio=height_ratio,
                camera_style=camera_style,
            )

            before_ok, before_count = self.comm.camera_count()
            if not before_ok:
                raise RuntimeError("camera_count failed before add_camera")

            ok, message = self.comm.add_camera(
                position=position,
                rotation=rotation,
                field_view=field_view,
            )
            if not ok:
                raise RuntimeError(f"add_camera failed for room {room.name}: {message}")

            camera_index = parse_camera_id(message)
            if camera_index is None:
                camera_index = before_count

            cameras.append(
                RoomCamera(
                    room=room,
                    camera_index=camera_index,
                    position=position,
                    rotation=rotation,
                    field_view=field_view,
                )
            )

            print(f"camera for {room.name}: index={camera_index}, position={position}, rotation={rotation}")

        camera_path = self.output_dir / "room_cameras.json"
        camera_path.write_text(json.dumps([asdict(camera) for camera in cameras], indent=2), encoding="utf-8")

        return cameras

    @staticmethod
    def compute_room_camera_pose(
        room: RoomInfo,
        height_ratio: float,
        camera_style: str,
    ) -> tuple[List[float], List[float]]:
        """根据房间 bounding box 计算摄像头位置和朝向。"""
        center_x, center_y, center_z = room.center
        size_x, size_y, size_z = room.size

        if camera_style == "topdown":
            position = [center_x, center_y + size_y * height_ratio, center_z]
            rotation = [90, 0, 0]
            return position, rotation

        if camera_style != "corner":
            raise ValueError(f"Unsupported camera_style: {camera_style}")

        position = [
            center_x - size_x * 0.33,
            center_y + size_y * height_ratio,
            center_z - size_z * 0.33,
        ]
        target = [center_x, center_y, center_z]

        dx = target[0] - position[0]
        dy = target[1] - position[1]
        dz = target[2] - position[2]
        horizontal = math.sqrt(dx * dx + dz * dz)

        # Unity camera forward axis is local +Z. These Euler angles point it at the room center.
        pitch = math.degrees(math.atan2(-dy, horizontal))
        yaw = math.degrees(math.atan2(dx, dz))
        rotation = [pitch, yaw, 0]

        return position, rotation

    def capture_snapshot(
        self,
        cameras: List[RoomCamera],
        mode: str,
        image_width: int,
        image_height: int,
    ) -> Dict[str, np.ndarray]:
        """一次性抓取所有房间摄像头画面。

        camera_image 支持传入 camera index 列表，因此这里是一轮请求同时拿多路图像。
        """
        camera_indexes = [camera.camera_index for camera in cameras]
        ok, images = self.comm.camera_image(
            camera_indexes,
            mode=mode,
            image_width=image_width,
            image_height=image_height,
        )
        if not ok:
            raise RuntimeError(f"camera_image failed for cameras {camera_indexes}")

        return {camera.room.name: image for camera, image in zip(cameras, images)}

    def save_snapshot(
        self,
        cameras: List[RoomCamera],
        mode: str,
        image_width: int,
        image_height: int,
    ) -> None:
        """保存每个房间的单帧图像和一张拼接预览图。"""
        images = self.capture_snapshot(cameras, mode, image_width, image_height)

        for room_name, image in images.items():
            image_path = self.output_dir / f"{safe_filename(room_name)}_{mode}.png"
            bgr_to_rgb_image(image).save(image_path)
            print(f"saved snapshot: {image_path}")

        sheet = build_contact_sheet(images, image_width, image_height)
        sheet_path = self.output_dir / f"room_camera_contact_sheet_{mode}.png"
        sheet.save(sheet_path)
        print(f"saved contact sheet: {sheet_path}")

    def save_overview_snapshot(
        self,
        rooms: List[RoomInfo],
        mode: str,
        image_width: int,
        image_height: int,
        field_view: float = 70.0,
    ) -> None:
        """保存一个覆盖整套户型的高位斜俯视图。"""
        if not rooms:
            raise ValueError("No rooms available for overview camera")

        min_x = min(room.center[0] - room.size[0] / 2 for room in rooms)
        max_x = max(room.center[0] + room.size[0] / 2 for room in rooms)
        min_z = min(room.center[2] - room.size[2] / 2 for room in rooms)
        max_z = max(room.center[2] + room.size[2] / 2 for room in rooms)

        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2
        span = max(max_x - min_x, max_z - min_z)

        position = [center_x, 8.0, min_z - span * 0.45]
        target = [center_x, 1.0, center_z]

        dx = target[0] - position[0]
        dy = target[1] - position[1]
        dz = target[2] - position[2]
        horizontal = math.sqrt(dx * dx + dz * dz)
        rotation = [
            math.degrees(math.atan2(-dy, horizontal)),
            math.degrees(math.atan2(dx, dz)),
            0,
        ]

        before_ok, before_count = self.comm.camera_count()
        if not before_ok:
            raise RuntimeError("camera_count failed before overview add_camera")

        ok, message = self.comm.add_camera(position=position, rotation=rotation, field_view=field_view)
        if not ok:
            raise RuntimeError(f"add overview camera failed: {message}")

        camera_index = parse_camera_id(message)
        if camera_index is None:
            camera_index = before_count

        ok, images = self.comm.camera_image(
            [camera_index],
            mode=mode,
            image_width=image_width,
            image_height=image_height,
        )
        if not ok or not images:
            raise RuntimeError("overview camera_image failed")

        output_path = self.output_dir / f"full_scene_overview_{mode}.png"
        bgr_to_rgb_image(images[0]).save(output_path)
        print(f"saved overview snapshot: {output_path}")

    def capture_video(
        self,
        cameras: List[RoomCamera],
        mode: str,
        image_width: int,
        image_height: int,
        fps: float,
        duration: float,
    ) -> None:
        """按目标 FPS 从所有房间摄像头采集并分别保存为 mp4。

        这一步实现的是“多摄像头同时输出”：每帧用一次 camera_image([...])
        同时取回所有摄像头，然后写入每个房间自己的视频文件。
        """
        frame_count = max(1, int(round(fps * duration)))
        frame_interval = 1.0 / fps
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        writers = {}
        for camera in cameras:
            video_path = self.output_dir / f"{safe_filename(camera.room.name)}_{mode}_{int(fps)}fps.mp4"
            writer = cv2.VideoWriter(str(video_path), fourcc, fps, (image_width, image_height))
            if not writer.isOpened():
                raise RuntimeError(f"Could not open video writer: {video_path}")
            writers[camera.room.name] = writer
            print(f"video output: {video_path}")

        start_time = time.perf_counter()
        captured = 0
        try:
            for frame_index in range(frame_count):
                frame_start = time.perf_counter()
                images = self.capture_snapshot(cameras, mode, image_width, image_height)

                for room_name, image in images.items():
                    writers[room_name].write(image)

                captured += 1
                elapsed = time.perf_counter() - frame_start
                sleep_time = frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

                if frame_index == 0 or (frame_index + 1) % max(1, int(fps)) == 0:
                    print(f"captured frames: {frame_index + 1}/{frame_count}")
        finally:
            for writer in writers.values():
                writer.release()

        total_time = time.perf_counter() - start_time
        actual_fps = captured / total_time if total_time > 0 else 0.0
        print(f"captured {captured} multi-camera frames in {total_time:.2f}s, actual loop FPS={actual_fps:.2f}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VirtualHome room-camera capture framework")
    parser.add_argument("--simulator-path", type=Path, default=None, help="Path to VirtualHome.exe")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for JSON/images/videos")
    parser.add_argument("--port", default="8080", help="HTTP port used by the Unity simulator")
    parser.add_argument("--attach", action="store_true", help="Attach to a manually started simulator instead of launching one")
    parser.add_argument("--mode", default="normal", help="Camera mode: normal, seg_inst, seg_class, depth, etc.")
    parser.add_argument("--width", type=int, default=640, help="Captured image width")
    parser.add_argument("--height", type=int, default=480, help="Captured image height")
    parser.add_argument("--fps", type=float, default=10.0, help="Target capture FPS")
    parser.add_argument("--duration", type=float, default=5.0, help="Video duration in seconds")
    parser.add_argument("--field-view", type=float, default=85.0, help="Room camera field of view")
    parser.add_argument("--height-ratio", type=float, default=0.32, help="Camera height above room center as room-height ratio")
    parser.add_argument("--camera-style", choices=["corner", "topdown"], default="corner", help="Room camera placement style")
    parser.add_argument("--include-overview", action="store_true", help="Also save a full-scene overview snapshot")
    parser.add_argument("--snapshot-only", action="store_true", help="Only save snapshots; do not write videos")
    return parser


def resolve_simulator_path(cli_path: Optional[Path]) -> Path:
    if cli_path is not None:
        return cli_path
    env_path = os.environ.get("VIRTUALHOME_SIMULATOR_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_SIMULATOR


def main() -> None:
    args = build_arg_parser().parse_args()
    simulator_path = resolve_simulator_path(args.simulator_path)

    framework = RoomCameraFramework(
        simulator_path=simulator_path,
        output_dir=args.output_dir,
        port=args.port,
        launch_simulator=not args.attach,
    )

    try:
        framework.launch()
        rooms = framework.query_environment()
        cameras = framework.add_room_cameras(
            rooms,
            field_view=args.field_view,
            height_ratio=args.height_ratio,
            camera_style=args.camera_style,
        )
        framework.save_snapshot(
            cameras,
            mode=args.mode,
            image_width=args.width,
            image_height=args.height,
        )
        if args.include_overview:
            framework.save_overview_snapshot(
                rooms,
                mode=args.mode,
                image_width=max(args.width * 2, 1024),
                image_height=max(args.height * 2, 768),
            )
        if not args.snapshot_only:
            framework.capture_video(
                cameras,
                mode=args.mode,
                image_width=args.width,
                image_height=args.height,
                fps=args.fps,
                duration=args.duration,
            )
    finally:
        framework.close()


if __name__ == "__main__":
    main()
