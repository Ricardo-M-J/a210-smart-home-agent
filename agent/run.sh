#!/usr/bin/env bash
# A210 智能家居边缘视觉 Agent —— 启动脚本
# 用法：bash run.sh [web|cli]
#   web  —— 启动 Web 服务（默认，演示/上板）
#   cli  —— 启动命令行交互
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 虚拟环境（install.sh 已建）
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

MODE="${1:-web}"

# 上板 real 模式：快照文件用绝对路径，避免 systemd cwd 不一致
# （本地 mock 模式可保持默认 ./mock/home_state.json）
export HOME_STATE_FILE="${HOME_STATE_FILE:-/tmp/home_state.json}"

echo "[run] 模式=$MODE 后端=$BACKEND 快照=$HOME_STATE_FILE"

if [ "$MODE" = "cli" ]; then
  exec python main.py
else
  exec python web.py
fi
