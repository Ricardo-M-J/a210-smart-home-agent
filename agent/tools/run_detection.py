"""模型推理 Tool：在 A210 端侧触发一次视觉检测，返回结构化检测结果。

- run() 主动触发一次端侧推理（对应赛题"模型推理 Tool"的字面要求）
- 读快照只是性能优化路径，封装在后端 infer() 内部，不暴露为 Tool 的行为

底层动作走 tools.backend：
    Mock 阶段：infer 退化为读快照（无真实 YOLO）
    上板后（方案 A）：infer 真正调用队友封装的 YOLO 推理接口
"""

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "run_detection",
        "description": "触发一次端侧视觉检测，返回结构化检测结果（各房间的人、灯、宠物、家电状态）。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def run() -> dict:
    """主动触发一次端侧推理，返回结构化检测结果。"""
    from tools.backend import get_backend

    return get_backend().infer()
