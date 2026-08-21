"""Mock 家居状态快照数据。

对齐队友板端快照格式（全屋聚合 + 房间信号字段），
供本地开发与命令行闭环使用；真实上板后由队友的 C++ 写文件替代。

快照格式：
{
  "timestamp_ms": 123456789,
  "rooms": {
    "kitchen": {"has_person": false, "has_cat": true, "has_dog": false, "fall_like": false},
    ...
  }
}
"""
import json
from pathlib import Path

_MOCK_DIR = Path(__file__).resolve().parent

# 五个房间（队友枚举）
_ROOMS = ["living_room", "bedroom1", "bedroom2", "kitchen", "bathroom"]


def _rooms(**overrides) -> dict:
    """构造一个全屋快照，默认全空，用 overrides 覆盖指定房间的信号。"""
    base = {r: {"has_person": False, "has_cat": False, "has_dog": False, "fall_like": False} for r in _ROOMS}
    for room, patch in overrides.items():
        base[room].update(patch)
    return base


# 场景 key -> 家居状态快照
SCENARIOS = {
    # 白天正常：客厅有人
    "day_normal": {
        "timestamp_ms": 1755670800000,  # 2026-08-20 14:30 左右
        "rooms": _rooms(living_room={"has_person": True}),
    },
    # 厨房有猫无人（宠物危险）
    "pet_in_kitchen": {
        "timestamp_ms": 1755670800000,
        "rooms": _rooms(kitchen={"has_cat": True}),
    },
    # 卧室有人跌倒
    "fall_in_bedroom": {
        "timestamp_ms": 1755702000000,  # 夜间 23:00 左右
        "rooms": _rooms(bedroom1={"has_person": True, "fall_like": True}),
    },
    # 夜间全屋无人
    "night_empty": {
        "timestamp_ms": 1755702000000,
        "rooms": _rooms(),
    },
    # 夜间有人进入客厅
    "night_person_enter": {
        "timestamp_ms": 1755702000000,
        "rooms": _rooms(living_room={"has_person": True}),
    },
}

DEFAULT_SCENE = "pet_in_kitchen"


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
