# A210 Smart Home Agent + VirtualHome

本仓库包含 A210 智能家居 Agent、Web UI、VirtualHome 虚拟家居环境、展示面板、样本脚本和本地运行依赖。

## 目录

```text
agent/         Agent 服务、LLM 对话、状态同步、Web UI
VIRTUAL_HOME/  VirtualHome 虚拟环境、Unity/Windows 模拟器、showcase 面板、脚本与 vhome 环境
docs/          集成、部署和数据契约文档
yolo/          A210/YOLO 侧代码与交接内容
```

## 首次配置

本项目当前以 Windows + PowerShell 为主要开发环境。

1. 准备 Agent 配置：

```powershell
Copy-Item .\agent\.env.example .\agent\.env
```

在 `agent/.env` 中确认至少包含：

```text
BACKEND=virtualhome
VIRTUAL_HOME_DIR=../VIRTUAL_HOME
VIRTUAL_HOME_PYTHON=../VIRTUAL_HOME/vhome/Scripts/python.exe
VIRTUAL_HOME_UNITY_CONTROL=1
VIRTUAL_HOME_UNITY_PORT=8080
WEB_PORT=8019
```

云端 LLM 的 `DASHSCOPE_API_KEY` 只写入本地 `agent/.env`，不要提交到 Git。

2. 使用仓库内置 VirtualHome Python 环境：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe -c "import cv2, PIL, requests; print('vhome ok')"
```

`VIRTUAL_HOME/vhome` 已随私有仓库提交，方便同机快速复现。注意：Windows venv 可能带有创建机器的绝对路径；如果其他开发者克隆后该环境不可用，用下面方式重建：

```powershell
python -m venv .\VIRTUAL_HOME\vhome
.\VIRTUAL_HOME\vhome\Scripts\python.exe -m pip install -r .\VIRTUAL_HOME\src\virtualhome_env\requirements-showcase.txt
.\VIRTUAL_HOME\vhome\Scripts\python.exe -m pip install -e .\VIRTUAL_HOME\virtualhome
```

3. 音乐文件放在：

```text
VIRTUAL_HOME/assets/music/
```

当前 Agent 与 showcase 面板只从该目录解析全屋音乐。06 健康助手优先播放 `伊藤サチコ - いつも何度でも.mp3`，用户自然语言点歌也使用同一个目录。

## 启动

1. 启动 VirtualHome.exe：

```powershell
.\VIRTUAL_HOME\windows_exec\windows_exec.v2.2.4\VirtualHome.exe -screen-fullscreen 0 -screen-quality 4 -http-port=8080
```

如果启动器出现，选择 Windowed 并点击 `Play!`。

2. 启动 Agent Web：

```powershell
python .\agent\web.py
```

浏览器打开：

```text
http://127.0.0.1:8019
```

3. 启动 VirtualHome showcase 面板：

```powershell
$env:A210_AGENT_URL="http://127.0.0.1:8019"
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\VIRTUAL_HOME\src\virtualhome_env\showcase_panel.py
```

面板 01 场景可点击 `Connect API` 连接已经打开的 VirtualHome.exe。

## 联动测试

在 Agent Web 对话框输入：

```text
打开卧室灯
关闭厨房灯
播放 doudou
停止音乐
```

预期结果：

- Agent UI 的四房间状态卡片同步变化。
- VirtualHome.exe 里的灯光状态通过 API 更新。
- 音乐只从 `VIRTUAL_HOME/assets/music` 播放，不再打开 Unity 内置 TV/radio 声源。
- `VIRTUAL_HOME/outputs/agent_bridge/simulated_device_state.json` 更新。

在 VirtualHome showcase 面板点击 03-07 样本，可验证人员计数、宠物留守、火灾烟雾、健康助手、离家陌生人等事件推送到 Agent。

更多细节见 [docs/virtualhome-agent-integration.md](docs/virtualhome-agent-integration.md) 和 [VIRTUAL_HOME/README.md](VIRTUAL_HOME/README.md)。

## VirtualHome 来源与提交方式

`VIRTUAL_HOME/virtualhome` 和 `VIRTUAL_HOME/virtualhome_unity_project` 来源于 VirtualHome 相关上游仓库，并在本项目中做了本地集成修改。

本仓库使用 Vendor 策略：两个子目录里的 `.git` 元数据已移除，源码作为本仓库普通目录提交。这样其他开发者克隆主仓库后可以直接拿到本地修改，不需要额外初始化 submodule。

不会上传的内容：

- `VIRTUAL_HOME/outputs/`：运行日志、导出的帧、样本视频、桥接状态，均可通过脚本重新生成。
- `VIRTUAL_HOME/archive/`：早期 legacy demo，不属于当前系统链路。
- `VIRTUAL_HOME/virtualhome_unity_project/Library/`、`Logs/`、`Temp/`、`UserSettings/`：Unity 缓存和本机编辑器状态。

会上传的内容：

- `VIRTUAL_HOME/src/`、`demo/`、`docs/`、`assets/demo_sources/`：当前集成代码、脚本、文档和生成素材。
- `VIRTUAL_HOME/assets/music/`：私有项目内置音乐。
- `VIRTUAL_HOME/vhome/`：当前可运行的 Windows Python 环境。
- `VIRTUAL_HOME/windows_exec/`：本机预编译 VirtualHome.exe 放置路径。`VirtualHome_Data/resources.assets.resS` 单文件约 3.36GB，超过 GitHub LFS 当前 2GB 单文件限制，不上传到仓库；新机器需要从原 VirtualHome 包或外部存储恢复到同一路径。
- `VIRTUAL_HOME/virtualhome/`、`virtualhome_unity_project/Assets`、`Packages`、`ProjectSettings`：VirtualHome Python 包和 Unity 源项目必要内容。

## GitHub 上传前检查

私有仓库也受 GitHub 普通 Git 单文件 100MB 限制。本仓库包含 Unity 资源、`vhome` 和音乐文件，必须启用 Git LFS。注意 GitHub LFS 仍会拒绝超过 2GB 的单文件，本项目的 `VIRTUAL_HOME/windows_exec/**/VirtualHome_Data/resources.assets.resS` 只保留在本机或外部存储：

```powershell
git lfs install
git lfs track
git status --short --branch
git ls-remote --heads origin
git fetch --prune origin
```

确认没有未拉取分支或远端新提交后再提交：

```powershell
git add .gitattributes README.md agent docs VIRTUAL_HOME
git status --short
git commit -m "集成 VirtualHome 虚拟家居环境"
git push origin master
```

如果 `git fetch` 后显示本地落后于远端，先处理远端更新：

```powershell
git pull --rebase origin master
```

遇到冲突时先解决冲突并运行基本启动测试，再 push。

## 敏感信息

不要提交：

- `agent/.env`
- 真实 API key
- 临时个人账号、token、Cookie

提交前可以扫描：

```powershell
rg -n "sk-[A-Za-z0-9_.-]+|API[_-]?key|DASHSCOPE_API_KEY|token" -g "!VIRTUAL_HOME/vhome/**" -g "!.git/**" .
```
