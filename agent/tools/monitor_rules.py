"""监控规则 Tool：把用户自然语言指令登记为持续监控规则。

用户说「厨房有猫没人就报警」→ Agent 把它解析成条件字典（when）→ add_monitor_rule
把规则存入 rules 表 → 事件引擎后台用通用匹配持续检测。

规则不是预设枚举，而是 LLM 从用户指令动态生成的条件字典，这是 Agent 自主性的核心。
"""
from event_engine import ROOM_CN, ROOM_FIELDS

_ROOMS = list(ROOM_CN.keys())

ADD_SPEC = {
    "type": "function",
    "function": {
        "name": "add_monitor_rule",
        "description": "登记一条持续监控规则。当用户说'如果发生X就报警/提醒我'这类持续监控需求时调用。"
                       "把用户的诉求解析成触发条件 when。",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "用户原始诉求的自然语言描述",
                },
                "when": {
                    "type": "object",
                    "description": "触发条件字典，字段之间是 AND 关系，省略的字段表示不限制。"
                                   "可选字段：room(房间名，枚举：living_room/bedroom1/bedroom2/kitchen/bathroom)、"
                                   "has_person(是否有人)、has_cat(是否有猫)、has_dog(是否有狗)、"
                                   "fall_like(是否像跌倒)、is_night(是否夜间)。"
                                   "例：厨房有猫且无人 → {\"room\":\"kitchen\",\"has_cat\":true,\"has_person\":false}；"
                                   "有人跌倒 → {\"fall_like\":true}；"
                                   "夜里有人进入 → {\"has_person\":true,\"is_night\":true}",
                    "properties": {
                        "room": {"type": "string", "enum": _ROOMS, "description": "指定房间，省略则匹配任意房间"},
                        "has_person": {"type": "boolean", "description": "是否检测到人"},
                        "has_cat": {"type": "boolean", "description": "是否检测到猫"},
                        "has_dog": {"type": "boolean", "description": "是否检测到狗"},
                        "fall_like": {"type": "boolean", "description": "是否像跌倒"},
                        "is_night": {"type": "boolean", "description": "是否夜间（22:00-06:00）"},
                    },
                },
                "action": {
                    "type": "string",
                    "enum": ["alert", "log"],
                    "description": "命中后动作：alert=告警；log=仅记录",
                },
                "requires_mode": {
                    "type": "string",
                    "enum": ["home", "away"],
                    "description": "可选：该规则仅在指定模式（home/away）下生效。"
                                   "如'有人进入报警'通常需要 away 模式（离家时才检测有人进入）。",
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
        "description": "取消一条监控规则（按 id，id 可从 list_monitor_rules 获得）。",
        "parameters": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer", "description": "规则 id"},
            },
            "required": ["rule_id"],
        },
    },
}

MODE_SPEC = {
    "type": "function",
    "function": {
        "name": "set_home_mode",
        "description": "设置在家/离家模式。用户说'我出门了/我离开家了'→away；说'我回来了/我到家了'→home。",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["home", "away"],
                    "description": "home=在家；away=离家",
                },
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
    """登记监控规则。when 是条件字典，由 LLM 从用户指令生成。"""
    from memory import Memory

    if not isinstance(when, dict) or not when:
        return {"status": "error", "detail": "when 条件不能为空"}
    # 校验 when 字段合法
    allowed = set(ROOM_FIELDS) | {"room", "is_night"}
    unknown = set(when) - allowed
    if unknown:
        return {"status": "error", "detail": f"未知条件字段: {unknown}，可选 {sorted(allowed)}"}
    # 校验 room 值在英文枚举里：LLM 偶尔生成中文（如"客厅"）或拼错，
    # 不校验会入库后永远匹配不到（rooms 的 key 是英文），用户以为设了监控其实没在干活
    if "room" in when and when["room"] not in _ROOMS:
        return {"status": "error", "detail": f"room 非法: {when['room']!r}，可选 {_ROOMS}"}

    rule_id = Memory().add_rule(description, when, action, requires_mode)
    return {
        "status": "ok",
        "rule_id": rule_id,
        "description": description,
        "when": when,
        "action": action,
        "requires_mode": requires_mode,
        "note": "监控规则已生效，后台将持续检测",
    }


def list_monitor_rules() -> dict:
    """列出当前启用的监控规则。"""
    from memory import Memory

    rules = Memory().list_rules(active_only=True)
    return {"status": "ok", "rules": rules}


def remove_monitor_rule(rule_id: int) -> dict:
    """取消监控规则。"""
    from memory import Memory

    ok = Memory().disable_rule(rule_id)
    if not ok:
        return {"status": "error", "detail": f"规则 {rule_id} 不存在或已停用"}
    return {"status": "ok", "rule_id": rule_id, "note": "规则已取消"}


def set_home_mode(mode: str) -> dict:
    """设置在家/离家模式。"""
    from memory import Memory

    if mode not in ("home", "away"):
        return {"status": "error", "detail": f"模式只能是 home 或 away，收到 {mode}"}
    Memory().set_home_mode(mode)
    return {
        "status": "ok",
        "mode": mode,
        "note": "已切换到离家模式" if mode == "away" else "已切换到在家模式",
    }


def get_home_mode() -> dict:
    """查询当前模式。"""
    from memory import Memory

    return {"status": "ok", "mode": Memory().get_home_mode()}
