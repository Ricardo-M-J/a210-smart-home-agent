"""Monitor-rule tools used by the agent function-calling loop."""

from __future__ import annotations

from rooms import ROOM_CN, ROOM_FIELDS, normalize_room

_ROOMS = list(ROOM_CN.keys())
_ROOM_FIELD_PROPERTIES = {
    "has_person": {"type": "boolean", "description": "是否检测到人"},
    "has_cat": {"type": "boolean", "description": "是否检测到猫"},
    "has_dog": {"type": "boolean", "description": "是否检测到狗"},
    "fall_like": {"type": "boolean", "description": "是否像跌倒/躺倒"},
    "hazard_detected": {"type": "boolean", "description": "是否检测到烟雾、火灾等危险"},
    "hazard_type": {"type": "string", "description": "危险类型，例如 fire_smoke"},
    "health_event": {"type": "boolean", "description": "是否有健康/可穿戴设备事件"},
    "unknown_person": {"type": "boolean", "description": "是否检测到陌生人"},
}

ADD_SPEC = {
    "type": "function",
    "function": {
        "name": "add_monitor_rule",
        "description": (
            "登记一条持续监控规则。把用户的自然语言需求解析成 when 条件；"
            "房间只允许 living_room/bedroom/kitchen/bathroom。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "用户原始需求的自然语言描述"},
                "when": {
                    "type": "object",
                    "description": (
                        "触发条件字典，字段之间是 AND 关系。可选字段：room、"
                        "has_person、has_cat、has_dog、fall_like、hazard_detected、"
                        "hazard_type、health_event、unknown_person、is_night。"
                    ),
                    "properties": {
                        "room": {"type": "string", "enum": _ROOMS, "description": "指定房间，省略则匹配任意房间"},
                        **_ROOM_FIELD_PROPERTIES,
                        "is_night": {"type": "boolean", "description": "是否夜间，22:00-06:00"},
                    },
                },
                "action": {
                    "type": "string",
                    "enum": ["alert", "log"],
                    "description": "命中后的动作：alert=告警，log=仅记录",
                },
                "requires_mode": {
                    "type": "string",
                    "enum": ["home", "away"],
                    "description": "可选：规则仅在指定 home/away 模式下生效",
                },
            },
            "required": ["description", "when"],
        },
    },
}

LIST_SPEC = {
    "type": "function",
    "function": {
        "name": "list_monitor_rules",
        "description": "查看当前已登记的监控规则列表。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

REMOVE_SPEC = {
    "type": "function",
    "function": {
        "name": "remove_monitor_rule",
        "description": "按 id 取消一条监控规则。",
        "parameters": {
            "type": "object",
            "properties": {"rule_id": {"type": "integer", "description": "规则 id"}},
            "required": ["rule_id"],
        },
    },
}

MODE_SPEC = {
    "type": "function",
    "function": {
        "name": "set_home_mode",
        "description": "设置在家/离家模式。",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["home", "away"],
                    "description": "home=在家，away=离家",
                }
            },
            "required": ["mode"],
        },
    },
}

GET_MODE_SPEC = {
    "type": "function",
    "function": {
        "name": "get_home_mode",
        "description": "查询当前在家/离家模式。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

RULE_SPECS = [ADD_SPEC, LIST_SPEC, REMOVE_SPEC, MODE_SPEC, GET_MODE_SPEC]


def add_monitor_rule(description: str, when: dict, action: str = "alert", requires_mode: str | None = None) -> dict:
    from memory import Memory

    if not isinstance(when, dict) or not when:
        return {"status": "error", "detail": "when 条件不能为空"}

    allowed = set(ROOM_FIELDS) | {"room", "is_night"}
    unknown = set(when) - allowed
    if unknown:
        return {"status": "error", "detail": f"未知条件字段: {sorted(unknown)}，可选 {sorted(allowed)}"}

    normalized = dict(when)
    if "room" in normalized:
        room = normalize_room(normalized["room"])
        if not room:
            return {"status": "error", "detail": f"room 非法: {normalized['room']!r}，可选 {_ROOMS}"}
        normalized["room"] = room

    rule_id = Memory().add_rule(description, normalized, action, requires_mode)
    return {
        "status": "ok",
        "rule_id": rule_id,
        "description": description,
        "when": normalized,
        "action": action,
        "requires_mode": requires_mode,
        "note": "监控规则已生效，后台会持续检测。",
    }


def list_monitor_rules() -> dict:
    from memory import Memory

    return {"status": "ok", "rules": Memory().list_rules(active_only=True)}


def remove_monitor_rule(rule_id: int) -> dict:
    from memory import Memory

    ok = Memory().disable_rule(rule_id)
    if not ok:
        return {"status": "error", "detail": f"规则 {rule_id} 不存在或已停用"}
    return {"status": "ok", "rule_id": rule_id, "note": "规则已取消"}


def set_home_mode(mode: str) -> dict:
    from memory import Memory

    if mode not in ("home", "away"):
        return {"status": "error", "detail": f"模式只能是 home 或 away，收到 {mode}"}
    Memory().set_home_mode(mode)
    return {"status": "ok", "mode": mode, "note": "已切换到离家模式" if mode == "away" else "已切换到在家模式"}


def get_home_mode() -> dict:
    from memory import Memory

    return {"status": "ok", "mode": Memory().get_home_mode()}
