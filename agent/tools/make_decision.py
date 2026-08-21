"""结果决策 Tool：根据视觉推理结果判断并触发动作（告警/记录日志）。

智能判断走云端 LLM（由 Agent 循环完成），本 Tool 负责把确定性动作落地：
- 生成结构化决策记录（写入 SQLite 记忆）
- 触发告警（本地阶段返回告警标记，上板后接真实告警通道）
"""

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "make_decision",
        "description": "根据当前家居状态做出判断，触发相应动作（告警/记录），并写入决策日志。",
        "parameters": {
            "type": "object",
            "properties": {
                "conclusion": {
                    "type": "string",
                    "description": "判断结论，如：无人但客厅灯亮、有人躺倒需关注、状态正常等",
                },
                "action": {
                    "type": "string",
                    "enum": ["alert", "log", "none"],
                    "description": "alert=告警；log=仅记录；none=无动作",
                },
                "message": {
                    "type": "string",
                    "description": "给用户的提示或告警内容",
                },
            },
            "required": ["conclusion", "action", "message"],
        },
    },
}

def run(conclusion: str, action: str, message: str) -> dict:
    """落地决策：写 SQLite 记忆 + 告警 + 推 Web 面板。"""
    from memory import Memory
    import runtime  # 延迟导入，避免运行时循环依赖

    record = {
        "conclusion": conclusion,
        "action": action,
        "message": message,
    }
    Memory().log_decision(record)

    alert = action == "alert"
    if alert:
        # 告警推入 Web 面板，闭合「决策 → 告警 → 可视化」
        runtime.push_alert("alert", conclusion, message)

    return {
        "status": "ok",
        "alert": alert,
        "record": record,
        "note": "已触发告警" if alert else "已记录决策",
    }
