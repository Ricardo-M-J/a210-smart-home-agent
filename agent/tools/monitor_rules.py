"""监控规则 Tool：把用户自然语言指令登记为持续监控规则。

用户说「我离开家了，有人进来就报警」→ Agent 判断意图 → 调 add_monitor_rule
把规则存入 rules 表 → 事件引擎后台按规则表持续检测。

这三个 Tool 让「下指令 → 持续监控」闭环成立，规则可增删，不再硬编码。
"""
from event_engine import RULE_TYPES

ADD_SPEC = {
    "type": "function",
    "function": {
        "name": "add_monitor_rule",
        "description": "登记一条持续监控规则。当用户说'如果发生X就报警/提醒我'这类持续监控需求时调用。"
                       f"rule_type 只能从以下选：{list(RULE_TYPES.keys())}，含义分别为：{RULE_TYPES}。"
                       "description 记录用户的原始诉求。",
        "parameters": {
            "type": "object",
            "properties": {
                "rule_type": {
                    "type": "string",
                    "enum": list(RULE_TYPES.keys()),
                    "description": "监控规则类型枚举",
                },
                "description": {
                    "type": "string",
                    "description": "用户原始诉求的自然语言描述",
                },
            },
            "required": ["rule_type", "description"],
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
        "description": "设置在家/离家模式。用户说'我出门了/我离开家了'→away；说'我回来了/我到家了'→home。"
                       "离家模式下 person_enter 等规则才会生效，在家模式下不检测人员进入。",
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


def add_monitor_rule(rule_type: str, description: str) -> dict:
    """登记监控规则。"""
    from memory import Memory

    if rule_type not in RULE_TYPES:
        return {"status": "error", "detail": f"未知规则类型: {rule_type}，可选 {list(RULE_TYPES.keys())}"}
    rule_id = Memory().add_rule(rule_type, description)
    return {
        "status": "ok",
        "rule_id": rule_id,
        "rule_type": rule_type,
        "description": description,
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
        "note": "已切换到离家模式，人员进入类规则已武装" if mode == "away" else "已切换到在家模式，人员进入类规则已解除武装",
    }


def get_home_mode() -> dict:
    """查询当前模式。"""
    from memory import Memory

    return {"status": "ok", "mode": Memory().get_home_mode()}
