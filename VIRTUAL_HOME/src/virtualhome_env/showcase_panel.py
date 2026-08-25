"""
VirtualHome 本地展示控制台。

这个文件只负责 VirtualHome 侧的展示：
- 播放现有 VirtualHome/Python demo 画面；
- 提供可点击的示例脚本入口；
- 导出 720p/10fps JPG 图像流、外部检测结果、反馈动作和蓝牙联动样例；
- 不在这里实现 YOLO、A210 推理、云端大语言模型或真实拨号/短信。

Run:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\showcase_panel.py

Export interface samples without opening the GUI:
    .\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\showcase_panel.py --export-samples
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

import cv2
from PIL import Image, ImageDraw, ImageTk

try:
    import winsound
except ImportError:  # pragma: no cover - Windows demo path.
    winsound = None


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_REPO = REPO_ROOT / "virtualhome"
OUTPUT_ROOT = REPO_ROOT / "outputs"
PANEL_OUTPUT_DIR = OUTPUT_ROOT / "showcase_panel"
LIVE_CAMERA_PORT = "8080"
LIVE_CAMERA_SIZE = (1280, 720)
AGENT_URL = os.environ.get("A210_AGENT_URL", "http://127.0.0.1:8019").rstrip("/")
SHOW_AGENT_DEVICE_OVERLAY = os.environ.get("SHOW_AGENT_DEVICE_OVERLAY", "0").strip().lower() in {"1", "true", "yes", "on"}
DEVICE_STATE_FILE = OUTPUT_ROOT / "agent_bridge" / "simulated_device_state.json"
PANEL_AGENT_RESPONSE_FILE = OUTPUT_ROOT / "agent_bridge" / "panel_agent_responses.jsonl"
ACTIVE_MUSIC_PLAYER_FILE = OUTPUT_ROOT / "agent_bridge" / "active_music_player.json"
LIVE_CAMERA_SCENARIOS = {"whole_home_overview"}
AGENT_LIVE_STREAM_SCENARIOS = {
    "bedroom_person",
    "kitchen_pet",
    "fire_smoke",
    "health_event",
    "away_mode_stranger",
}
LIVE_AGENT_STREAM_INTERVAL_MS = 500
AGENT_TIMELINE_SPEED = float(os.environ.get("A210_AGENT_TIMELINE_SPEED", "1.0"))
ROOMS = ("living_room", "bedroom", "kitchen", "bathroom")
LIGHT_DEFAULTS = {f"{room}_ceiling_light": "on" for room in ROOMS}
WHOLE_HOME_SPEAKER = "whole_home_speaker"
MUSIC_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
_MUSIC_DIR_RAW = os.environ.get("VIRTUAL_HOME_MUSIC_DIR", "")
MUSIC_DIR = Path(_MUSIC_DIR_RAW) if _MUSIC_DIR_RAW else REPO_ROOT / "assets" / "music"
if not MUSIC_DIR.is_absolute():
    MUSIC_DIR = (REPO_ROOT / MUSIC_DIR).resolve()

sys.path.insert(0, str(PACKAGE_REPO))


def first_existing(*paths: Path) -> Path:
    """按优先级选择已经生成的媒体文件。"""
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def parse_camera_id(message: str) -> Optional[int]:
    """从 Unity 返回的 'New camera created. Id:79' 中解析摄像机编号。"""
    match = re.search(r"Id:(\d+)", message or "")
    if not match:
        return None
    return int(match.group(1))


def available_music_tracks() -> List[str]:
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


def resolve_music_path(track: str) -> Optional[Path]:
    requested = normalize_music_query(track)
    if not requested:
        return None
    files: List[Path] = []
    if not MUSIC_DIR.exists():
        return None
    try:
        files.extend(
            path
            for path in sorted(MUSIC_DIR.iterdir())
            if path.is_file() and path.suffix.lower() in MUSIC_EXTENSIONS
        )
    except OSError:
        return None
    if not files:
        return None
    for path in files:
        candidates = {
            normalize_music_query(path.stem),
            normalize_music_query(path.name),
        }
        if requested in candidates or any(candidate and (requested in candidate or candidate in requested) for candidate in candidates):
            return path
    return None


def normalize_music_query(text: str) -> str:
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


class MciAudioPlayer:
    """Single-source Windows audio player for Agent-controlled music."""

    def __init__(self) -> None:
        self.alias = "a210_vhome_music"
        self.active = False
        self.process: Optional[subprocess.Popen] = None
        self.stop()

    @staticmethod
    def available() -> bool:
        return sys.platform.startswith("win") and hasattr(ctypes, "windll")

    def play(self, path: Path, loop: bool = False) -> None:
        if not self.available():
            raise RuntimeError("Windows MCI audio is unavailable")

        self.stop()
        mci_error: Optional[Exception] = None
        try:
            self._play_mci(path, loop=loop)
            return
        except Exception as exc:
            mci_error = exc
            self._send_no_error(f"close {self.alias}")

        if path.suffix.lower() == ".mp3":
            try:
                self._play_powershell_media(path, loop=loop)
                return
            except Exception as exc:
                raise RuntimeError(f"MCI failed: {mci_error}; PowerShell MediaPlayer failed: {exc}") from exc

        raise mci_error

    def _play_mci(self, path: Path, loop: bool = False) -> None:
        suffix = path.suffix.lower()
        media_type = "mpegvideo" if suffix in {".mp3", ".m4a"} else "waveaudio" if suffix == ".wav" else ""
        open_cmd = f'open "{path}"'
        if media_type:
            open_cmd += f" type {media_type}"
        open_cmd += f" alias {self.alias}"

        self._send(open_cmd)
        self.active = True
        try:
            self._send(f"play {self.alias}" + (" repeat" if loop else ""))
        except Exception:
            self.stop()
            raise

    def _play_powershell_media(self, path: Path, loop: bool = False) -> None:
        uri = path.resolve().as_uri().replace("'", "''")
        loop_value = "$true" if loop else "$false"
        script = f"""
