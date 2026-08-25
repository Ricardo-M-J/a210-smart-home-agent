"""端侧动作后端：把「真实采集/推理」抽象成可替换接口。

设计目的（对应赛题"评分隐患"）：
    Tool 必须有「主动触发端侧动作」的能力，而不是只会读现成文件。
    本模块定义采集(capture)/推理(infer)接口；Mock 阶段用读快照兜底，
    上板后由队友封装的真实接口替换，Tool 层代码不变。

后端选择：config.BACKEND  ∈ {"mock", "real"}，默认 mock。
"""

import config


class Backend:
    """端侧动作抽象接口。上板后实现这三个方法，Tool 层即可切换。"""

    def capture(self) -> dict:
        """主动采集一帧，返回画面信息（fresh 路径）。"""
        raise NotImplementedError

    def latest_frame(self) -> dict:
        """读最近一帧缓存（latest 路径，性能优化）。"""
        raise NotImplementedError

    def infer(self) -> dict:
        """触发一次端侧视觉推理，返回结构化检测结果。"""
        raise NotImplementedError


    def home_state(self) -> dict:
        """Return the current home-state snapshot for monitor polling."""
        raise NotImplementedError

    def apply_feedback(self, conclusion: str, action: str, message: str, record: dict | None = None) -> dict:
        """Optionally send an agent decision back to the environment."""
        return {"status": "ignored", "detail": "backend does not support scene feedback"}

    def list_scenes(self) -> list[str]:
        return []

    def set_scene(self, scene: str) -> bool:
        return False

    def ingest_virtualhome_frame(self, payload: dict) -> dict:
        return {"status": "ignored", "detail": "backend does not accept VirtualHome frames"}

    def latest_feedback(self, limit: int = 20) -> list[dict]:
        return []

    def control_virtualhome(
        self,
        room: str,
        device: str,
        command: str,
        value: str | None = None,
        source_text: str | None = None,
    ) -> dict:
        return {"status": "ignored", "detail": "backend does not support VirtualHome controls"}


class MockBackend(Backend):
    """Mock 后端：无真实摄像头/YOLO，用快照文件代表画面与检测结果。"""

    @staticmethod
    def _state() -> dict:
        from tools.reader import read_home_state
        return read_home_state()

    def capture(self) -> dict:
        state = self._state()
        if "error" in state:
            return {"status": "error", "detail": state["error"]}
        return {
            "status": "ok",
            "frame_id": f"frame@{state.get('timestamp_ms', 'unknown')}",
            "note": "Mock 模式：无真实摄像头，以家居状态快照代表画面",
        }

    def latest_frame(self) -> dict:
        # Mock 下 latest 与 capture 同源（读快照）
        return self.capture()

    def infer(self) -> dict:
        state = self._state()
        if "error" in state:
            return {"status": "error", "detail": state["error"]}
        return {
            "status": "ok",
            "timestamp_ms": state.get("timestamp_ms"),
            "rooms": state.get("rooms", {}),
            "note": "Mock 模式：无真实 YOLO，以快照代表检测结果",
        }


    def home_state(self) -> dict:
        return self._state()

    def list_scenes(self) -> list[str]:
        from mock import SCENARIOS

        return list(SCENARIOS.keys())

    def set_scene(self, scene: str) -> bool:
        from mock import SCENARIOS, write_scene

        if scene not in SCENARIOS:
            return False
        write_scene(scene)
        return True


class RealBackend(Backend):
    """真实后端：上板后读队友 C++ 写的全屋快照文件。

    capture/latest_frame/infer 都读 HOME_STATE_FILE（队友原子写 /tmp/home_state.json）。
    Mock 和 Real 的差异只在快照来源：Mock 是本地模拟器写，Real 是队友 C++ 写。
    """

    @staticmethod
    def _state() -> dict:
        from tools.reader import read_home_state
        return read_home_state()

    def capture(self) -> dict:
        state = self._state()
        if "error" in state:
            return {"status": "error", "detail": state["error"]}
        return {"status": "ok", "frame_id": f"frame@{state.get('timestamp_ms', 'unknown')}"}

    def latest_frame(self) -> dict:
        return self.capture()

    def infer(self) -> dict:
        state = self._state()
        if "error" in state:
            return {"status": "error", "detail": state["error"]}
        return {
            "status": "ok",
            "timestamp_ms": state.get("timestamp_ms"),
            "rooms": state.get("rooms", {}),
        }


    def home_state(self) -> dict:
        return self._state()


class VirtualHomeBackend(Backend):
    """VirtualHome backend: consume virtual camera frames and scene result JSONL files."""

    def __init__(self):
        from tools.virtualhome_adapter import VirtualHomeAdapter

        self.adapter = VirtualHomeAdapter.from_config()

    def capture(self) -> dict:
        return self.adapter.capture()

    def latest_frame(self) -> dict:
        return self.adapter.latest_frame()

    def infer(self) -> dict:
        return self.adapter.infer()

    def home_state(self) -> dict:
        return self.adapter.home_state()

    def apply_feedback(self, conclusion: str, action: str, message: str, record: dict | None = None) -> dict:
        return self.adapter.apply_feedback(conclusion, action, message, record)

    def list_scenes(self) -> list[str]:
        return self.adapter.list_scenes()

    def set_scene(self, scene: str) -> bool:
        return self.adapter.set_scene(scene)

    def ingest_virtualhome_frame(self, payload: dict) -> dict:
        return self.adapter.ingest_frame(payload)

    def latest_feedback(self, limit: int = 20) -> list[dict]:
        return self.adapter.latest_feedback(limit)

    def control_virtualhome(
        self,
        room: str,
        device: str,
        command: str,
        value: str | None = None,
        source_text: str | None = None,
    ) -> dict:
        return self.adapter.control_device(room, device, command, value, source_text)


def get_backend() -> Backend:
    """按配置返回后端实例。"""
    backend = config.BACKEND.lower()
    if backend == "real":
        return RealBackend()
    if backend == "virtualhome":
        return VirtualHomeBackend()
    return MockBackend()
