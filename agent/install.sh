#!/usr/bin/env bash
# A210 智能家居边缘视觉 Agent —— 部署脚本
# 用法：bash install.sh
# 在 A210（RISC-V Debian）上执行：建虚拟环境、装依赖、生成 .env。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
echo "[install] 项目目录: $DIR"

# 1. 虚拟环境（隔离系统 Python，规避权限与依赖冲突）
if [ ! -d ".venv" ]; then
  echo "[install] 创建虚拟环境 .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2. 安装依赖（仅 requests + flask；若 flask 的 MarkupSafe 在 riscv64 无 wheel，
#    会自动尝试源码编译，需板上有 gcc；失败则改用纯标准库 http.server 方案）
echo "[install] 安装依赖 ..."
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3. 生成 .env（如不存在）
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[install] 已生成 .env，请编辑填入 DASHSCOPE_API_KEY 与 BACKEND"
fi

echo "[install] 完成。后续：编辑 .env → bash run.sh"
