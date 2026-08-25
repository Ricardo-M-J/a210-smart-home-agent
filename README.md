# A210 Smart Home Agent + VirtualHome

本仓库把 A210 智能家居 Agent、Web UI、VirtualHome 虚拟家居环境、showcase 面板、样本脚本和本地运行依赖放在同一个私有项目里。Agent 端可以通过自然语言控制 VirtualHome 的灯光和全屋音乐；VirtualHome 端可以把 01-07 展示样本的帧流、房间状态和检测结果同步给 Agent。

当前验证环境以 Windows + PowerShell 为准。

## 目录

```text
agent/          Agent 服务、LLM 对话、状态同步、Web UI
VIRTUAL_HOME/   VirtualHome 虚拟环境、展示面板、样本脚本、音乐和 Python 环境
docs/           Agent 与 VirtualHome 集成、部署和数据契约文档
yolo/           A210/YOLO 侧代码与交接内容
```

## 协作者首次配置

### 1. 安装基础工具

新机器至少需要：

- Git
- Git LFS
- Windows PowerShell
- Python 3.10/3.11 或 Conda，用于在内置 `vhome` 环境不可用时重建环境
- VSCode + Python 扩展，可选，用于直接使用 `.vscode/launch.json`
- Unity Hub，可选，仅当需要重新打开或构建 `virtualhome_unity_project` 时使用

Unity 源工程当前记录的编辑器版本是 `2021.3.10f1c2`。只运行预编译 `VirtualHome.exe` 不需要安装 Unity。

### 2. 克隆仓库并拉取 LFS 文件

本项目包含音乐、虚拟环境、Unity 资源和可执行文件，必须先安装并启用 Git LFS。

```powershell
git lfs install
git clone https://github.com/Ricardo-M-J/a210-smart-home-agent.git
cd a210-smart-home-agent
git lfs pull
```

如果没有执行 `git lfs pull`，很多二进制文件会只是很小的 pointer 文本，`vhome`、音乐或 VirtualHome 运行文件可能无法正常使用。

### 3. 恢复 GitHub 无法托管的 VirtualHome 大文件

GitHub LFS 当前拒收超过 2GB 的单文件。本项目里的下面这个 Unity 运行资源约 `3.36GB`，实际大小约 `3,606,796,284` 字节，因此没有上传到 GitHub：

```text
VIRTUAL_HOME/windows_exec/windows_exec.v2.2.4/VirtualHome_Data/resources.assets.resS
```

协作者必须手动获取并放回同一路径，否则 `VirtualHome.exe` 可能无法完整渲染，showcase 面板的 `Connect API` 和官方自然动画样本也可能失败。

获取方式按优先级选择：

1. 向项目维护者索取团队共享的完整 `windows_exec.v2.2.4` 压缩包，或至少索取 `resources.assets.resS` 这个文件。解压或复制后，确保文件位于上面的精确路径。
2. 如果拿不到团队包，可以从 VirtualHome 官方 Windows simulator 包获取预编译模拟器。上游仓库 `VIRTUAL_HOME/virtualhome/README.md` 中给出的 Windows 下载入口是 `http://virtual-home.org//release/simulator/v2.0/v2.3.0/windows_exec.zip`。官方版本可能不是本项目验证过的 `v2.2.4`，如果目录名不同，可以改名为 `windows_exec.v2.2.4`，或在单独运行脚本时使用 `--simulator-path` 指向真实的 `VirtualHome.exe`。
3. 如果需要完全可编辑的模拟器，可以用 `VIRTUAL_HOME/virtualhome_unity_project` 通过 Unity 重新构建 Windows 可执行包，并把构建结果放到 `VIRTUAL_HOME/windows_exec/windows_exec.v2.2.4/`。

恢复后用下面命令确认：

```powershell
Test-Path .\VIRTUAL_HOME\windows_exec\windows_exec.v2.2.4\VirtualHome_Data\resources.assets.resS
(Get-Item .\VIRTUAL_HOME\windows_exec\windows_exec.v2.2.4\VirtualHome_Data\resources.assets.resS).Length
```

第一条应返回 `True`，第二条应接近 `3606796284`。这个文件已经写入 `.gitignore`，不要再提交到 Git。

### 4. 配置 Agent 环境变量

复制本地配置文件：

```powershell
Copy-Item .\agent\.env.example .\agent\.env
```

在 `agent/.env` 中确认或修改：

