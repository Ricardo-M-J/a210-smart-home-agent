"""家居状态读取：Agent 消费感知层写入的快照文件。

真实环境：感知进程原子写 HOME_STATE_FILE，Agent 轮询读。
本地 Mock：由 mock 模块写入 home_state.json，同样走这个读取器。
"""
import json
import os
from pathlib import Path

import config


def read_home_state() -> dict:
    """读取家居状态快照。文件不存在或解析失败时返回空快照（降级）。"""
    path = Path(config.HOME_STATE_FILE)
    if not path.exists():
        return {"error": "暂无家居状态数据，感知进程尚未写入快照"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"快照读取失败: {e}"}
