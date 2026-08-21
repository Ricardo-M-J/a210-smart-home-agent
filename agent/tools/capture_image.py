"""图像采集 Tool：获取当前家居画面。

- mode=latest：读最近一帧缓存（性能优化路径，摄像头持续采时直接用）
- mode=fresh：主动采集一帧（真正触发一次采集动作）

底层动作走 tools.backend，Mock 阶段读快照兜底，上板后切真实采集接口。
"""

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "capture_image",
        "description": "获取当前家居画面（一帧图像）。mode=latest 读最新缓存帧，mode=fresh 主动采集一帧。",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["latest", "fresh"],
                    "description": "latest=读缓存帧；fresh=主动重新采集",
                },
            },
            "required": [],
        },
    },
}


def run(mode: str = "latest") -> dict:
    """按 mode 返回画面信息。fresh 走主动采集，latest 读缓存。"""
    from tools.backend import get_backend

    backend = get_backend()
    if mode == "fresh":
        result = backend.capture()  # 主动触发采集
    else:
        result = backend.latest_frame()  # 读缓存（优化路径）
    result["mode"] = mode
    return result