```text
DASHSCOPE_API_KEY=<向项目维护者获取，不要提交>
DASHSCOPE_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-flash

BACKEND=virtualhome
VIRTUAL_HOME_DIR=../VIRTUAL_HOME
VIRTUAL_HOME_PYTHON=../VIRTUAL_HOME/vhome/Scripts/python.exe
VIRTUAL_HOME_UNITY_CONTROL=1
VIRTUAL_HOME_UNITY_PORT=8080

WEB_HOST=0.0.0.0
WEB_PORT=8019
A210_AGENT_URL=http://127.0.0.1:8019
```

真实 API Key 只能写在本机 `agent/.env`，不要提交到 Git。云端 LLM 不可用时，优先检查 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`、网络代理和当前网络是否能访问对应端点。

### 5. 准备 Python 环境

仓库里已经包含一个 Windows Python 环境：

```text
VIRTUAL_HOME/vhome/
```

优先直接验证它：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe -c "import cv2, flask, requests; from PIL import Image; print('vhome ok')"
```

如果提示 `cv2`、`flask` 或其他模块缺失，或者虚拟环境因为机器路径差异不能启动，可以重建。

普通 venv 方式：

```powershell
python -m venv .\VIRTUAL_HOME\vhome
.\VIRTUAL_HOME\vhome\Scripts\python.exe -m pip install -U pip
.\VIRTUAL_HOME\vhome\Scripts\python.exe -m pip install -r .\agent\requirements.txt
.\VIRTUAL_HOME\vhome\Scripts\python.exe -m pip install -r .\VIRTUAL_HOME\src\virtualhome_env\requirements-showcase.txt
.\VIRTUAL_HOME\vhome\Scripts\python.exe -m pip install -e .\VIRTUAL_HOME\virtualhome
```

Conda 方式：

```powershell
conda create -n vhome python=3.10 -y
conda activate vhome
python -m pip install -U pip
python -m pip install -r .\agent\requirements.txt
python -m pip install -r .\VIRTUAL_HOME\src\virtualhome_env\requirements-showcase.txt
python -m pip install -e .\VIRTUAL_HOME\virtualhome
python -c "import sys; print(sys.executable)"
```

如果使用 Conda 环境，把最后一条命令打印出来的 `python.exe` 绝对路径写入 `agent/.env` 的 `VIRTUAL_HOME_PYTHON`。VSCode 的 `.vscode/launch.json` 默认使用仓库内的 `VIRTUAL_HOME\vhome\Scripts\python.exe`，如果改用 Conda，也要同步改 VSCode 配置或手动选择解释器。

### 6. 音乐文件

全屋音乐统一放在：

```text
VIRTUAL_HOME/assets/music/
```

当前支持 `mp3` 和 `wav`。Agent 自然语言点歌、停止音乐，以及 06 健康助手样本都会使用这个目录。06 健康助手优先播放 `伊藤サチコ - いつも何度でも.mp3`；如果要替换舒缓音乐，把新文件放到该目录，并在对应脚本或配置中改优先曲目即可。

## 启动项目

建议从仓库根目录运行所有命令。

### 1. 启动 VirtualHome.exe

```powershell
.\VIRTUAL_HOME\windows_exec\windows_exec.v2.2.4\VirtualHome.exe -screen-fullscreen 0 -screen-quality 4 -http-port=8080
```

如果出现启动器，选择 Windowed 并点击 `Play!`。Agent 不会自动启动 VirtualHome.exe，它只会连接已经在 `8080` 端口运行的模拟器。

### 2. 启动 Agent Web

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\agent\web.py
```

浏览器打开：

```text
http://127.0.0.1:8019
```

不要在浏览器里打开 `http://0.0.0.0:8019`。`0.0.0.0` 是服务监听地址，不是访问地址。

### 3. 启动 VirtualHome showcase 面板

```powershell
$env:A210_AGENT_URL="http://127.0.0.1:8019"
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\VIRTUAL_HOME\src\virtualhome_env\showcase_panel.py
```

也可以在 VSCode 里直接运行：

```text
Agent Web (VirtualHome, 8019)
VirtualHome Showcase Panel
Agent + VirtualHome Panel
```

VSCode 的 compound 会同时启动 Agent Web 和 showcase 面板，但 `VirtualHome.exe` 仍建议先手动打开并点击 `Play!`。

## 联动测试

Agent 端自然语言控制：

```text
打开卧室灯
关闭厨房灯
打开客厅灯
播放 doudou
停止音乐
```

预期现象：

- Agent Web 的四房间状态卡片实时变化，只包含客厅、卧室、厨房、卫生间。
- VirtualHome 里的灯光通过 Python API 更新。
- 全屋音乐只从 `VIRTUAL_HOME/assets/music` 播放，不再触发 Unity 内置 TV/radio 声源。
- `VIRTUAL_HOME/outputs/agent_bridge/simulated_device_state.json` 会记录当前设备状态。

