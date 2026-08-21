"""运行时装配：把 Agent、模拟感知进程、事件监控装配成共享单例，供 Web 使用。

- Agent：一个共享实例，多轮对话记忆持续存在（加锁保证线程安全）
- PerceptionSimulator：后台模拟感知层持续写快照
- EventMonitor：后台轮询快照 → 事件引擎检测 → Agent 决策 → 告警入缓冲 + 落库
"""
import threading
import time

import config
from agent import Agent
from event_engine import EventEngine
from memory import Memory
from simulator import PerceptionSimulator
from tools.reader import read_home_state

_agent: Agent | None = None
_simulator: PerceptionSimulator | None = None
_monitor: "EventMonitor | None" = None
_alerts: list[dict] = []
_alerts_lock = threading.Lock()


def push_alert(severity: str, summary: str, response: str) -> None:
    """向 Web 告警面板推一条告警（线程安全，保留最近 100 条）。"""
    alert = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "severity": severity,
        "summary": summary,
        "response": response,
    }
    with _alerts_lock:
        _alerts.append(alert)
        del _alerts[:-100]


class EventMonitor(threading.Thread):
    """后台线程：持续检测异常事件并触发 Agent 决策告警。"""

    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True)
        self.interval = interval
        self.engine = EventEngine()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            state = read_home_state()
            for event in self.engine.detect(state):
                self._handle_event(event)
            self._stop.wait(self.interval)

    @staticmethod
    def _handle_event(event: dict) -> None:
        # 落库疑似事件（severity 标记为 suspicious，最终是否告警由 LLM 二次判断）
        Memory().log_event({
            "event_type": "rule_match",
            "key": event.get("room"),
            "severity": "suspicious",
            "summary": event.get("summary"),
        })
        # Agent 二次判断：若 LLM 判断需告警，会调 make_decision 推入告警面板
        get_agent().on_event(event)


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent()
    return _agent


def get_simulator() -> PerceptionSimulator | None:
    """返回模拟感知进程。上板 real 模式返回 None（由队友真实进程接管）。"""
    global _simulator
    if config.BACKEND == "real":
        return None
    if _simulator is None:
        _simulator = PerceptionSimulator()
        _simulator.write_once()  # 先同步写一次快照，避免监控线程读到残留旧文件
        _simulator.start()
    return _simulator


def get_monitor() -> EventMonitor:
    global _monitor
    if _monitor is None:
        _monitor = EventMonitor()
        _monitor.start()
    return _monitor


def start() -> None:
    """按 BACKEND 装配运行时：mock 起模拟器 + 监控；real 只起监控（读真实快照）。"""
    get_simulator()
    get_monitor()


def get_alerts(limit: int = 50) -> list[dict]:
    with _alerts_lock:
        return list(_alerts[-limit:])
