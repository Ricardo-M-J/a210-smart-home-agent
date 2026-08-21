"""模拟感知进程：模拟「摄像头持续采集 + 端侧检测」的感知层。

真实架构里，感知层是队友的独立进程：摄像头持续采集 → YOLO 检测 → 原子写快照文件。
本地没有摄像头/YOLO，用本模块模拟这个进程的行为：

- 后台线程按固定间隔，把「当前场景」的快照原子写入 HOME_STATE_FILE
- 支持运行时切换场景，模拟「有人进入/离开、灯开关」等状态变化
- 上板后，本模块被队友的真实感知进程替代，Agent/Web 代码不变（只换写文件的一方）

这正好演练了「文件 IPC」契约：Agent 只认快照文件，不关心写入方是谁。
"""
import threading
import time

import config
from mock import SCENARIOS, write_scene


class PerceptionSimulator(threading.Thread):
    """后台线程：周期性把当前场景写入快照文件，模拟感知层持续输出。"""

    def __init__(self, scene: str = "day_nobody_off", interval: float = 1.0):
        super().__init__(daemon=True)
        self.scene = scene
        self.interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def set_scene(self, scene: str) -> bool:
        if scene not in SCENARIOS:
            return False
        with self._lock:
            self.scene = scene
        return True

    def get_scene(self) -> str:
        with self._lock:
            return self.scene

    def stop(self) -> None:
        self._stop.set()

    def write_once(self) -> None:
        """同步写一次当前场景快照（供启动时调用，消除竞态）。"""
        with self._lock:
            scene = self.scene
        write_scene(scene)

    def run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                scene = self.scene
            write_scene(scene)
            self._stop.wait(self.interval)
