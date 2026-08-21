"""配置加载：从 .env / 环境变量读取，绝不硬编码 API Key。

加载优先级：进程环境变量 > .env 文件。
"""
import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析，避免引入 python-dotenv 依赖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 进程环境变量优先，.env 不覆盖
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(_BASE_DIR / ".env")


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# 云端大模型（通义千问 OpenAI 兼容端点）
DASHSCOPE_API_KEY = get("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = get("DASHSCOPE_BASE_URL", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
DASHSCOPE_MODEL = get("DASHSCOPE_MODEL", "qwen3.6-flash")

# 家居状态快照文件路径
# 相对路径基于项目根目录（本文件所在目录）解析为绝对路径，避免依赖运行时的 cwd。
# 上板时在 .env 里写绝对路径（如 /tmp/home_state.json）即可，无需改代码。
_HOME_STATE_RAW = get("HOME_STATE_FILE", "./mock/home_state.json")
HOME_STATE_FILE = str(Path(_HOME_STATE_RAW).resolve() if not Path(_HOME_STATE_RAW).is_absolute() else Path(_HOME_STATE_RAW))

# Web 服务
WEB_HOST = get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(get("WEB_PORT", "8000"))

# 端侧动作后端：mock=读快照兜底；real=调用队友的采集/推理接口（上板后）
BACKEND = get("BACKEND", "mock")
