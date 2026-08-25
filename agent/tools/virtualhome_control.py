"""Tool for controlling VirtualHome room devices from Agent dialogue."""

from __future__ import annotations

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "control_virtualhome",
        "description": (
            "控制 VirtualHome 四个房间的灯光或全屋音乐。"
            "用于用户要求打开/关闭灯、播放/停止/暂停/切换音乐等指令。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "room": {
                    "type": "string",
                    "enum": ["living_room", "bedroom", "kitchen", "bathroom", "all_rooms"],
                    "description": "灯光目标房间；音乐固定使用 all_rooms",
                },
                "device": {
                    "type": "string",
                    "enum": ["light", "speaker"],
                    "description": "light=房间灯光，speaker=全屋音乐",
                },
                "command": {
                    "type": "string",
                    "enum": ["on", "off", "play", "stop", "pause"],
                    "description": "灯光使用 on/off；音箱使用 play/stop/pause",
                },
                "value": {
                    "type": "string",
                    "description": "可选，音乐曲目或附加值",
                },
                "source_text": {
                    "type": "string",
                    "description": "用户原始自然语言指令",
                },
            },
            "required": ["room", "device", "command"],
        },
    },
}


def run(
    room: str,
    device: str,
    command: str,
    value: str | None = None,
    source_text: str | None = None,
) -> dict:
    from tools.backend import get_backend

    return get_backend().control_virtualhome(room, device, command, value, source_text)
