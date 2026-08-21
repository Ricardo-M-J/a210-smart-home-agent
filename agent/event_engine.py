"""事件引擎：读取「监控规则表」，用确定性检查发现「疑似事件」。

两级判断架构（对应赛题"端云协同 + Agent 自主判断"）：
    第一级（本模块，确定性、零成本、可离线）：按规则表扫快照，产出「疑似事件」——
        只描述"检测到了什么可疑现象"，不判断"要不要报警、报什么级别"。
    第二级（Agent，云端 LLM）：收到疑似事件后结合上下文做最终判断，决定是否告警。

规则来源：rules 表（用户下指令 → Agent 解析 → add_rule 入库），不是硬编码。
边沿触发：状态从「未命中」变为「命中」时才上报一次，持续命中期间不重复；
        状态消失后再次出现才重新上报。避免同一异常反复烧 LLM / 反复告警。
"""
from memory import Memory

# 规则类型元信息：rule_type -> 给 LLM 看的中文说明（用于把自然语言解析成规则）
RULE_TYPES = {
    "no_person_light_on": "房间无人但灯亮着，可能忘关灯",
    "person_lying": "有人呈躺卧姿态（非卧室），可能跌倒或晕倒",
    "person_enter": "房间从无人变为有人，可能有人进入",
}


def _find(obj_list: list, category: str) -> dict | None:
    """在房间对象列表里按 category 找对象。"""
    return next((o for o in obj_list if o.get("category") == category), None)


def _check_no_person_light_on(state: dict, _prev: dict | None) -> list[dict]:
    """命中：房间无人但灯亮。返回 [{room}]。"""
    hits = []
    for room in state.get("rooms", []):
        person = _find(room.get("objects", []), "person")
        light = _find(room.get("objects", []), "light")
        if person and light and person.get("count", 0) == 0 and light.get("state") == "on":
            hits.append({"room": room["room"]})
    return hits


def _check_person_lying(state: dict, _prev: dict | None) -> list[dict]:
    """命中：非卧室有人躺卧。返回 [{room}]。"""
    hits = []
    for room in state.get("rooms", []):
        if room.get("room") == "卧室":
            continue  # 卧室躺卧属正常休息，不初筛
        person = _find(room.get("objects", []), "person")
        if person and person.get("count", 0) > 0 and person.get("pose") == "lying":
            hits.append({"room": room["room"]})
    return hits


def _check_person_enter(state: dict, prev: dict | None) -> list[dict]:
    """命中：房间从无人变为有人。返回 [{room}]。

    前置条件：仅离家模式（away）下才检测人员进入；在家模式下用户
    自己在各房间走动属正常，不当作可疑事件。
    """
    if Memory().get_home_mode() != "away":
        return []
    if not prev:
        return []  # 首次快照无法判断"进入"
    hits = []
    for room in state.get("rooms", []):
        cur = _find(room.get("objects", []), "person")
        cur_count = cur.get("count", 0) if cur else 0
        prev_room = next((r for r in prev.get("rooms", []) if r.get("room") == room["room"]), None)
        prev_person = _find(prev_room.get("objects", []), "person") if prev_room else None
        prev_count = prev_person.get("count", 0) if prev_person else 0
        if prev_count == 0 and cur_count > 0:
            hits.append({"room": room["room"]})
    return hits


# rule_type -> 确定性检查函数（返回命中列表，空列表=未命中）
RULE_CHECKS = {
    "no_person_light_on": _check_no_person_light_on,
    "person_lying": _check_person_lying,
    "person_enter": _check_person_enter,
}


class EventEngine:
    def __init__(self):
        # key -> 该规则位置当前是否处于「命中」状态（边沿触发的记忆）
        self._active: set[str] = set()
        self._prev_state: dict | None = None  # 上一次快照（供状态变化类规则）

    def detect(self, state: dict) -> list[dict]:
        """按规则表检测当前快照，返回疑似事件列表（不带 severity）。

        边沿触发：只有 key 从「未命中」变为「命中」才产出事件；
        持续命中期间不重复；状态消失后 key 移出 active，再次命中才重新上报。
        """
        if "error" in state:
            return []

        events: list[dict] = []
        current_hits: set[str] = set()

        for rule in Memory().list_rules(active_only=True):
            checker = RULE_CHECKS.get(rule["rule_type"])
            if checker is None:
                continue
            for hit in checker(state, self._prev_state):
                key = f"{rule['id']}:{hit['room']}"
                current_hits.add(key)
                if key in self._active:
                    continue  # 持续命中，不重复上报
                self._active.add(key)
                events.append({
                    "rule_id": rule["id"],
                    "rule_type": rule["rule_type"],
                    "room": hit["room"],
                    "rule_description": rule.get("description") or "",
                    "summary": self._summarize(rule, hit),
                })

        # 状态消失的 key 从 active 移出，下次再命中时重新触发
        self._active = current_hits
        self._prev_state = state
        return events

    @staticmethod
    def _summarize(rule: dict, hit: dict) -> str:
        """生成疑似事件的一句话描述（给 LLM 二次判断用）。"""
        base = RULE_TYPES.get(rule["rule_type"], rule["rule_type"])
        return f"{hit['room']}：{base}"
