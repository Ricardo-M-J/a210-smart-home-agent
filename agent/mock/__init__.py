"""Mock 家居状态快照数据。

覆盖「有人/无人 × 灯亮/灯灭 × 白天/夜间」的典型组合，
供本地开发与命令行闭环使用；真实上板后由队友的感知进程写文件替代。
"""
import json
from pathlib import Path

_MOCK_DIR = Path(__file__).resolve().parent

# 场景 key -> 家居状态快照（严格遵循 schema/home_state_schema.json 契约）
SCENARIOS = {
    # —— 白天 ——
    "day_person_on": {
        "timestamp": "2026-08-20 14:30:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 1, "pose": "standing"},
                {"category": "light", "state": "on"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    "day_person_off": {
        "timestamp": "2026-08-20 15:00:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 1, "pose": "sitting"},
                {"category": "light", "state": "off"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    "day_nobody_on": {
        "timestamp": "2026-08-20 11:20:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "on"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    "day_nobody_off": {
        "timestamp": "2026-08-20 10:10:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    # —— 夜间 ——
    "night_person_on": {
        "timestamp": "2026-08-20 23:10:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 1, "pose": "sitting"},
                {"category": "light", "state": "on"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    "night_person_off": {
        "timestamp": "2026-08-20 22:40:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 1, "pose": "standing"},
                {"category": "light", "state": "off"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    # 独居安全核心：无人但灯亮（忘关灯告警）
    "night_nobody_on": {
        "timestamp": "2026-08-20 23:10:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "on"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    "night_nobody_off": {
        "timestamp": "2026-08-20 23:30:00",
        "rooms": [
            {"room": "客厅", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
            {"room": "卧室", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
    # 独居安全核心：有人躺着（跌倒/晕倒关注）
    "night_lying": {
        "timestamp": "2026-08-20 23:45:00",
        "rooms": [
            {"room": "卧室", "objects": [
                {"category": "person", "count": 1, "pose": "lying"},
                {"category": "light", "state": "off"},
            ]},
            {"room": "客厅", "objects": [
                {"category": "person", "count": 0, "pose": None},
                {"category": "light", "state": "off"},
            ]},
        ],
    },
}

DEFAULT_SCENE = "night_nobody_on"


def load_scene(name: str = DEFAULT_SCENE) -> dict:
    """按场景名返回快照（深拷贝，避免调用方污染常量）。"""
    return json.loads(json.dumps(SCENARIOS[name]))


def write_scene(name: str = DEFAULT_SCENE, path: Path | None = None) -> Path:
    """把场景写入快照文件（模拟感知进程原子写）。

    默认写入 config.HOME_STATE_FILE（与 reader 读取的是同一路径），
    保证 mock 与上板 real 的读写路径一致，避免迁移时写读脱钩。
    """
    import config

    target = Path(path) if path else Path(config.HOME_STATE_FILE)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(load_scene(name), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)  # 原子替换
    return target