VirtualHome 端样本联动：

```text
01 全屋环境俯瞰交互
02 多摄像头布设
03 人员计数和无人关灯
04 普通模式宠物留守告警
05 火灾烟雾报警
06 健康助手：灯光 + 音乐
07 离家模式陌生人告警
```

点击 showcase 面板里的 03-07 样本时，面板会把当前样本帧和外部识别结果发送到 Agent 的 `/api/virtualhome/frame`。Agent 终端会输出 `[virtualhome-sync]` 日志；异常事件会在 Agent 对话框里给出日常化提示。

基础接口检查：

```powershell
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8019/api/llm/status').read().decode('utf-8'))"
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8019/api/state').read().decode('utf-8'))"
```

更多细节见：

```text
docs/virtualhome-agent-integration.md
VIRTUAL_HOME/README.md
VIRTUAL_HOME/docs/virtualhome_demo_runbook.md
```

## 上传与协作规则

本仓库采用 Vendor 策略：`VIRTUAL_HOME/virtualhome` 和 `VIRTUAL_HOME/virtualhome_unity_project` 的内部 `.git` 已移除，作为主仓库普通目录提交，不需要额外初始化 submodule。

不会上传或不应提交的内容：

- `agent/.env`：包含真实 API Key。
- `VIRTUAL_HOME/windows_exec/**/VirtualHome_Data/resources.assets.resS`：单文件超过 GitHub LFS 2GB 限制，必须走外部包恢复。
- `VIRTUAL_HOME/outputs/`：运行日志、导出的帧、样本视频、桥接状态，可重新生成。
- `VIRTUAL_HOME/archive/`：早期 legacy demo，不属于当前系统链路。
- `VIRTUAL_HOME/virtualhome_unity_project/Library/`、`Logs/`、`Temp/`、`UserSettings/`：Unity 缓存和本机编辑器状态。
- `__pycache__/`、`*.pyc`、临时文件和本机缓存。

会上传的内容：

- `agent/`、`docs/`：Agent、Web UI、LLM 和集成文档。
- `VIRTUAL_HOME/src/`、`demo/`、`docs/`、`assets/demo_sources/`：VirtualHome 集成脚本、showcase 面板、接口 schema 和素材。
- `VIRTUAL_HOME/assets/music/`：私有项目内置音乐。
- `VIRTUAL_HOME/vhome/`：当前 Windows Python 环境，使用 Git LFS 托管。
- `VIRTUAL_HOME/windows_exec/`：除超限 `resources.assets.resS` 外的预编译模拟器文件。
- `VIRTUAL_HOME/virtualhome/`、`VIRTUAL_HOME/virtualhome_unity_project/Assets`、`Packages`、`ProjectSettings`：VirtualHome Python API 和 Unity 源项目必要内容。

提交前建议检查：

```powershell
git status --short --branch
git fetch --prune origin
git lfs status
Get-ChildItem -Path VIRTUAL_HOME -Recurse -File -Force | Where-Object { $_.Length -gt 2GB } | Sort-Object Length -Descending | Select-Object FullName,Length
rg -n "sk-[A-Za-z0-9_.-]+|API[_-]?key|DASHSCOPE_API_KEY|token" -g "!VIRTUAL_HOME/vhome/**" -g "!.git/**" .
```

如果本地有未提交改动，`git pull --rebase origin master` 会失败并提示 `cannot pull with rebase: You have unstaged changes`。先提交或 stash，再 rebase：

```powershell
git add .gitattributes .gitignore .vscode README.md agent docs VIRTUAL_HOME
git commit -m "描述本次修改"
git pull --rebase origin master
git push origin master
```

如果 push 再次出现 `Size must be less than or equal to 2147483648`，说明还有超过 2GB 的单文件进入了提交。先用上面的 `Get-ChildItem` 命令定位，再用 `git rm --cached -- <path>` 从索引移除，并写入 `.gitignore`。

## 常见问题

`ERR_ADDRESS_INVALID`：浏览器不要访问 `0.0.0.0`，改用 `http://127.0.0.1:8019`。

`cv2` 缺失：确认正在使用 `VIRTUAL_HOME\vhome\Scripts\python.exe`；如果环境损坏，按本文 Python 环境部分重建。

`Connect API` 失败：确认 `VirtualHome.exe` 已打开、点击了 `Play!`、端口是 `8080`，并且 `resources.assets.resS` 已恢复到正确路径。

云端 LLM 不可用：检查 `agent/.env` 中的 API Key、Base URL、模型名和网络代理。可以先打开 `/api/llm/status` 看具体错误。
