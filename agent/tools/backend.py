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
            "frame_id": f"frame@{state.get('timestamp', 'unknown')}",
            "note": "Mock 模式：无真实摄像头，以家居状态快照代表画面",
        }

    def latest_frame(self) -> dict:
        # Mock 下 latest 与 capture 同源（读快照）
        return self.capture()

    def infer(self) -> dict:
        state = self._state()
        if "error" in state:
            return {"status": "error", "detail": state["error"]}
        detections = []
        for room in state.get("rooms", []):
            for obj in room.get("objects", []):
                detections.append({"room": room["room"], **obj})
        return {
            "status": "ok",
            "timestamp": state.get("timestamp"),
            "detections": detections,
            "note": "Mock 模式：无真实 YOLO，以快照代表检测结果",
        }


class RealBackend(Backend):
    """真实后端：上板后调用队友封装的采集/推理接口。

    TODO（等队友接口冻结后填充）：
        capture()       -> 调用队友摄像头采集模块，返回真实一帧
        latest_frame()  -> 读摄像头最新缓存帧
        infer()         -> 调用队友 YOLO 推理接口，返回真实检测结果
    """

    def capture(self) -> dict:
        raise NotImplementedError("待接队友采集接口")

    def latest_frame(self) -> dict:
        raise NotImplementedError("待接队友采集接口")

    def infer(self) -> dict:
        raise NotImplementedError("待接队友推理接口")


def get_backend() -> Backend:
    """按配置返回后端实例。"""
    if config.BACKEND == "real":
        return RealBackend()
    return MockBackend()