Add-Type -AssemblyName PresentationCore
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([Uri]::new('{uri}'))
$player.Volume = 1.0
$loop = {loop_value}
$player.Play()
while ($true) {{
    Start-Sleep -Milliseconds 200
    if ($player.NaturalDuration.HasTimeSpan -and $player.Position -ge $player.NaturalDuration.TimeSpan) {{
        if ($loop) {{
            $player.Position = [TimeSpan]::Zero
            $player.Play()
        }} else {{
            break
        }}
    }}
}}
$player.Close()
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        args = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ]
        startupinfo = None
        creationflags = 0
        if sys.platform.startswith("win"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        self.active = True
        self._write_registered_process(path)

    def stop(self) -> None:
        registered_pid = self._registered_pid()
        if self.process is not None:
            process = self.process
            self.process = None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        elif registered_pid is not None:
            self._kill_pid_tree(registered_pid)
        self._clear_registered_process()
        if not self.available():
            self.active = False
            return
        self._send_no_error(f"stop {self.alias}")
        self._send_no_error(f"close {self.alias}")
        self.active = False

    def has_registered_process(self) -> bool:
        return ACTIVE_MUSIC_PLAYER_FILE.exists()

    def _read_registered_process(self) -> Dict[str, object]:
        try:
            value = json.loads(ACTIVE_MUSIC_PLAYER_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _registered_pid(self) -> Optional[int]:
        data = self._read_registered_process()
        try:
            pid = int(data.get("pid") or 0)
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None

    def _write_registered_process(self, path: Path) -> None:
        if self.process is None:
            return
        data = {
            "pid": self.process.pid,
            "path": str(path.resolve()),
            "started_at": time.time(),
        }
        try:
            ACTIVE_MUSIC_PLAYER_FILE.parent.mkdir(parents=True, exist_ok=True)
            ACTIVE_MUSIC_PLAYER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _clear_registered_process(self) -> None:
        try:
            ACTIVE_MUSIC_PLAYER_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    def _kill_pid_tree(self, pid: int) -> None:
        if not sys.platform.startswith("win"):
            return
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=2.0,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    @staticmethod
    def _send(command: str) -> None:
        result = ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
        if result:
            buffer = ctypes.create_unicode_buffer(256)
            ctypes.windll.winmm.mciGetErrorStringW(result, buffer, 256)
            raise RuntimeError(buffer.value or f"MCI audio command failed: {result}")

    def _send_no_error(self, command: str) -> None:
        try:
            self._send(command)
        except Exception:
            pass


def normalize_device_state(state: Dict[str, object]) -> Dict[str, object]:
    normalized: Dict[str, object] = dict(state) if isinstance(state, dict) else {}
    normalized.setdefault("schema", "virtualhome.device_state.v1")
    normalized.setdefault("updated_at", 0)
    normalized.setdefault("alerts", [])
    normalized.setdefault("environment", {})

    lights = normalized.get("lights") if isinstance(normalized.get("lights"), dict) else {}
    for target, value in LIGHT_DEFAULTS.items():
        lights.setdefault(target, value)
    normalized["lights"] = lights

    speakers = normalized.get("speakers") if isinstance(normalized.get("speakers"), dict) else {}
    whole = speakers.get(WHOLE_HOME_SPEAKER) if isinstance(speakers, dict) else None
    if not isinstance(whole, dict):
        whole = {}

    state_text = str(whole.get("state") or "stop").lower()
    if state_text in {"play", "on"}:
        state_text = "playing"
    elif state_text in {"off", "stopped"}:
        state_text = "stop"
    if state_text not in {"playing", "pause", "stop"}:
        state_text = "stop"

    tracks = available_music_tracks()
    track = str(whole.get("track") or "")
    if state_text == "stop":
        track = ""
    normalized["speakers"] = {
        WHOLE_HOME_SPEAKER: {
            "state": state_text,
            "track": track,
            "scope": "whole_home",
            "source": str(whole.get("source") or ""),
            "music_dir": str(MUSIC_DIR),
            "available_tracks": tracks,
        }
    }
    normalized["music_library"] = {
        "dir": str(MUSIC_DIR),
        "supported_extensions": list(MUSIC_EXTENSIONS),
        "tracks": [{"name": name} for name in tracks],
    }
    return normalized


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def mix_hex(left: str, right: str, ratio: float) -> str:
    ratio = clamp(ratio, 0.0, 1.0)
    lr, lg, lb = hex_to_rgb(left)
    rr, rg, rb = hex_to_rgb(right)
    return rgb_to_hex(
        (
            int(lr + (rr - lr) * ratio),
            int(lg + (rg - lg) * ratio),
            int(lb + (rb - lb) * ratio),
        )
    )


@dataclass
class ShowcaseScenario:
    key: str
    title: str
    purpose: str
    room: str
    media_path: Path
    media_type: str
    stream_id: str
    category: str
    expected_external_result: Dict[str, object]
    feedback_action: Dict[str, object]
    bluetooth_actions: List[Dict[str, object]] = field(default_factory=list)
    audio_path: Optional[Path] = None


def feedback_action(
    scene: str,
    room: str,
    action: str,
    target: str,
    value: str,
    reason: str,
    payload: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    record: Dict[str, object] = {
        "schema": "virtualhome.feedback.v1",
        "source": "external_agent",
        "scene": scene,
        "room": room,
        "timestamp": 0.0,
        "action": action,
        "target": target,
        "value": value,
        "reason": reason,
    }
    if payload is not None:
        record["payload"] = payload
    return record


def bluetooth_action(
    scene: str,
    timestamp: float,
    device_type: str,
    device_id: str,
    action: str,
    payload: Dict[str, object],
) -> Dict[str, object]:
    return {
        "schema": "virtualhome.bluetooth_action.v1",
        "scene": scene,
        "timestamp": timestamp,
        "transport": "ble_placeholder",
        "device_type": device_type,
        "device_id": device_id,
        "action": action,
        "payload": payload,
    }


# 这里集中维护最终展示按钮。后续想增加 demo，只需要补一个 ShowcaseScenario。
SCENARIOS: List[ShowcaseScenario] = [
    ShowcaseScenario(
        key="whole_home_overview",
        title="全屋环境俯瞰交互",
        purpose="展示 VirtualHome 全屋环境。静态图支持平移/缩放；连接 VirtualHome.exe 后，可用右侧 VIEW CAMERA 按键实时移动/旋转 Unity 摄像机并刷新 720p 图像。Reset View 回到俯瞰相机位。",
        room="all_rooms",
        media_path=OUTPUT_ROOT / "room_cameras" / "full_scene_overview_normal.png",
        media_type="image",
        stream_id="whole_home_overview_camera",
        category="ENVIRONMENT",
        expected_external_result={
            "schema": "external.vision_result.v1",
            "source": "placeholder_yolov11_or_a210",
            "room": "all_rooms",
            "room_count": 4,
            "status": "whole_home_overview_ready",
        },
        feedback_action=feedback_action(
            scene="whole_home_overview",
            room="all_rooms",
            action="none",
            target="overview_preview",
            value="none",
            reason="overview_preview_only",
        ),
    ),
    ShowcaseScenario(
        key="multi_camera_layout",
        title="多摄像头布设",
        purpose="展示每个房间一路固定摄像头的采集结果，约定输出 720p/10fps/JPG 图像流给视觉侧。",
        room="all_rooms",
        media_path=OUTPUT_ROOT / "room_cameras" / "room_camera_contact_sheet_normal.png",
        media_type="image",
        stream_id="multi_room_camera_preview",
        category="CAMERAS",
        expected_external_result={
            "schema": "external.vision_result.v1",
            "source": "placeholder_yolov11_or_a210",
            "room": "all_rooms",
            "room_count": 4,
            "status": "room_camera_layout_ready",
            "payload": {
                "streams": ["bedroom_camera_0", "kitchen_camera_0", "livingroom_camera_0", "bathroom_camera_0"],
            },
        },
        feedback_action=feedback_action(
            scene="multi_camera_layout",
            room="all_rooms",
            action="none",
            target="camera_layout",
            value="none",
            reason="camera_layout_preview_only",
        ),
    ),
    ShowcaseScenario(
        key="bedroom_person",
        title="人员计数和无人关灯",
        purpose="使用 VirtualHome 官方 API 角色动画展示人物自然走进/走出；YOLO 人数统计归零后，只触发卧室灯光关闭反馈。",
        room="bedroom",
        media_path=first_existing(
            PANEL_OUTPUT_DIR / "virtualhome_api_motion" / "bedroom_walk_light" / "bedroom_walk_light_yolo_light_feedback.mp4",
            PANEL_OUTPUT_DIR / "virtualhome_api_motion" / "bedroom_walk_light" / "bedroom_walk_light_api_recording.mp4",
            PANEL_OUTPUT_DIR / "bedroom_walk_light" / "bedroom_natural_walk_light_off.mp4",
        ),
        media_type="video",
        stream_id="bedroom_camera_0",
        category="CLOSED LOOP",
        expected_external_result={
            "schema": "external.vision_result.v1",
            "source": "placeholder_yolov11_or_a210",
            "room": "bedroom",
            "timeline": [
                {"frame": 56, "t": 5.6, "person_count": 1, "event": "person_entered"},
                {"frame": 181, "t": 18.1, "person_count": 0, "event": "person_left"},
                {"frame": 185, "t": 18.5, "person_count": 0, "event": "person_left_light_off"},
            ],
        },
        feedback_action=feedback_action(
            scene="bedroom_person",
            room="bedroom",
            action="set_light",
            target="bedroom_ceiling_light",
            value="off",
            reason="person_count=0_after_person_left",
            payload={"room_scope": "bedroom_only", "sync": "after_yolo_person_count_zero"},
        ),
    ),
    ShowcaseScenario(
        key="kitchen_pet",
        title="普通模式宠物留守告警",
        purpose="普通模式下，厨房里有真实 VirtualHome cat 模型；主人通过 VirtualHome 人物行走帧进入并离开。YOLO 替代结果变成 person_count=0 + pet_count=1 后，agent 占位反馈触发厨房告警并只关闭厨房灯。",
        room="kitchen",
        media_path=first_existing(
            PANEL_OUTPUT_DIR / "kitchen_pet_owner_leave" / "kitchen_pet_owner_leave_alert.mp4",
            PANEL_OUTPUT_DIR / "virtualhome_api_pet" / "kitchen_pet" / "kitchen_pet_api_detection.mp4",
        ),
        media_type="video",
        stream_id="kitchen_camera_0",
        category="CLOSED LOOP",
        expected_external_result={
            "schema": "external.vision_result.v1",
            "source": "placeholder_yolov11_or_a210",
            "room": "kitchen",
            "smart_home_mode": "normal",
            "person_count": 0,
            "pet_type": "cat",
            "pet_count": 1,
            "event": "pet_unattended_alert_light_off",
            "timeline": [
                {"frame": 0, "t": 0.0, "person_count": 1, "pet_count": 1, "event": "owner_entered_kitchen"},
                {"frame": 62, "t": 6.2, "person_count": 0, "pet_count": 1, "event": "kitchen_unmanned_pet_present"},
                {"frame": 67, "t": 6.7, "person_count": 0, "pet_count": 1, "event": "pet_unattended_alert_light_off"},
            ],
        },
        feedback_action=feedback_action(
            scene="kitchen_pet",
            room="kitchen",
            action="raise_alert_and_set_light",
            target="kitchen_pet_guard_and_light",
            value="alert_on_light_off",
            reason="normal_mode_person_count=0_pet_count=1",
            payload={
                "mode": "normal",
                "alert": "pet_unattended_in_kitchen",
                "set_light": {"target": "kitchen_ceiling_light", "value": "off"},
                "room_scope": "kitchen_only",
                "transport": "agent_feedback_placeholder",
            },
        ),
        bluetooth_actions=[
            bluetooth_action(
                scene="kitchen_pet",
                timestamp=6.7,
                device_type="mobile_phone",
                device_id="phone_demo_01",
                action="notify",
                payload={
                    "title": "厨房宠物告警",
                    "message": "普通模式下厨房无人，但检测到猫仍在厨房，已关闭厨房灯并发出提醒。",
                    "mode": "normal",
                    "pet_type": "cat",
                    "pet_count": 1,
                },
            ),
        ],
    ),
    ShowcaseScenario(
        key="fire_smoke",
        title="火灾烟雾报警",
        purpose="模拟火灾烟雾，外部视觉检测后通过手机 BLE 占位发出告警。",
        room="kitchen",
        media_path=PANEL_OUTPUT_DIR / "fire_smoke" / "fire_smoke_alarm.mp4",
        media_type="video",
        stream_id="kitchen_camera_0",
        category="SAFETY",
        expected_external_result={
            "schema": "external.vision_result.v1",
            "source": "placeholder_yolov11_or_a210",
            "room": "kitchen",
            "person_count": 0,
            "hazard_detected": True,
            "hazard_type": "fire_smoke",
            "risk_level": "critical",
            "event": "fire_smoke_detected",
        },
        feedback_action=feedback_action(
            scene="fire_smoke",
            room="kitchen",
            action="raise_alert",
            target="fire_alarm",
            value="fire_smoke_detected",
            reason="person_count=0_and_smoke_detected",
            payload={"severity": "critical", "suggested_action": "notify_and_start_fire_alarm", "transport": "ble_placeholder"},
        ),
        bluetooth_actions=[
            bluetooth_action(
                scene="fire_smoke",
                timestamp=1.6,
                device_type="mobile_phone",
                device_id="phone_demo_01",
                action="notify",
                payload={"title": "Fire smoke alert", "hazard_type": "fire_smoke", "mode": "demo_only"},
            ),
        ],
    ),
    ShowcaseScenario(
        key="health_event",
        title="健康助手",
        purpose="普通状态为暖光；心率升高后切换冷光并播放预设音乐，手机显示缓解焦虑提示；30s 后恢复暖光并停止音乐。",
        room="bedroom",
        media_path=PANEL_OUTPUT_DIR / "health_event" / "health_assistant.mp4",
        media_type="video",
        stream_id="bedroom_camera_0",
        category="WEARABLE",
        expected_external_result={
            "schema": "external.health_event.v1",
            "source": "wearable_or_agent_placeholder",
            "room": "bedroom",
            "event": "anxiety_detected",
            "payload": {"heart_rate": 118, "anxiety_score": 0.88, "confidence": 0.91},
        },
        feedback_action=feedback_action(
            scene="health_event",
            room="bedroom",
            action="set_environment",
            target="bedroom_ambient_light_and_whole_home_music",
            value="anxiety_relief_mode",
            reason="wearable_detected_anxiety_high_heart_rate",
            payload={
                "light": "cool_blue",
                "music": "伊藤サチコ - いつも何度でも",
                "music_scope": "whole_home",
                "music_source": "health_event",
                "agent_message": "检测到心率升高，建议进行 4-7-8 呼吸，并播放舒缓音乐。",
                "transport": "agent_feedback_placeholder",
            },
        ),
        bluetooth_actions=[
            bluetooth_action(
                scene="health_event",
                timestamp=8.0,
                device_type="mobile_phone",
                device_id="phone_demo_01",
                action="notify",
                payload={
                    "event": "anxiety_relief_started",
                    "title": "健康助手",
                    "message": "检测到心率升高。请跟随 4-7-8 呼吸，放松肩颈，音乐将在 30 秒后自动关闭。",
                    "heart_rate": 118,
                    "anxiety_score": 0.88,
                    "mode": "demo_only",
                },
            )
        ],
        audio_path=MUSIC_DIR / "伊藤サチコ - いつも何度でも.mp3",
    ),
    ShowcaseScenario(
        key="away_mode_stranger",
        title="人物进入与离家告警",
        purpose="全屋视角中出现人物；YOLO/身份占位结果返回 person_count=1。Agent 当前为居家模式时只同步状态，当前为离家模式时触发安防告警。",
        room="all_rooms",
        media_path=PANEL_OUTPUT_DIR / "away_mode_stranger" / "away_mode_stranger_alert.mp4",
        media_type="video",
        stream_id="whole_home_overview_camera",
        category="SECURITY",
        expected_external_result={
            "schema": "external.security_result.v1",
            "source": "placeholder_yolov11_or_a210",
            "room": "all_rooms",
            "smart_home_mode": "agent_home_mode_dependent",
            "person_count": 1,
            "known_resident_count": 0,
            "unknown_person_count": 1,
            "alarm_active": False,
            "event": "person_entered_home",
        },
        feedback_action=feedback_action(
            scene="away_mode_stranger",
            room="all_rooms",
            action="raise_alert",
            target="home_security_alarm",
            value="stranger_detected",
            reason="away_mode_unknown_person_detected",
            payload={
                "mode": "away",
                "severity": "critical",
                "message": "away_mode_stranger_detected",
                "agent_interface": "placeholder_feedback_jsonl",
            },
        ),
        bluetooth_actions=[
            bluetooth_action(
                scene="away_mode_stranger",
                timestamp=2.2,
                device_type="mobile_phone",
                device_id="phone_demo_01",
                action="notify",
                payload={
                    "title": "离家模式告警",
                    "message": "检测到陌生人进入住宅，已触发安防告警并通知紧急联系人。",
                    "mode": "away",
                    "unknown_person_count": 1,
                },
            ),
        ],
    ),
]


def find_sample_frame(scenario: ShowcaseScenario) -> Optional[Path]:
    if scenario.key == "whole_home_overview":
        return OUTPUT_ROOT / "room_cameras" / "full_scene_overview_normal.png"
    if scenario.key == "multi_camera_layout":
        return scenario.media_path
    if scenario.key == "bedroom_person":
        api_frame = PANEL_OUTPUT_DIR / "virtualhome_api_motion" / "bedroom_walk_light" / "jpg" / "bedroom" / "frame_000060.jpg"
        if api_frame.exists():
            return api_frame
        return PANEL_OUTPUT_DIR / "bedroom_walk_light" / "jpg" / "bedroom" / "frame_000010.jpg"
    if scenario.key == "kitchen_pet":
        enhanced_frame = PANEL_OUTPUT_DIR / "kitchen_pet_owner_leave" / "jpg" / "kitchen" / "frame_000068.jpg"
        if enhanced_frame.exists():
            return enhanced_frame
        api_frame = PANEL_OUTPUT_DIR / "virtualhome_api_pet" / "kitchen_pet" / "jpg" / "kitchen" / "frame_000020.jpg"
        if api_frame.exists():
            return api_frame
        return None
    if scenario.key == "fire_smoke":
        return PANEL_OUTPUT_DIR / "fire_smoke" / "jpg" / "kitchen" / "frame_000020.jpg"
    if scenario.key == "health_event":
        return PANEL_OUTPUT_DIR / "health_event" / "jpg" / "bedroom" / "frame_000020.jpg"
    if scenario.key == "away_mode_stranger":
        return PANEL_OUTPUT_DIR / "away_mode_stranger" / "jpg" / "all_rooms" / "frame_000028.jpg"
    if scenario.media_type == "image":
        return scenario.media_path
    return None


def ensure_stream_jpg(frame_path: Optional[Path], scenario_key: str) -> Optional[Path]:
    """把截图统一整理成 1280x720 JPG，方便外部 YOLO/A210 直接读取。"""
    if frame_path is None or not frame_path.exists():
        return frame_path

    try:
        with Image.open(frame_path) as image:
            rgb = image.convert("RGB")
            if frame_path.suffix.lower() in {".jpg", ".jpeg"} and rgb.size == (1280, 720):
                return frame_path

            sample_dir = PANEL_OUTPUT_DIR / "interface_samples" / "sample_frames"
            sample_dir.mkdir(parents=True, exist_ok=True)
            output_path = sample_dir / f"{scenario_key}_{frame_path.stem}.jpg"

            canvas = Image.new("RGB", (1280, 720), (18, 22, 28))
            rgb.thumbnail((1280, 720), Image.Resampling.LANCZOS)
            left = (1280 - rgb.width) // 2
            top = (720 - rgb.height) // 2
            canvas.paste(rgb, (left, top))
            canvas.save(output_path, "JPEG", quality=95)
            return output_path
    except Exception:
        return frame_path


def build_frame_sample(scenario: ShowcaseScenario, frame_index: int = 0) -> Dict[str, object]:
    frame_path = ensure_stream_jpg(find_sample_frame(scenario), scenario.key)
    return {
        "schema": "virtualhome.frame.v1",
        "stream_id": scenario.stream_id,
        "scene": scenario.key,
        "room": scenario.room,
        "camera_id": 0,
        "frame_index": frame_index,
        "timestamp": round(frame_index / 10.0, 3),
        "resolution": [1280, 720],
        "fps": 10,
        "image": {
            "encoding": "jpg",
            "mime": "image/jpeg",
            "path": str(frame_path.relative_to(REPO_ROOT)) if frame_path else "",
        },
    }


def build_bluetooth_action_samples() -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for scenario in SCENARIOS:
        rows.extend(scenario.bluetooth_actions)
    return rows


def export_interface_samples(output_dir: Path = PANEL_OUTPUT_DIR) -> Path:
    """导出给其他同学集成时使用的接口样例。"""
    sample_dir = output_dir / "interface_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)

    frame_stream_path = sample_dir / "virtualhome_frame_stream_sample.jsonl"
    external_result_path = sample_dir / "external_result_sample.jsonl"
    feedback_path = sample_dir / "virtualhome_feedback_action_sample.jsonl"
    bluetooth_path = sample_dir / "virtualhome_bluetooth_action_sample.jsonl"
    catalog_path = sample_dir / "showcase_scenarios.json"

    with frame_stream_path.open("w", encoding="utf-8") as file:
        for index, scenario in enumerate(SCENARIOS):
            file.write(json.dumps(build_frame_sample(scenario, index), ensure_ascii=False) + "\n")

    with external_result_path.open("w", encoding="utf-8") as file:
        for scenario in SCENARIOS:
            file.write(json.dumps(scenario.expected_external_result, ensure_ascii=False) + "\n")

    with feedback_path.open("w", encoding="utf-8") as file:
        for scenario in SCENARIOS:
            file.write(json.dumps(scenario.feedback_action, ensure_ascii=False) + "\n")

    with bluetooth_path.open("w", encoding="utf-8") as file:
        for action in build_bluetooth_action_samples():
            file.write(json.dumps(action, ensure_ascii=False) + "\n")

    catalog = [asdict(scenario) for scenario in SCENARIOS]
    for item in catalog:
        item["media_path"] = str(Path(item["media_path"]).relative_to(REPO_ROOT))
        if item.get("audio_path"):
            item["audio_path"] = str(Path(item["audio_path"]).relative_to(REPO_ROOT))
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = sample_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# VirtualHome interface samples",
                "",
                "These files are VirtualHome-side examples only.",
                "",
                "- `virtualhome_frame_stream_sample.jsonl`: JPG frame messages sent to edge vision.",
                "- `external_result_sample.jsonl`: placeholder results expected from YOLO/A210/agent.",
                "- `virtualhome_feedback_action_sample.jsonl`: actions VirtualHome can receive.",
                "- `virtualhome_bluetooth_action_sample.jsonl`: demo-only BLE watch/phone actions.",
                "- `showcase_scenarios.json`: local demo catalog.",
                "",
                "The target stream format is 1280x720 at 10fps.",
                "BLE/call/SMS records are placeholders and do not trigger real devices.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return sample_dir


class ShowcasePanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("VirtualHome Edge Vision Command Center")
        self.root.geometry("1420x860")
        self.root.minsize(980, 620)

        self.colors = {
            "bg": "#03070d",
            "panel": "#07131d",
            "panel_alt": "#0b1c2a",
            "line": "#1b5368",
            "line_soft": "#113040",
            "cyan": "#44dfff",
            "green": "#76f2ba",
            "yellow": "#f8d56b",
            "red": "#ff6b7a",
            "violet": "#b58cff",
            "amber": "#ffb454",
            "text": "#e8f5ff",
            "muted": "#8fb4c3",
            "button": "#10283a",
            "button_active": "#17485c",
        }

        self.video_capture: Optional[cv2.VideoCapture] = None
        self.video_after_id: Optional[str] = None
        self.current_image: Optional[ImageTk.PhotoImage] = None
        self.last_pil_image: Optional[Image.Image] = None
        self.active_scenario: Optional[ShowcaseScenario] = None
        self.scenario_buttons: Dict[str, tk.Button] = {}
        self.media_zoom = 1.0
        self.media_pan: Tuple[int, int] = (0, 0)
        self.drag_start: Optional[Tuple[int, int]] = None
        self.phone_title: Optional[tk.Label] = None
        self.phone_body: Optional[tk.Label] = None
        self.phone_status: Optional[tk.Label] = None
        self.sound_enabled = True
        self.sound_button: Optional[tk.Button] = None
        self.audio_after_ids: List[str] = []
        self.agent_music_signature = ""
        self.missing_music_signature = ""
        self.audio_player = MciAudioPlayer()
        self.live_comm = None
        self.live_camera_index: Optional[int] = None
        self.live_camera_position: List[float] = [0.0, 8.0, -8.0]
        self.live_camera_rotation: List[float] = [58.0, 0.0, 0.0]
        self.live_camera_fov = 72.0
        self.live_camera_update_supported = True
        self.live_camera_label: Optional[tk.Label] = None
        self.device_state_mtime = 0.0
        self.live_stream_after_id: Optional[str] = None
        self.live_stream_started_at = 0.0
        self.live_stream_frame_index = 0
        self.live_stream_inflight = False
        self.current_stream_frame_path: Optional[Path] = None
        self.current_media_timestamp = 0.0
        self.current_media_frame_index = 0
        self.camera_panel: Optional[tk.Frame] = None
        self.phone_panel: Optional[tk.Frame] = None
        self.phone_shell: Optional[tk.Frame] = None
        self.phone_signal: Optional[tk.Label] = None
        self.status_tile_frames: List[Tuple[tk.Frame, str]] = []
        self.animation_phase = 0
        self.animation_after_id: Optional[str] = None
        self.ticker_label: Optional[tk.Label] = None
        self.side_canvas: Optional[tk.Canvas] = None
        self.side_inner: Optional[tk.Frame] = None
        self.side_window_id: Optional[int] = None
        self.agent_url = AGENT_URL
        self.agent_home_mode = "home"
        self.agent_home_mode_checked_at = 0.0

        self._build_ui()
        self.show_scenario(SCENARIOS[0])
        self._schedule_animation()

    def _label(self, parent: tk.Misc, text: str, size: int = 10, color: Optional[str] = None, bold: bool = False) -> tk.Label:
        weight = "bold" if bold else "normal"
        return tk.Label(
            parent,
            text=text,
            bg=self.colors["panel"],
            fg=color or self.colors["text"],
            font=("Microsoft YaHei UI", size, weight),
        )

    def _build_ui(self) -> None:
        self.root.configure(bg=self.colors["bg"])

        shell = tk.Frame(self.root, bg=self.colors["bg"], padx=18, pady=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = tk.Frame(shell, bg=self.colors["bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title = tk.Label(
            header,
            text="VirtualHome Edge Vision Command Center",
            bg=self.colors["bg"],
            fg=self.colors["text"],
            font=("Microsoft YaHei UI", 22, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")
        subtitle = tk.Label(
            header,
            text="VHOME STREAM BUS // EDGE VISION // AGENT FEEDBACK // DEVICE LINK",
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=("Consolas", 11),
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.mode_label = tk.Label(
            header,
            text="DEMO ONLY | BLE / CALL / SMS PLACEHOLDER",
            bg="#172b36",
            fg=self.colors["yellow"],
            font=("Consolas", 10, "bold"),
            padx=14,
            pady=6,
        )
        self.mode_label.grid(row=0, column=1, rowspan=2, sticky="e")

        body = tk.Frame(shell, bg=self.colors["bg"])
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=5)
        body.columnconfigure(1, weight=2, minsize=330)
        body.rowconfigure(0, weight=1)

        media_panel = tk.Frame(body, bg=self.colors["panel"], highlightbackground=self.colors["line"], highlightthickness=1)
        media_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        media_panel.columnconfigure(0, weight=1)
        media_panel.rowconfigure(1, weight=1)

        media_header = tk.Frame(media_panel, bg=self.colors["panel"], padx=14, pady=10)
        media_header.grid(row=0, column=0, sticky="ew")
        media_header.columnconfigure(0, weight=1)
        self.scene_title = self._label(media_header, "", size=15, bold=True)
        self.scene_title.grid(row=0, column=0, sticky="w")
        self.scene_category = self._label(media_header, "", size=10, color=self.colors["cyan"], bold=True)
        self.scene_category.grid(row=0, column=1, sticky="e")

        self.media_canvas = tk.Canvas(media_panel, bg="#02070c", highlightthickness=0)
        self.media_canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.media_canvas.bind("<Configure>", self._resize_media)
        self.media_canvas.bind("<ButtonPress-1>", self._start_pan)
        self.media_canvas.bind("<B1-Motion>", self._drag_pan)
        self.media_canvas.bind("<ButtonRelease-1>", self._end_pan)
        self.media_canvas.bind("<MouseWheel>", self._zoom_media)
        self.media_canvas.bind("<Button-4>", self._zoom_media)
        self.media_canvas.bind("<Button-5>", self._zoom_media)

        status_row = tk.Frame(media_panel, bg=self.colors["panel"], padx=14, pady=10)
        status_row.grid(row=2, column=0, sticky="ew")
        for index in range(4):
            status_row.columnconfigure(index, weight=1)

        self.camera_status = self._status_tile(status_row, 0, "CAMERA STREAM", "1280x720 JPG @ 10fps", self.colors["cyan"])
        self.vision_status = self._status_tile(status_row, 1, "EDGE VISION", "waiting", self.colors["green"])
        self.ble_status = self._status_tile(status_row, 2, "BLE DEVICES", "standby", self.colors["yellow"])
        self.feedback_status = self._status_tile(status_row, 3, "FEEDBACK", "none", self.colors["red"])

        side_shell = tk.Frame(body, bg=self.colors["bg"])
        side_shell.grid(row=0, column=1, sticky="nsew")
        side_shell.columnconfigure(0, weight=1)
        side_shell.rowconfigure(0, weight=1)

        self.side_canvas = tk.Canvas(side_shell, bg=self.colors["bg"], highlightthickness=0)
        side_scrollbar = tk.Scrollbar(side_shell, orient="vertical", command=self.side_canvas.yview)
        self.side_canvas.configure(yscrollcommand=side_scrollbar.set)
        self.side_canvas.grid(row=0, column=0, sticky="nsew")
        side_scrollbar.grid(row=0, column=1, sticky="ns")

        side = tk.Frame(self.side_canvas, bg=self.colors["bg"])
        side.columnconfigure(0, weight=1)
        self.side_inner = side
        self.side_window_id = self.side_canvas.create_window((0, 0), window=side, anchor="nw")
        side.bind("<Configure>", self._update_side_scroll_region)
        self.side_canvas.bind("<Configure>", self._resize_side_window)

        script_panel = self._panel(side, "SCENARIO SCRIPTS")
        script_panel.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        for index, scenario in enumerate(SCENARIOS):
            button = tk.Button(
                script_panel,
                text=f"{index + 1:02d}  {scenario.title}",
                anchor="w",
                command=lambda item=scenario: self.show_scenario(item),
                bg=self.colors["button"],
                fg=self.colors["text"],
                activebackground=self.colors["button_active"],
                activeforeground=self.colors["text"],
                relief="flat",
                bd=0,
                padx=12,
                pady=9,
                font=("Microsoft YaHei UI", 10),
            )
            button.grid(row=index + 1, column=0, sticky="ew", padx=12, pady=(0, 7))
            self.scenario_buttons[scenario.key] = button

        self.camera_panel = self._panel(side, "VIEW CAMERA")
        self.camera_panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._build_live_camera_panel(self.camera_panel)

        self.phone_panel = self._panel(side, "PHONE / AGENT LINK")
        self.phone_panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self._build_phone_panel(self.phone_panel)

        actions = self._panel(side, "LOCAL ACTIONS")
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        export_button = self._action_button(actions, "Export Interface JSONL", self.export_samples)
        export_button.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 7))
        open_button = self._action_button(actions, "Open Output Folder", self.open_output_dir)
        open_button.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 7))
        self.sound_button = self._action_button(actions, "", self.toggle_sound)
        self._set_sound_button_label()
        self.sound_button.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 7))
        reset_view = self._action_button(actions, "Reset View", self.reset_media_view)
        reset_view.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))

        detail_panel = self._panel(side, "ACTIVE DATA CONTRACT")
        detail_panel.grid(row=3, column=0, sticky="ew")
        self.details = tk.Text(
            detail_panel,
            wrap="word",
            bg="#03090f",
            fg=self.colors["text"],
            insertbackground=self.colors["cyan"],
            relief="flat",
            bd=0,
            font=("Consolas", 9),
            padx=10,
            pady=10,
            height=11,
        )
        self.details.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self._bind_side_mousewheel(side_shell)

        footer = tk.Frame(shell, bg=self.colors["bg"])
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.status_label = tk.Label(
            footer,
            text="Ready",
            bg=self.colors["bg"],
            fg=self.colors["muted"],
            font=("Microsoft YaHei UI", 10),
        )
        self.status_label.pack(anchor="w")
        self.ticker_label = tk.Label(
            footer,
            text="",
            bg="#061018",
            fg=self.colors["cyan"],
            font=("Consolas", 10, "bold"),
            padx=10,
            pady=5,
        )
        self.ticker_label.pack(fill="x", pady=(6, 0))

    def _panel(self, parent: tk.Misc, title: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.colors["panel"], highlightbackground=self.colors["line"], highlightthickness=1)
        frame.columnconfigure(0, weight=1)
        label = tk.Label(
            frame,
            text=title,
            bg=self.colors["panel"],
            fg=self.colors["cyan"],
            font=("Consolas", 10, "bold"),
            padx=12,
            pady=10,
        )
        label.grid(row=0, column=0, sticky="w")
        return frame

    def _update_side_scroll_region(self, _event: Optional[tk.Event] = None) -> None:
        if self.side_canvas is not None:
            self.side_canvas.configure(scrollregion=self.side_canvas.bbox("all"))

    def _resize_side_window(self, event: tk.Event) -> None:
        if self.side_canvas is not None and self.side_window_id is not None:
            self.side_canvas.itemconfigure(self.side_window_id, width=event.width)

    def _bind_side_mousewheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_side_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_side_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_side_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_side_mousewheel(child)

    def _on_side_mousewheel(self, event: tk.Event) -> str:
        if self.side_canvas is None:
            return "break"
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            units = -3 if getattr(event, "delta", 0) > 0 else 3
        self.side_canvas.yview_scroll(units, "units")
        return "break"

    def _build_phone_panel(self, parent: tk.Misc) -> None:
        phone = tk.Frame(parent, bg="#05090f", highlightbackground="#2b5363", highlightthickness=2)
        self.phone_shell = phone
        phone.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        phone.columnconfigure(0, weight=1)
        self.phone_signal = tk.Label(
            phone,
            text="BLE LINK  READY",
            bg="#05090f",
            fg=self.colors["green"],
            font=("Consolas", 9, "bold"),
            padx=12,
            pady=6,
        )
        self.phone_signal.grid(row=0, column=0, sticky="ew")
        self.phone_title = tk.Label(
            phone,
            text="Agent Phone",
            bg="#05090f",
            fg=self.colors["cyan"],
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        self.phone_title.grid(row=1, column=0, sticky="ew")
        self.phone_body = tk.Label(
            phone,
            text="No notification",
            bg="#081923",
            fg=self.colors["text"],
            font=("Microsoft YaHei UI", 10),
            padx=12,
            pady=12,
            wraplength=330,
            justify="left",
        )
        self.phone_body.grid(row=2, column=0, sticky="ew", padx=10)
        self.phone_status = tk.Label(
            phone,
            text="BLE placeholder standby",
            bg="#05090f",
            fg=self.colors["muted"],
            font=("Consolas", 9),
            padx=12,
            pady=8,
        )
        self.phone_status.grid(row=3, column=0, sticky="ew")

    def _action_button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg="#163347",
            fg=self.colors["text"],
            activebackground="#1e5268",
            activeforeground=self.colors["text"],
            relief="flat",
            bd=0,
            padx=12,
            pady=9,
            font=("Consolas", 10, "bold"),
        )

    def _camera_button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            width=8,
            command=command,
            bg="#0d2535",
            fg=self.colors["text"],
            activebackground="#1e5268",
            activeforeground=self.colors["text"],
            relief="flat",
            bd=0,
            padx=6,
            pady=7,
            font=("Consolas", 9, "bold"),
        )

    def _build_live_camera_panel(self, parent: tk.Misc) -> None:
        for column in range(4):
            parent.columnconfigure(column, weight=1, uniform="view_camera_columns")

        self.live_camera_label = tk.Label(
            parent,
            text="Open VirtualHome.exe, press Play!, then connect.",
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Consolas", 9),
            padx=12,
            pady=4,
        )
        self.live_camera_label.grid(row=1, column=0, columnspan=4, sticky="ew", padx=12, pady=(0, 7))

        self._camera_button(parent, "Connect API", self.connect_live_camera).grid(row=2, column=0, columnspan=2, sticky="ew", padx=(12, 4), pady=(0, 6))
        self._camera_button(parent, "Reset", self.reset_live_camera_view).grid(row=2, column=2, columnspan=2, sticky="ew", padx=(4, 12), pady=(0, 6))

        self._camera_button(parent, "Yaw -", lambda: self.rotate_live_camera(0.0, -6.0)).grid(row=3, column=0, sticky="ew", padx=(12, 4), pady=(0, 6))
        self._camera_button(parent, "Yaw +", lambda: self.rotate_live_camera(0.0, 6.0)).grid(row=3, column=1, sticky="ew", padx=4, pady=(0, 6))
        self._camera_button(parent, "Pitch +", lambda: self.rotate_live_camera(4.0, 0.0)).grid(row=3, column=2, sticky="ew", padx=4, pady=(0, 6))
        self._camera_button(parent, "Pitch -", lambda: self.rotate_live_camera(-4.0, 0.0)).grid(row=3, column=3, sticky="ew", padx=(4, 12), pady=(0, 6))

        self._camera_button(parent, "Left", lambda: self.move_live_camera(strafe=-0.4)).grid(row=4, column=0, sticky="ew", padx=(12, 4), pady=(0, 6))
        self._camera_button(parent, "Right", lambda: self.move_live_camera(strafe=0.4)).grid(row=4, column=1, sticky="ew", padx=4, pady=(0, 6))
        self._camera_button(parent, "Fwd", lambda: self.move_live_camera(forward=0.4)).grid(row=4, column=2, sticky="ew", padx=4, pady=(0, 6))
        self._camera_button(parent, "Back", lambda: self.move_live_camera(forward=-0.4)).grid(row=4, column=3, sticky="ew", padx=(4, 12), pady=(0, 6))

        self._camera_button(parent, "Up", lambda: self.move_live_camera(up=0.3)).grid(row=5, column=0, sticky="ew", padx=(12, 4), pady=(0, 12))
        self._camera_button(parent, "Down", lambda: self.move_live_camera(up=-0.3)).grid(row=5, column=1, sticky="ew", padx=4, pady=(0, 12))
        self._camera_button(parent, "FOV -", lambda: self.zoom_live_camera(-3.0)).grid(row=5, column=2, sticky="ew", padx=4, pady=(0, 12))
        self._camera_button(parent, "FOV +", lambda: self.zoom_live_camera(3.0)).grid(row=5, column=3, sticky="ew", padx=(4, 12), pady=(0, 12))

    def _status_tile(self, parent: tk.Misc, column: int, title: str, value: str, accent: str) -> tk.Label:
        tile = tk.Frame(parent, bg=self.colors["panel_alt"], highlightbackground=self.colors["line"], highlightthickness=2)
        tile.grid(row=0, column=column, sticky="ew", padx=4)
        header = tk.Frame(tile, bg=self.colors["panel_alt"])
        header.pack(fill="x")
        tk.Label(
            header,
            text=title,
            bg=self.colors["panel_alt"],
            fg=accent,
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=4,
        ).pack(side="left", anchor="w")
        tk.Label(
            header,
            text="●",
            bg=self.colors["panel_alt"],
            fg=accent,
            font=("Consolas", 10, "bold"),
            padx=8,
        ).pack(side="right")
        value_label = tk.Label(
            tile,
            text=value,
            bg=self.colors["panel_alt"],
            fg=self.colors["text"],
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=4,
        )
        value_label.pack(anchor="w")
        self.status_tile_frames.append((tile, accent))
        return value_label

    def show_scenario(self, scenario: ShowcaseScenario) -> None:
        self.stop_video()
        self.stop_audio()
        self.stop_live_agent_stream()
        self.active_scenario = scenario
        self.current_stream_frame_path = None
        self.current_media_timestamp = 0.0
        self.current_media_frame_index = 0
        self._reset_media_transform()
        self._mark_active_button(scenario.key)
        self._update_context_panels(scenario)
        self._update_header(scenario)
        self._update_details(scenario)
        self._write_log_for_scenario(scenario)
        if not self._scenario_uses_live_agent_stream(scenario):
            self._post_scenario_to_agent(scenario)

        if not scenario.media_path.exists():
            self.show_placeholder(f"缺少演示文件:\n{scenario.media_path}")
        elif scenario.key in LIVE_CAMERA_SCENARIOS and self.live_comm is not None:
            self.reset_live_camera_view()
        elif scenario.media_type == "video":
            self.play_video(scenario.media_path)
        else:
            self.show_image(scenario.media_path)

        if self._scenario_uses_live_agent_stream(scenario):
            self.start_live_agent_stream(scenario)

    def _update_context_panels(self, scenario: ShowcaseScenario) -> None:
        """01/02 展示摄像头控制；交互样本保留原来的房间样本画面。"""
        if self.camera_panel is None or self.phone_panel is None:
            return
        if scenario.key in LIVE_CAMERA_SCENARIOS:
            self.camera_panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))
            self.phone_panel.grid_remove()
        else:
            self.camera_panel.grid_remove()
            self.phone_panel.grid(row=1, column=0, sticky="ew", pady=(0, 12))

    def _mark_active_button(self, active_key: str) -> None:
        for key, button in self.scenario_buttons.items():
            selected = key == active_key
            button.configure(
                bg=self.colors["button_active"] if selected else self.colors["button"],
                fg=self.colors["cyan"] if selected else self.colors["text"],
            )

    def _update_header(self, scenario: ShowcaseScenario) -> None:
        self.scene_title.configure(text=scenario.title)
        self.scene_category.configure(text=scenario.category)
        self.vision_status.configure(text=self._vision_summary(scenario))
        self.ble_status.configure(text=self._ble_summary(scenario))
        self.feedback_status.configure(text=f"{scenario.feedback_action['action']} -> {scenario.feedback_action['target']}")
        self._update_phone(scenario)
        self.status_label.configure(
            text=f"当前场景: {scenario.title} | 输出目标: 720p JPG stream @ 10fps | 场景反馈: {scenario.feedback_action['action']}"
        )

    def _schedule_animation(self) -> None:
        self.animation_after_id = self.root.after(90, self._animate_ui)

    def _animate_ui(self) -> None:
        self.animation_phase = (self.animation_phase + 1) % 100000
        pulse = (math.sin(self.animation_phase * 0.16) + 1.0) / 2.0

        self.mode_label.configure(fg=mix_hex(self.colors["yellow"], self.colors["cyan"], pulse * 0.65))
        self.scene_category.configure(fg=mix_hex(self.colors["cyan"], self.colors["green"], pulse * 0.55))

        for index, (tile, accent) in enumerate(self.status_tile_frames):
            local_pulse = (math.sin(self.animation_phase * 0.16 + index * 0.9) + 1.0) / 2.0
            tile.configure(highlightbackground=mix_hex(self.colors["line"], accent, 0.25 + local_pulse * 0.7))

        if self.active_scenario is not None:
            for key, button in self.scenario_buttons.items():
                if key != self.active_scenario.key:
                    continue
                button.configure(
                    bg=mix_hex(self.colors["button_active"], "#236a7c", 0.35 + pulse * 0.35),
                    fg=mix_hex(self.colors["text"], self.colors["cyan"], 0.55 + pulse * 0.35),
                )

        phone_active = self.active_scenario is not None and bool(self.active_scenario.bluetooth_actions)
        if self.phone_shell is not None:
            phone_accent = self.colors["green"] if phone_active else self.colors["line"]
            self.phone_shell.configure(highlightbackground=mix_hex("#2b5363", phone_accent, 0.25 + pulse * 0.55))
        if self.phone_signal is not None:
            self.phone_signal.configure(
                text="BLE LINK  ACTIVE" if phone_active else "BLE LINK  READY",
                fg=mix_hex(self.colors["muted"], self.colors["green"] if phone_active else self.colors["cyan"], 0.45 + pulse * 0.45),
            )

        if self.ticker_label is not None:
            self.ticker_label.configure(
                text=self._ticker_text(),
                fg=mix_hex(self.colors["cyan"], self.colors["green"], 0.2 + pulse * 0.45),
            )

        if self.last_pil_image is not None:
            self._draw_media_image(self.last_pil_image)
        self._refresh_live_camera_after_agent_control()
        self._sync_agent_music_playback()

        self._schedule_animation()

    def _ticker_text(self) -> str:
        scenario = self.active_scenario
        if scenario is None:
            base = " VHOME BUS // WAITING FOR SCENARIO // "
        else:
            base = (
                f" STREAM={scenario.stream_id} // ROOM={scenario.room} // "
                f"VISION={self._vision_summary(scenario)} // FEEDBACK={scenario.feedback_action['action']}->{scenario.feedback_action['target']} // "
                f"BLE={self._ble_summary(scenario)} // 1280x720@10FPS JPG // "
            )
        repeated = (base + "   ") * 4
        start = self.animation_phase % max(1, len(base))
        return repeated[start : start + 150]

    def _vision_summary(self, scenario: ShowcaseScenario) -> str:
        result = scenario.expected_external_result
        if result.get("fall_detected"):
            return f"fall={result.get('fall_detected')} conf={result.get('fall_confidence')}"
        if scenario.key == "away_mode_stranger":
            mode = self._agent_home_mode()
            return "person=1 unknown=1 mode=away" if mode == "away" else "person=1 mode=home"
        if "unknown_person_count" in result:
            return f"unknown={result.get('unknown_person_count')} mode={result.get('smart_home_mode')}"
        if "pet_count" in result:
            mode = result.get("smart_home_mode")
            if mode:
                return f"{result.get('pet_type')} count={result.get('pet_count')} mode={mode}"
            return f"{result.get('pet_type')} count={result.get('pet_count')}"
        if result.get("hazard_detected"):
            return f"hazard={result.get('hazard_type')}"
        if result.get("schema") == "external.health_event.v1":
            payload = result.get("payload") or {}
            if isinstance(payload, dict):
                return f"HR={payload.get('heart_rate')} anxiety={payload.get('anxiety_score')}"
            return str(result.get("event") or "health event")
        if "person_count" in result:
            return f"person_count={result.get('person_count')}"
        if "timeline" in result:
            return "person tracking timeline"
        return str(result.get("status") or result.get("event") or "ready")

    def _ble_summary(self, scenario: ShowcaseScenario) -> str:
        if not scenario.bluetooth_actions:
            return "no BLE action"
        devices = sorted({str(item["device_type"]) for item in scenario.bluetooth_actions})
        return ", ".join(devices)

    def _update_phone(self, scenario: ShowcaseScenario) -> None:
        if self.phone_title is None or self.phone_body is None or self.phone_status is None:
            return

        if not scenario.bluetooth_actions:
            action = scenario.feedback_action
            self.phone_title.configure(text="Agent Phone")
            self.phone_body.configure(text=f"{scenario.title}\nAgent action: {action['action']} -> {action['target']}")
            self.phone_status.configure(text="No phone push for this scene")
            return

        action = scenario.bluetooth_actions[0]
        payload = action.get("payload", {})
        device_type = str(action.get("device_type", "device"))
        self.phone_title.configure(text=f"{device_type.replace('_', ' ').title()} Notification")

        if scenario.key == "kitchen_pet":
            message = (
                f"{payload.get('title', '厨房宠物告警')}\n"
                f"普通模式 | 厨房无人\n"
                f"{payload.get('pet_type', 'cat')} count={payload.get('pet_count', 1)}\n"
                "Action: 告警 + 关闭厨房灯"
            )
        elif scenario.key == "away_mode_stranger":
            mode = self._agent_home_mode()
            if mode == "away":
                message = (
                    f"{payload.get('title', '离家模式告警')}\n"
                    "离家模式 | 陌生人进入\n"
                    "person count=1 | unknown count=1\n"
                    "Action: 安防告警 + 通知联系人"
                )
            else:
                message = (
                    "人物进入检测\n"
                    "居家模式 | 人物进入\n"
                    "person count=1\n"
                    "Action: 仅同步状态"
                )
        elif scenario.key == "fire_smoke":
            message = f"{payload.get('title', 'Fire smoke alert')}\nRisk: critical\nAction: notify caregiver"
        elif scenario.key == "health_event":
            message = str(payload.get("message", "检测到心率升高，请跟随呼吸节奏放松。"))
        else:
            message = json.dumps(payload, ensure_ascii=False)

        self.phone_body.configure(text=message)
        self.phone_status.configure(text=f"BLE placeholder | t={action.get('timestamp', 0)}s | {action.get('action')}")

    def _update_details(self, scenario: ShowcaseScenario) -> None:
        details = {
            "scene": scenario.key,
            "title": scenario.title,
            "purpose": scenario.purpose,
            "stream_contract": {
                "stream_id": scenario.stream_id,
                "room": scenario.room,
                "resolution": [1280, 720],
                "fps": 10,
                "format": "jpg",
            },
            "external_result_placeholder": scenario.expected_external_result,
            "virtualhome_feedback_action": scenario.feedback_action,
            "bluetooth_actions": scenario.bluetooth_actions,
            "audio_path": str(scenario.audio_path.relative_to(REPO_ROOT)) if scenario.audio_path else None,
        }
        self.details.delete("1.0", tk.END)
        self.details.insert(tk.END, json.dumps(details, ensure_ascii=False, indent=2))

    def _write_log_for_scenario(self, scenario: ShowcaseScenario) -> None:
        PANEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        event_path = PANEL_OUTPUT_DIR / "clicked_scenarios.jsonl"
        record = {
            "timestamp": time.time(),
            "scene": scenario.key,
            "stream_sample": build_frame_sample(scenario),
            "expected_external_result": scenario.expected_external_result,
            "feedback_action": scenario.feedback_action,
            "bluetooth_actions": scenario.bluetooth_actions,
        }
        with event_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _scenario_uses_live_agent_stream(scenario: ShowcaseScenario) -> bool:
        return scenario.key in AGENT_LIVE_STREAM_SCENARIOS

    def start_live_agent_stream(self, scenario: ShowcaseScenario) -> None:
        self.stop_live_agent_stream()
        self.live_stream_started_at = time.monotonic()
        self.live_stream_frame_index = 0
        self.live_stream_inflight = False
        self.current_stream_frame_path = None
        self.current_media_timestamp = 0.0
        self.current_media_frame_index = 0
        self._prepare_live_stream_scene(scenario)
        self._send_live_agent_frame()

    def stop_live_agent_stream(self) -> None:
        if self.live_stream_after_id is not None:
            try:
                self.root.after_cancel(self.live_stream_after_id)
            except tk.TclError:
                pass
            self.live_stream_after_id = None
        self.live_stream_inflight = False

    def _prepare_live_stream_scene(self, scenario: ShowcaseScenario) -> None:
        if scenario.key == "bedroom_person":
            self._apply_local_device_command("bedroom", "light", "on")
        elif scenario.key == "kitchen_pet":
            self._apply_local_device_command("kitchen", "light", "on")

    def _send_live_agent_frame(self) -> None:
        scenario = self.active_scenario
        if scenario is None or not self._scenario_uses_live_agent_stream(scenario):
            return

        elapsed = self._current_agent_stream_time()
        frame_index = (
            self.current_media_frame_index
            if self.current_stream_frame_path is not None
            else self.live_stream_frame_index
        )
        frame = build_frame_sample(scenario, frame_index=frame_index)
        frame["timestamp"] = round(elapsed, 3)
        frame["frame_index"] = frame_index

        image_path = self._current_agent_frame_path(scenario)
        if image_path is not None:
            frame["image"] = {"encoding": "jpg", "mime": "image/jpeg", "path": str(image_path.relative_to(REPO_ROOT))}

        packet = {
            "schema": "virtualhome.agent_bridge_packet.v1",
            "source": "showcase_panel_live",
            "scene": scenario.key,
            "frame": frame,
            "external_result": self._current_external_result(scenario, elapsed),
        }

        if not self.live_stream_inflight:
            self.live_stream_inflight = True
            thread = threading.Thread(target=self._post_live_agent_packet_worker, args=(packet,), daemon=True)
            thread.start()

        self.live_stream_frame_index += 1
        self.live_stream_after_id = self.root.after(LIVE_AGENT_STREAM_INTERVAL_MS, self._send_live_agent_frame)

    def _post_live_agent_packet_worker(self, packet: Dict[str, object]) -> None:
        try:
            self._post_agent_packet_worker(packet)
        finally:
            self.live_stream_inflight = False

    def _current_agent_stream_time(self) -> float:
        if self.current_stream_frame_path is not None:
            return self.current_media_timestamp
        return (time.monotonic() - self.live_stream_started_at) * AGENT_TIMELINE_SPEED

    def _current_agent_frame_path(self, scenario: ShowcaseScenario) -> Optional[Path]:
        if (
            self.current_stream_frame_path is not None
            and self.current_stream_frame_path.exists()
            and self.active_scenario is not None
            and self.active_scenario.key == scenario.key
        ):
            return self.current_stream_frame_path

        if scenario.key == "whole_home_overview" and self.live_comm is not None:
            try:
                if self.live_camera_index is None:
                    self.reset_live_camera_view()
                else:
                    self._capture_live_camera_frame()
                live_path = PANEL_OUTPUT_DIR / "live_overview" / "latest_overview_camera.jpg"
                if live_path.exists():
                    return live_path
            except Exception as exc:
                self._set_live_camera_status(f"Live frame capture failed: {exc}", error=True)
        return find_sample_frame(scenario)

    def _current_external_result(self, scenario: ShowcaseScenario, elapsed: float) -> Dict[str, object]:
        result = json.loads(json.dumps(scenario.expected_external_result, ensure_ascii=False))
        result["scene"] = scenario.key
        if scenario.key == "away_mode_stranger":
            result = self._mode_adjusted_intrusion_result(result)
        timeline = result.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            return result

        selected: Optional[Dict[str, object]] = None
        for item in timeline:
            if not isinstance(item, dict):
                continue
            try:
                item_t = float(item.get("t", 0.0))
            except (TypeError, ValueError):
                item_t = 0.0
            if elapsed >= item_t:
                selected = item

        compact = {key: value for key, value in result.items() if key != "timeline"}
        if selected is None:
            if scenario.key == "bedroom_person":
                compact.update({"person_count": 0, "event": "room_empty_light_on"})
            elif scenario.key == "kitchen_pet":
                compact.update({"person_count": 1, "pet_count": 1, "pet_type": "cat", "event": "owner_entered_kitchen"})
            return compact

        for key, value in selected.items():
            if key not in {"frame", "t"}:
                compact[key] = value
        return compact

    def _mode_adjusted_intrusion_result(self, result: Dict[str, object]) -> Dict[str, object]:
        mode = self._agent_home_mode()
        adjusted = dict(result)
        adjusted["smart_home_mode"] = mode
        person_count = max(1, self._safe_int(adjusted.get("person_count"), 1))
        adjusted["person_count"] = person_count
        if mode == "away":
            adjusted["known_resident_count"] = 0
            adjusted["unknown_person_count"] = max(1, self._safe_int(adjusted.get("unknown_person_count"), person_count))
            adjusted["unknown_person"] = True
            adjusted["alarm_active"] = True
            adjusted["event"] = "away_mode_stranger_alert"
        else:
            adjusted["known_resident_count"] = person_count
            adjusted["unknown_person_count"] = 0
            adjusted["unknown_person"] = False
            adjusted["alarm_active"] = False
            adjusted["event"] = "person_entered_home"
        return adjusted

    def _agent_home_mode(self) -> str:
        now = time.monotonic()
        if now - self.agent_home_mode_checked_at < 1.0:
            return self.agent_home_mode
        self.agent_home_mode_checked_at = now
        try:
            with urllib.request.urlopen(self.agent_url + "/api/home-mode", timeout=0.7) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            mode = str(data.get("mode") or "home").strip().lower()
            self.agent_home_mode = "away" if mode == "away" else "home"
        except Exception:
            self.agent_home_mode = "home"
        return self.agent_home_mode

    @staticmethod
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _apply_local_device_command(self, room: str, device: str, command: str) -> None:
        state = normalize_device_state(self._read_agent_device_state())
        state["updated_at"] = time.time()

        if device == "light":
            state["lights"][f"{room}_ceiling_light"] = command
        elif device == "speaker":
            state["speakers"] = {
                WHOLE_HOME_SPEAKER: {
                    "state": "playing" if command == "play" else command,
                    "track": "",
                    "scope": "whole_home",
                    "music_dir": str(MUSIC_DIR),
                    "available_tracks": available_music_tracks(),
                }
            }

        DEVICE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEVICE_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

        if self.live_comm is None:
            return
        try:
            from unity_device_controller import UnityDeviceController

            controller = UnityDeviceController(port=LIVE_CAMERA_PORT, timeout_wait=3)
            controller.control(room, device, command)
        except Exception as exc:
            self._set_live_camera_status(f"Initial device sync failed: {exc}", error=True)

    def _post_scenario_to_agent(self, scenario: ShowcaseScenario) -> None:
        packet = {
            "schema": "virtualhome.agent_bridge_packet.v1",
            "source": "showcase_panel",
            "scene": scenario.key,
            "frame": build_frame_sample(scenario),
            "external_result": scenario.expected_external_result,
        }
        thread = threading.Thread(target=self._post_agent_packet_worker, args=(packet,), daemon=True)
        thread.start()

    def _post_agent_packet_worker(self, packet: Dict[str, object]) -> None:
        response: Dict[str, object]
        try:
            data = json.dumps(packet, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                self.agent_url + "/api/virtualhome/frame",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=8.0) as resp:
                response = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            response = {
                "schema": "a210.agent_response.v1",
                "status": "error",
                "scene": packet.get("scene"),
                "error": str(exc),
            }

        PANEL_AGENT_RESPONSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with PANEL_AGENT_RESPONSE_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(response, ensure_ascii=False) + "\n")

        scene = response.get("scene") or packet.get("scene")
        status = response.get("status")
        feedback = response.get("feedback_action") if isinstance(response.get("feedback_action"), dict) else {}
        action = feedback.get("action", "none")
        self.root.after(
            0,
            lambda: self.status_label.configure(
                text=f"Agent sync {status}: scene={scene}, action={action}, url={self.agent_url}"
            ),
        )

    def play_video(self, path: Path) -> None:
        self.video_capture = cv2.VideoCapture(str(path))
        fps = self.video_capture.get(cv2.CAP_PROP_FPS) or 10
        delay_ms = max(20, int(1000 / fps))
        self._read_video_frame(delay_ms)

    def _read_video_frame(self, delay_ms: int) -> None:
        if self.video_capture is None:
            return

        ok, frame = self.video_capture.read()
        if not ok:
            self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.video_capture.read()
            if not ok:
                self.show_placeholder("视频读取失败")
                return

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        frame_index = max(0, int(self.video_capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1)
        timestamp_ms = float(self.video_capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
        fps = float(self.video_capture.get(cv2.CAP_PROP_FPS) or 10.0)
        timestamp = timestamp_ms / 1000.0 if timestamp_ms > 0 else frame_index / max(fps, 1.0)
        self._update_current_stream_frame(image, frame_index, timestamp)
        self.set_media_image(image)
        self.video_after_id = self.root.after(delay_ms, lambda: self._read_video_frame(delay_ms))

    def _update_current_stream_frame(self, image: Image.Image, frame_index: int, timestamp: float) -> None:
        scenario = self.active_scenario
        if scenario is None or not self._scenario_uses_live_agent_stream(scenario):
            return

        stream_dir = PANEL_OUTPUT_DIR / "live_agent_stream" / scenario.key
        stream_dir.mkdir(parents=True, exist_ok=True)
        latest_path = stream_dir / "latest.jpg"
        image.save(latest_path, "JPEG", quality=92)
        self.current_stream_frame_path = latest_path
        self.current_media_timestamp = timestamp
        self.current_media_frame_index = frame_index

    def show_image(self, path: Path) -> None:
        self.set_media_image(Image.open(path).convert("RGB"))

    def show_placeholder(self, message: str) -> None:
        image = Image.new("RGB", (1280, 720), (6, 16, 24))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1279, 719), outline=(68, 223, 255), width=3)
        draw.text((52, 300), message, fill=(232, 245, 255), spacing=10)
        self.set_media_image(image)

    def _set_live_camera_status(self, message: str, error: bool = False) -> None:
        if self.live_camera_label is not None:
            self.live_camera_label.configure(
                text=message,
                fg=self.colors["red"] if error else self.colors["muted"],
            )
        self.status_label.configure(text=message)

    def connect_live_camera(self) -> None:
        """连接已经打开并进入 Play 状态的 VirtualHome.exe。"""
        if self.active_scenario is None or self.active_scenario.key in LIVE_CAMERA_SCENARIOS:
            self.stop_video()
        try:
            from virtualhome.simulation.unity_simulator import comm_unity

            self.live_comm = comm_unity.UnityCommunication(
                port=LIVE_CAMERA_PORT,
                logging=False,
                timeout_wait=2,
            )
            ok, count = self.live_comm.camera_count()
            if not ok:
                raise RuntimeError("camera_count failed")
            self.live_camera_index = None
            self.live_camera_update_supported = True
            self._set_live_camera_status(f"Connected to VirtualHome on port {LIVE_CAMERA_PORT}; cameras={count}")
            if self.active_scenario is None or self.active_scenario.key in LIVE_CAMERA_SCENARIOS:
                self.reset_live_camera_view()
        except Exception as exc:
            self.live_comm = None
            self.live_camera_index = None
            self._set_live_camera_status(f"Live camera connection failed: {exc}", error=True)

    def reset_live_camera_view(self) -> None:
        """把 Unity 摄像机恢复到当前场景对应的推荐姿态。"""
        self._reset_media_transform()
        if self.live_comm is None:
            self.connect_live_camera()
            return

        try:
            self.live_camera_position, self.live_camera_rotation, self.live_camera_fov = self._compute_live_camera_pose()
            self._apply_live_camera_pose()
        except Exception as exc:
            self._set_live_camera_status(f"Reset live camera failed: {exc}", error=True)

    def rotate_live_camera(self, pitch_delta: float, yaw_delta: float) -> None:
        self._ensure_live_camera_ready()
        if self.live_comm is None:
            return
        self.live_camera_rotation[0] = clamp(self.live_camera_rotation[0] + pitch_delta, 15.0, 84.0)
        self.live_camera_rotation[1] = (self.live_camera_rotation[1] + yaw_delta) % 360.0
        self._apply_live_camera_pose()

    def move_live_camera(self, forward: float = 0.0, strafe: float = 0.0, up: float = 0.0) -> None:
        self._ensure_live_camera_ready()
        if self.live_comm is None:
            return

        yaw = math.radians(self.live_camera_rotation[1])
        forward_vec = [math.sin(yaw), 0.0, math.cos(yaw)]
        right_vec = [math.cos(yaw), 0.0, -math.sin(yaw)]
        self.live_camera_position[0] += forward_vec[0] * forward + right_vec[0] * strafe
        self.live_camera_position[1] = clamp(self.live_camera_position[1] + up, 1.0, 14.0)
        self.live_camera_position[2] += forward_vec[2] * forward + right_vec[2] * strafe
        self._apply_live_camera_pose()

    def zoom_live_camera(self, fov_delta: float) -> None:
        self._ensure_live_camera_ready()
        if self.live_comm is None:
            return
        self.live_camera_fov = clamp(self.live_camera_fov + fov_delta, 35.0, 95.0)
        self._apply_live_camera_pose()

    def _ensure_live_camera_ready(self) -> None:
        if self.active_scenario is None or self.active_scenario.key in LIVE_CAMERA_SCENARIOS:
            self.stop_video()
        if self.live_comm is None:
            self.connect_live_camera()

    def _compute_live_camera_pose(self) -> Tuple[List[float], List[float], float]:
        scenario = self.active_scenario
        if scenario is not None and scenario.room not in {"all_rooms", "all", "whole_home"}:
            pose = self._compute_room_pose(scenario.room)
            if pose is not None:
                return pose
        return self._compute_overview_pose()

    def _compute_room_pose(self, room: str) -> Optional[Tuple[List[float], List[float], float]]:
        if self.live_comm is None:
            return None

        room_class = {
            "living_room": "livingroom",
            "bedroom": "bedroom",
            "kitchen": "kitchen",
            "bathroom": "bathroom",
        }.get(str(room or "").strip().lower())
        if not room_class:
            return None

        ok, graph = self.live_comm.environment_graph()
        if not ok:
            return None

        for node in graph.get("nodes", []):
            if node.get("category") != "Rooms" or str(node.get("class_name", "")).lower() != room_class:
                continue
            bbox = node.get("bounding_box") or {}
            center = bbox.get("center")
            size = bbox.get("size")
            if not center or not size:
                return None
            span = max(float(size[0]), float(size[2]), 2.0)
            position = [float(center[0]), max(2.4, float(center[1]) + 3.0), float(center[2]) - span * 1.05]
            target = [float(center[0]), float(center[1]) + 1.0, float(center[2])]
            dx = target[0] - position[0]
            dy = target[1] - position[1]
            dz = target[2] - position[2]
            horizontal = math.sqrt(dx * dx + dz * dz)
            rotation = [
                math.degrees(math.atan2(-dy, horizontal)),
                math.degrees(math.atan2(dx, dz)),
                0.0,
            ]
            return position, rotation, 62.0
        return None

    def _compute_overview_pose(self) -> Tuple[List[float], List[float], float]:
        if self.live_comm is None:
            return [0.0, 8.0, -8.0], [58.0, 0.0, 0.0], 72.0

        ok, graph = self.live_comm.environment_graph()
        if not ok:
            return [0.0, 8.0, -8.0], [58.0, 0.0, 0.0], 72.0

        rooms = []
        for node in graph.get("nodes", []):
            if node.get("category") != "Rooms":
                continue
            bbox = node.get("bounding_box") or {}
            center = bbox.get("center")
            size = bbox.get("size")
            if center and size:
                rooms.append((center, size))

        if not rooms:
            return [0.0, 8.0, -8.0], [58.0, 0.0, 0.0], 72.0

        min_x = min(center[0] - size[0] / 2 for center, size in rooms)
        max_x = max(center[0] + size[0] / 2 for center, size in rooms)
        min_z = min(center[2] - size[2] / 2 for center, size in rooms)
        max_z = max(center[2] + size[2] / 2 for center, size in rooms)
        center_x = (min_x + max_x) / 2
        center_z = (min_z + max_z) / 2
        span = max(max_x - min_x, max_z - min_z, 1.0)

        position = [center_x, 8.0, min_z - span * 0.45]
        target = [center_x, 1.0, center_z]
        dx = target[0] - position[0]
        dy = target[1] - position[1]
        dz = target[2] - position[2]
        horizontal = math.sqrt(dx * dx + dz * dz)
        rotation = [
            math.degrees(math.atan2(-dy, horizontal)),
            math.degrees(math.atan2(dx, dz)),
            0.0,
        ]
        return position, rotation, 72.0

    def _apply_live_camera_pose(self) -> None:
        if self.live_comm is None:
            return

        position = [float(value) for value in self.live_camera_position]
        rotation = [float(value) for value in self.live_camera_rotation]
        fov = float(self.live_camera_fov)

        try:
            if self.live_camera_index is None or not self.live_camera_update_supported:
                self._add_live_camera_pose(position, rotation, fov)
            else:
                try:
                    ok, message = self.live_comm.update_camera(
                        self.live_camera_index,
                        position=position,
                        rotation=rotation,
                        field_view=fov,
                    )
                except Exception as exc:
                    if not self._should_fallback_to_add_camera(str(exc)):
                        raise
                    ok, message = False, str(exc)

                if not ok:
                    if self._should_fallback_to_add_camera(str(message)):
                        self.live_camera_update_supported = False
                        self._add_live_camera_pose(position, rotation, fov)
                    else:
                        raise RuntimeError(f"update_camera failed: {message}")

            self._capture_live_camera_frame()
        except Exception as exc:
            self._set_live_camera_status(f"Live camera update failed: {exc}", error=True)

    @staticmethod
    def _should_fallback_to_add_camera(message: str) -> bool:
        text = message.lower()
        return "unknown action update_camera" in text or "update_camera" in text or "camera" in text

    def _add_live_camera_pose(self, position: List[float], rotation: List[float], fov: float) -> None:
        """部分预编译 VirtualHome 不支持 update_camera，按键刷新时改为新增摄像机。"""
        if self.live_comm is None:
            return
        ok, before_count = self.live_comm.camera_count()
        if not ok:
            raise RuntimeError("camera_count failed before add_camera")
        ok, message = self.live_comm.add_camera(position=position, rotation=rotation, field_view=fov)
        if not ok:
            raise RuntimeError(f"add_camera failed: {message}")
        camera_index = parse_camera_id(message)
        self.live_camera_index = camera_index if camera_index is not None else before_count

    def _capture_live_camera_frame(self) -> None:
        if self.live_comm is None or self.live_camera_index is None:
            return

        width, height = LIVE_CAMERA_SIZE
        ok, images = self.live_comm.camera_image(
            [self.live_camera_index],
            mode="normal",
            image_width=width,
            image_height=height,
        )
        if not ok or not images:
            raise RuntimeError("camera_image failed")

        frame = images[0]
        if frame.ndim == 3 and frame.shape[2] == 3:
            image = Image.fromarray(frame[:, :, ::-1])
        else:
            image = Image.fromarray(frame)

        live_dir = PANEL_OUTPUT_DIR / "live_overview"
        live_dir.mkdir(parents=True, exist_ok=True)
        latest_path = live_dir / "latest_overview_camera.jpg"
        image.save(latest_path, "JPEG", quality=95)
        self.set_media_image(image)
        self._set_live_camera_status(
            "Live camera "
            f"id={self.live_camera_index} pos={','.join(f'{v:.1f}' for v in self.live_camera_position)} "
            f"rot={','.join(f'{v:.1f}' for v in self.live_camera_rotation)} fov={self.live_camera_fov:.0f} "
            f"mode={'update' if self.live_camera_update_supported else 'add-camera'}"
        )

    def set_media_image(self, image: Image.Image) -> None:
        self.last_pil_image = image
        self._draw_media_image(image)

    def _refresh_live_camera_after_agent_control(self) -> None:
        if self.active_scenario is None:
            return
        if self.active_scenario.key not in LIVE_CAMERA_SCENARIOS:
            return
        if self.live_comm is None:
            return
        try:
            mtime = DEVICE_STATE_FILE.stat().st_mtime
        except OSError:
            return
        if mtime <= self.device_state_mtime:
            return
        self.device_state_mtime = mtime
        try:
            if self.live_camera_index is None:
                self.reset_live_camera_view()
            else:
                self._capture_live_camera_frame()
        except Exception as exc:
            self._set_live_camera_status(f"Live camera refresh after Agent control failed: {exc}", error=True)

    def _resize_media(self, _event: tk.Event) -> None:
        if self.last_pil_image is not None:
            self._draw_media_image(self.last_pil_image)

    def _draw_media_image(self, image: Image.Image) -> None:
        # 静态图像支持平移/缩放；01 场景连接模拟器后，VIEW CAMERA 按键会刷新真实 Unity 摄像机画面。
        canvas_w = max(320, self.media_canvas.winfo_width() or 900)
        canvas_h = max(220, self.media_canvas.winfo_height() or 506)
        max_w = max(240, canvas_w - 24)
        max_h = max(160, canvas_h - 24)

        source = image
        base_scale = min(max_w / source.width, max_h / source.height)
        final_scale = max(0.05, base_scale * self.media_zoom)
        target_size = (
            max(1, int(round(source.width * final_scale))),
            max(1, int(round(source.height * final_scale))),
        )
        display = source.resize(target_size, Image.Resampling.LANCZOS)
        self.current_image = ImageTk.PhotoImage(display)

        self.media_canvas.delete("all")
        self.media_canvas.create_rectangle(1, 1, canvas_w - 2, canvas_h - 2, outline=self.colors["line"], width=1)
        pan_x, pan_y = self.media_pan
        center_x = canvas_w // 2 + pan_x
        center_y = canvas_h // 2 + pan_y
        self.media_canvas.create_image(center_x, center_y, image=self.current_image, anchor="center")
        image_box = (
            center_x - target_size[0] // 2,
            center_y - target_size[1] // 2,
            center_x + target_size[0] // 2,
            center_y + target_size[1] // 2,
        )
        self._draw_media_overlay(canvas_w, canvas_h, image_box)
        if SHOW_AGENT_DEVICE_OVERLAY:
            self._draw_agent_device_overlay(image_box)
        if self.active_scenario and (
            self.active_scenario.key in LIVE_CAMERA_SCENARIOS
            or self.current_stream_frame_path is not None
        ):
            if self.active_scenario.key not in LIVE_CAMERA_SCENARIOS:
                hint = "scenario camera stream | sending displayed frames to Agent"
            elif self.live_comm is not None and self.live_camera_index is not None:
                hint = "Unity live camera | VIEW CAMERA buttons rotate/move | Reset View"
            else:
                hint = "static preview | left-drag pan | wheel zoom | Connect for Unity camera"
            self.media_canvas.create_text(
                18,
                canvas_h - 22,
                text=f"{hint} | zoom={self.media_zoom:.1f}x",
                anchor="w",
                fill=self.colors["muted"],
                font=("Consolas", 9),
            )

    def _read_agent_device_state(self) -> Dict[str, object]:
        if not DEVICE_STATE_FILE.exists():
            return normalize_device_state({})
        try:
            value = json.loads(DEVICE_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return normalize_device_state({})
        return normalize_device_state(value if isinstance(value, dict) else {})

    def _draw_agent_device_overlay(self, image_box: Tuple[int, int, int, int]) -> None:
        scenario_key = self.active_scenario.key if self.active_scenario is not None else ""
        if scenario_key not in {"whole_home_overview", "multi_camera_layout"}:
            return

        state = self._read_agent_device_state()
        lights = state.get("lights") if isinstance(state.get("lights"), dict) else {}
        speakers = state.get("speakers") if isinstance(state.get("speakers"), dict) else {}
        if not lights and not speakers:
            return

        speaker_value = speakers.get(WHOLE_HOME_SPEAKER) if isinstance(speakers, dict) else None
        if isinstance(speaker_value, dict):
            speaker_state = str(speaker_value.get("state") or "stop").lower()
            speaker_track = str(speaker_value.get("track") or "")
        else:
            speaker_state = str(speaker_value or "stop").lower()
            speaker_track = ""

        x0, y0, x1, y1 = image_box
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        room_boxes = {
            "living_room": (0.05, 0.08, 0.48, 0.45, "客厅"),
            "bedroom": (0.52, 0.08, 0.95, 0.45, "卧室"),
            "kitchen": (0.05, 0.55, 0.48, 0.92, "厨房"),
            "bathroom": (0.52, 0.55, 0.95, 0.92, "卫生间"),
        }

        for room, (rx0, ry0, rx1, ry1, label) in room_boxes.items():
            target = f"{room}_ceiling_light"
            light_value = str(lights.get(target, "unknown")).lower()

            left = x0 + int(width * rx0)
            top = y0 + int(height * ry0)
            right = x0 + int(width * rx1)
            bottom = y0 + int(height * ry1)
            if light_value == "on":
                fill = "#f4c95d"
                outline = "#ffe08a"
                stipple = "gray25"
                light_text = "灯光 开"
            elif light_value == "off":
                fill = "#05070a"
                outline = "#415166"
                stipple = "gray50"
                light_text = "灯光 关"
            else:
                fill = "#17212b"
                outline = "#526476"
                stipple = "gray75"
                light_text = "灯光 未设置"

            self.media_canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                fill=fill,
                outline=outline,
                width=2,
                stipple=stipple,
            )
            lines = [label, light_text]
            self.media_canvas.create_text(
                left + 10,
                top + 10,
                text="\n".join(lines),
                anchor="nw",
                fill="#f8fafc",
                font=("Microsoft YaHei UI", 10, "bold"),
            )

        if speaker_state in {"playing", "play", "on"}:
            music_text = f"全屋音乐 播放中" + (f"：{speaker_track}" if speaker_track else "")
        elif speaker_state == "pause":
            music_text = "全屋音乐 暂停"
        else:
            music_text = "全屋音乐 关闭"
        self.media_canvas.create_text(
            x0 + 12,
            y1 - 40,
            text=music_text,
            anchor="w",
            fill="#f8fafc",
            font=("Microsoft YaHei UI", 10, "bold"),
        )

    def _draw_media_overlay(self, canvas_w: int, canvas_h: int, image_box: Tuple[int, int, int, int]) -> None:
        phase = self.animation_phase
        pulse = (math.sin(phase * 0.18) + 1.0) / 2.0

        x0, y0, x1, y1 = image_box
        bracket = 46
        corner_color = mix_hex(self.colors["cyan"], self.colors["green"], pulse * 0.5)
        corners = [
            ((x0, y0), (x0 + bracket, y0), (x0, y0 + bracket)),
            ((x1, y0), (x1 - bracket, y0), (x1, y0 + bracket)),
            ((x0, y1), (x0 + bracket, y1), (x0, y1 - bracket)),
            ((x1, y1), (x1 - bracket, y1), (x1, y1 - bracket)),
        ]
        for origin, horizontal, vertical in corners:
            self.media_canvas.create_line(origin[0], origin[1], horizontal[0], horizontal[1], fill=corner_color, width=3)
            self.media_canvas.create_line(origin[0], origin[1], vertical[0], vertical[1], fill=corner_color, width=3)

    def _reset_media_transform(self) -> None:
        self.media_zoom = 1.0
        self.media_pan = (0, 0)
        self.drag_start = None

    def _can_transform_media(self) -> bool:
        return self.active_scenario is not None and self.active_scenario.media_type == "image"

    def _start_pan(self, event: tk.Event) -> None:
        if self._can_transform_media():
            self.drag_start = (event.x, event.y)

    def _drag_pan(self, event: tk.Event) -> None:
        if not self._can_transform_media() or self.drag_start is None:
            return
        last_x, last_y = self.drag_start
        pan_x, pan_y = self.media_pan
        self.media_pan = (pan_x + event.x - last_x, pan_y + event.y - last_y)
        self.drag_start = (event.x, event.y)
        if self.last_pil_image is not None:
            self._draw_media_image(self.last_pil_image)

    def _end_pan(self, _event: tk.Event) -> None:
        self.drag_start = None

    def _zoom_media(self, event: tk.Event) -> None:
        if not self._can_transform_media():
            return
        delta = 1 if getattr(event, "delta", 0) > 0 or getattr(event, "num", None) == 4 else -1
        factor = 1.12 if delta > 0 else 1 / 1.12
        self.media_zoom = min(3.5, max(0.8, self.media_zoom * factor))
        if self.last_pil_image is not None:
            self._draw_media_image(self.last_pil_image)

    def reset_media_view(self) -> None:
        self._reset_media_transform()
        if self.active_scenario and self.active_scenario.key in LIVE_CAMERA_SCENARIOS and self.live_comm is not None:
            self.reset_live_camera_view()
            return
        if self.last_pil_image is not None:
            self._draw_media_image(self.last_pil_image)

    def _set_sound_button_label(self) -> None:
        if self.sound_button is not None:
            self.sound_button.configure(text=f"Sound: {'ON' if self.sound_enabled else 'OFF'}")

    def toggle_sound(self) -> None:
        self.sound_enabled = not self.sound_enabled
        self._set_sound_button_label()
        self.stop_audio()

    def _schedule_audio_for_scenario(self, scenario: ShowcaseScenario, immediate: bool = False) -> None:
        # Sample audio is intentionally not scheduled here. Health-scene music
        # must be started/stopped only through Agent -> device_state feedback,
        # otherwise scenario 06 can play two overlapping sources.
        return

    def _sync_agent_music_playback(self) -> None:
        if not self.sound_enabled:
            return
        state = self._read_agent_device_state()
        speakers = state.get("speakers") if isinstance(state.get("speakers"), dict) else {}
        speaker = speakers.get(WHOLE_HOME_SPEAKER) if isinstance(speakers, dict) else {}
        if not isinstance(speaker, dict):
            speaker = {}
        speaker_state = str(speaker.get("state") or "stop").lower()
        if speaker_state not in {"playing", "play", "on"}:
            self.missing_music_signature = ""
            if self.agent_music_signature or self.audio_player.active or self.audio_player.has_registered_process():
                self.stop_audio()
            return

        requested_track = str(speaker.get("track") or "")
        path = resolve_music_path(requested_track)
        if path is None:
            missing_signature = normalize_music_query(requested_track)
            if missing_signature and missing_signature != self.missing_music_signature:
                print(f"[audio] Music track not found in {MUSIC_DIR}: {requested_track}. Current audio stopped.")
                self.missing_music_signature = missing_signature
            if self.agent_music_signature or self.audio_player.active or self.audio_player.has_registered_process():
                self.stop_audio()
            return
        self.missing_music_signature = ""
        signature = str(path.resolve())
        if signature == self.agent_music_signature:
            return
        if self._play_audio(path, loop=True):
            self.agent_music_signature = signature

    def _play_audio(self, path: Path, loop: bool = False) -> bool:
        if not self.sound_enabled:
            return False
        try:
            self.audio_player.play(path, loop=loop)
            return True
        except Exception as exc:
            if path.suffix.lower() != ".wav" or winsound is None:
                self._set_live_camera_status(f"Music playback failed: {exc}", error=True)
                return False

        flags = winsound.SND_FILENAME | winsound.SND_ASYNC
        if loop:
            flags |= winsound.SND_LOOP
        winsound.PlaySound(str(path), flags)
        return True

    def stop_audio(self) -> None:
        for after_id in self.audio_after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.audio_after_ids.clear()
        self.agent_music_signature = ""
        self.audio_player.stop()
        if winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)

    def stop_video(self) -> None:
        if self.video_after_id is not None:
            self.root.after_cancel(self.video_after_id)
            self.video_after_id = None
        if self.video_capture is not None:
            self.video_capture.release()
            self.video_capture = None

    def export_samples(self) -> None:
        sample_dir = export_interface_samples()
        messagebox.showinfo("导出完成", f"接口样例已写入:\n{sample_dir}")

    def open_output_dir(self) -> None:
        PANEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(PANEL_OUTPUT_DIR)

    def close(self) -> None:
        if self.animation_after_id is not None:
            try:
                self.root.after_cancel(self.animation_after_id)
            except tk.TclError:
                pass
            self.animation_after_id = None
        self.stop_video()
        self.stop_audio()
        self.stop_live_agent_stream()
        if self.live_comm is not None:
            try:
                self.live_comm.close()
            except Exception:
                pass
            self.live_comm = None
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VirtualHome local showcase panel")
    parser.add_argument("--export-samples", action="store_true", help="Export interface samples and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.export_samples:
        sample_dir = export_interface_samples()
        print(f"exported interface samples: {sample_dir}")
        return

    root = tk.Tk()
    app = ShowcasePanel(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
