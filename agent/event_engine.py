"""事件引擎：读取「监控规则表」，用通用条件匹配发现「疑似事件」。

两级判断架构（对应赛题"端云协同 + Agent 自主判断"）：
    第一级（本模块，确定性、零成本、可离线）：按规则表扫全屋快照，产出「疑似事件」。
    第二级（Agent，云端 LLM）：收到疑似事件后做最终判断，决定是否告警。

核心设计：规则不是硬编码的枚举，而是 LLM 从用户指令生成的条件字典（when）。
本模块只提供一个通用的 check() 匹配器，不预设任何"异常类型"。

边沿触发：规则从「未命中」变为「命中」才上报一次，持续命中不重复；
        消失后再次命中才重新上报，避免反复告警。
"""
from datetime import datetime

from memory import Memory

# 房间英文 -> 中文（展示用）
ROOM_CN = {
    "living_room": "客厅",
    "bedroom1": "卧室1",
    "bedroom2": "卧室2",
    "kitchen": "厨房",
    "bathroom": "卫生间",
}

# 房间级信号字段（快照每个房间都有）
ROOM_FIELDS = ("has_person", "has_cat", "has_dog", "fall_like")


def is_night(timestamp_ms: int) -> bool:
    """从毫秒时间戳判断是否夜间（22:00–06:00）。"""
    try:
        hour = datetime.fromtimestamp(timestamp_ms / 1000).hour
    except (OSError, ValueError, OverflowError):
        return False
    return hour >= 22 or hour < 6


def _room_matches(room_state: dict, when: dict) -> bool:
    """判断单个房间状态是否满足 when 的所有房间级条件。"""
    for field in ROOM_FIELDS:
        if field in when and room_state.get(field) != when[field]:
            return False
    return True


def check(state: dict, when: dict) -> str | None:
    """判断全屋快照是否满足规则条件，返回命中的房间名（英文），未命中返回 None。

    when 可含字段：
        room        指定房间（英文枚举）；省略则匹配任意房间
        is_night    全局条件：是否夜间
        has_person / has_cat / has_dog / fall_like  房间级条件
    """
    if not state or "error" in state:
        return None

    # 全局条件
    if "is_night" in when:
        if is_night(state.get("timestamp_ms", 0)) != when["is_night"]:
            return None

    rooms = state.get("rooms", {})
    if not isinstance(rooms, dict):
        return None

    # 指定房间 / 任意房间
    candidates = [when["room"]] if when.get("room") else list(rooms.keys())
    for name in candidates:
        room_state = rooms.get(name)
        if room_state and _room_matches(room_state, when):
            return name
    return None


class EventEngine:
    def __init__(self):
        # key -> 该规则在对应房间当前是否处于「命中」状态（边沿触发的记忆）
        self._active: set[str] = set()

    def detect(self, state: dict) -> list[dict]:
        """按规则表检测当前快照，返回疑似事件列表（不带 severity）。"""
        if "error" in state:
            return []

        events: list[dict] = []
        current_hits: set[str] = set()

        for rule in Memory().list_rules(active_only=True):
            when = rule.get("when") or {}
            requires_mode = rule.get("requires_mode")
            # 模式前置：规则指定了 requires_mode 时，只有当前模式匹配才检测
            if requires_mode and Memory().get_home_mode() != requires_mode:
                continue

            room = check(state, when)
            if room is None:
                continue

            key = f"{rule['id']}:{room}"
            current_hits.add(key)
            if key in self._active:
                continue  # 持续命中，不重复上报
            self._active.add(key)
            events.append({
                "rule_id": rule["id"],
                "room": room,
                "rule_description": rule.get("description") or "",
                "summary": f"{ROOM_CN.get(room, room)}：命中规则「{rule.get('description') or '未命名'}」",
            })

        # 状态消失的 key 从 active 移出，下次再命中时重新触发
        self._active = current_hits
        return events
