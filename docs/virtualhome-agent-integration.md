# VirtualHome 与 A210 Agent 集成使用文档

本文档说明如何启动两个 UI，并测试 VirtualHome 虚拟摄像头/场景反馈与 Agent 的连通性。

## 当前结论

- Agent 已支持 `BACKEND=virtualhome`。
- 当前家居状态统一为四个房间：`living_room`、`bedroom`、`kitchen`、`bathroom`。
- 旧的 `bedroom1`/`bedroom2` 仅作为兼容输入，内部会归一化为 `bedroom`。
- Agent Web 的“当前家居状态”以四个房间卡片展示，实时显示人、猫、狗、陌生人、灯光、音乐和异常摘要。
- Agent 对话框可以直接控制 VirtualHome 设备：优先通过 VirtualHome Python API attach 到已打开的 `VirtualHome.exe`，再用 `expand_scene` 修改真实 Unity 环境图里的房间灯光/媒体设备状态。
- 文字灯光叠加层默认关闭；需要调试时才设置 `SHOW_AGENT_DEVICE_OVERLAY=1` 打开。
- VirtualHome 样本场景已对齐：`whole_home_overview`、`multi_camera_layout`、`bedroom_person`、`kitchen_pet`、`fire_smoke`、`health_event`、`away_mode_stranger`。
- VirtualHome 可以通过 `POST /api/virtualhome/frame` 把帧流和外部识别结果传给 Agent；Agent 返回 `a210.agent_response.v1`，其中包含 `home_state` 和 `virtualhome.feedback.v1` 动作。
- Agent 终端会输出每帧 `[virtualhome-sync]` 同步日志；普通同步不再进入 Agent UI 对话框。
- Agent UI 顶部控制区改为“家居模式”：`居家(home)` / `离家(away)`。
- Agent UI 的“当前家居状态”以四个房间卡片实时显示人、猫、狗、陌生人等数量；只有危险、陌生人、健康、跌倒、宠物独处等异常才会在对话框主动提示。
- VirtualHome 面板中 01 可连接 `VirtualHome.exe` 的 Unity live camera；02 保留原来的多房间固定摄像头布局；03-07 保留各自原始样本视频里的房间镜头、人物自然行走、小猫、烟雾等内容，同时把“当前正在显示的帧”实时保存并推给 Agent。
- 反馈动作写入：
  - `VIRTUAL_HOME/outputs/agent_feedback/virtualhome_feedback_actions.jsonl`
  - `VIRTUAL_HOME/outputs/agent_bridge/agent_feedback_actions.jsonl`
  - `VIRTUAL_HOME/outputs/agent_bridge/simulated_device_state.json`

## 为什么 web.py 以前无法导入 mock

原来的 `web.py` 在文件顶层执行了 `from mock import SCENARIOS`。如果从项目根目录、不同工作目录、或 `BACKEND=virtualhome` 的情况下启动，Python 仍会先加载 `mock`，因此会出现路径/模块导入问题。

同时 `runtime.py` 顶层导入 `simulator.py`，而 `simulator.py` 也顶层导入 `mock`，所以即使并不使用 mock 后端，也会提前碰到 `mock`。

现在已经修正为按后端惰性加载：只有 `BACKEND=mock` 时才导入 mock/simulator。

## 环境

不要新建 conda 环境。VirtualHome 已自带环境：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe
```

Agent Web 使用当前 Python 环境运行。如果缺 Flask/requests：

```powershell
cd D:\AAApersonal\a210_Vision_Agent\a210-smart-home-agent\agent
python -m pip install -r requirements.txt
```

## 配置

`agent/.env` 至少需要：

```text
BACKEND=virtualhome
VIRTUAL_HOME_DIR=../VIRTUAL_HOME
VIRTUAL_HOME_SCENE=kitchen_pet
VIRTUAL_HOME_UNITY_CONTROL=1
VIRTUAL_HOME_UNITY_PORT=8080
VIRTUAL_HOME_PYTHON=../VIRTUAL_HOME/vhome/Scripts/python.exe
```

云端模型可选。如果配置 API key 后仍显示云端不可用，检查三点：

```powershell
cd D:\AAApersonal\a210_Vision_Agent\a210-smart-home-agent\agent
python -c "import config; print(bool(config.DASHSCOPE_API_KEY), len(config.DASHSCOPE_API_KEY or '')); print(config.DASHSCOPE_BASE_URL); print(config.DASHSCOPE_MODEL)"
```

确认 key 没有多余空格，改完 `.env` 后必须重启 `python web.py`。
也可以在 Agent Web 启动后直接查云端健康状态：

```powershell
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8019/api/llm/status').read().decode('utf-8'))"
```

返回 `ok:true` 表示 key、模型名、URL 和网络链路都正常。

## 启动两个 UI

1. 先启动真实 VirtualHome.exe，并确认它监听 HTTP API。默认端口是 8080：

```powershell
cd D:\AAApersonal\a210_Vision_Agent\a210-smart-home-agent
.\VIRTUAL_HOME\windows_exec\windows_exec.v2.2.4\VirtualHome.exe -screen-fullscreen 0 -screen-quality 4 -http-port=8080
```

如果已经手动打开了 `VirtualHome.exe`，只要它是 `-http-port=8080` 即可。可以这样检查：

```powershell
python -c "import urllib.request,json; req=urllib.request.Request('http://127.0.0.1:8080', data=json.dumps({'id':'probe','action':'idle'}).encode(), headers={'Content-Type':'application/json'}, method='POST'); print(urllib.request.urlopen(req).read().decode('utf-8'))"
```

2. 启动 Agent Web UI。若 8000 已被旧进程占用，建议直接换一个新端口，例如 8019：

```powershell
cd D:\AAApersonal\a210_Vision_Agent\a210-smart-home-agent
$env:WEB_PORT="8019"
python .\agent\web.py
```

浏览器打开：

```text
http://127.0.0.1:8019
```

不要打开 `http://0.0.0.0:8019`。`0.0.0.0` 是服务监听地址，不是浏览器访问地址。

3. 启动 VirtualHome 展示面板。需要查看 01 的 Unity 实时摄像头时，再在面板右侧点击 `Connect API` 连接同一个已打开的 `VirtualHome.exe`：

```powershell
cd D:\AAApersonal\a210_Vision_Agent\a210-smart-home-agent
$env:A210_AGENT_URL="http://127.0.0.1:8019"
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\VIRTUAL_HOME\src\virtualhome_env\showcase_panel.py
```

## 连通性测试

列出 Agent 看到的 VirtualHome 场景：

```powershell
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8019/api/scenes').read().decode('utf-8'))"
```

### Agent 对话控制 VirtualHome

在 Agent Web 的对话框中输入以下自然语言命令：

```text
打开厨房灯
关闭卫生间灯
打开客厅灯
播放卧室音乐
停止卧室音乐
```

预期结果：

- Agent 对话区返回“已通过 VirtualHome API 打开/关闭某房间灯光”或“已通过 VirtualHome API 播放/停止某房间音乐”。
- 已打开的 `VirtualHome.exe` 里的真实房间亮度会变化；卧室音乐优先映射到 VirtualHome 自带的 `radio`，客厅/厨房会映射到可开关媒体设备如 `tv/computer`。
- `VIRTUAL_HOME/outputs/agent_bridge/simulated_device_state.json` 被更新。
- VirtualHome 面板切到 01 `whole_home_overview`，点击 `Connect API` 后看到的是 Unity 摄像头画面；Agent 控制后面板会自动刷新摄像头帧。

也可以用接口快速验证：

```powershell
python -c "import urllib.request,json; req=urllib.request.Request('http://127.0.0.1:8019/api/chat', data=json.dumps({'question':'打开卧室灯'}, ensure_ascii=False).encode('utf-8'), headers={'Content-Type':'application/json'}, method='POST'); print(urllib.request.urlopen(req).read().decode('utf-8'))"
```

用 VirtualHome API 直接查看卧室灯/开关节点是否变成 `ON`：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe -c "import sys,json; sys.path.insert(0, r'VIRTUAL_HOME/virtualhome'); from virtualhome.simulation.unity_simulator import comm_unity; comm=comm_unity.UnityCommunication(port='8080', timeout_wait=5, logging=False); ok,g=comm.environment_graph(); nodes={n['id']:n for n in g['nodes']}; print(json.dumps({i:nodes[i].get('states') for i in [103,104,175]}, ensure_ascii=True))"
```

查看 Agent 侧设备状态和 Unity 控制结果：

```powershell
Get-Content .\VIRTUAL_HOME\outputs\agent_bridge\simulated_device_state.json -Raw -Encoding UTF8
```

### VirtualHome 触发 Agent 同步与主动提示

在 VirtualHome 面板中点击人员计数、无人关灯、宠物留守、火灾烟雾、健康助手、陌生人等场景时，面板会把当前样本帧和外部识别结果发到 Agent 的 `/api/virtualhome/frame`。Agent 会同步四房间状态；若检测到异常，Agent Web 对话区会主动插入一条提醒。

现在的输出分工是：

- Agent 终端：每次推帧都会打印 `[virtualhome-sync] scene=... rooms: 客厅=人0/猫0/狗0/陌生人0; ...`，用于确认 VirtualHome 到 Agent 的实时通信。
- Agent UI 家居模式：点击 `居家` 或 `离家` 会写入 Agent 的 home/away 模式，离家模式下安防相关规则会更敏感。
- Agent UI 状态面板：四个房间卡片实时显示人数、猫狗数量、陌生人数量、灯光/音乐状态和异常摘要。
- Agent UI 对话框：只显示异常主动提醒，例如厨房宠物独处、火灾烟雾、陌生人、健康异常、疑似跌倒。普通人员计数、无人关灯等同步/自动化事件不会进入对话框。

07 `人物进入与离家告警` 的模式验证方式：

1. Agent UI 先切到 `居家`，再点 VirtualHome 面板里的 07；Agent 只同步人物/陌生人数量，返回动作应为 `none`。
2. Agent UI 再切到 `离家`，重新点 07；Agent 返回 `raise_alert home_security_alarm`，对话框会主动提示安防告警。

03 `人员计数和无人关灯` 的实时验证方式：

1. 确保 Agent Web 和 `VirtualHome.exe` 已启动。
2. 在 VirtualHome 面板点击 03 `人员计数和无人关灯`。
3. Agent Web 的“当前家居状态”里，卧室卡片会随面板实时推送显示 `人数 0 -> 1 -> 0`。
4. 当事件进入 `person_left` 后，Agent 返回 `set_light bedroom_ceiling_light=off`；样本画面继续按原来的卧室镜头播放到关灯反馈段，同时 Agent 会写入设备状态并尝试通过 VirtualHome API 控制真实 Unity 房间灯光。

也可以用桥接脚本模拟一次 VirtualHome 场景推送：

推送一个厨房宠物样本帧：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\VIRTUAL_HOME\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --scene kitchen_pet --max-frames 1
```

预期输出包含：

```text
scene=kitchen_pet status=ok action=raise_alert_and_set_light target=kitchen_pet_guard_and_light value=alert_on_light_off
```

推送全部样本：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\VIRTUAL_HOME\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --scene all --max-frames 7 --interval 0.05
```

预期动作：

- `bedroom_person` -> `set_light`，`bedroom_ceiling_light=off`
- `kitchen_pet` -> `raise_alert_and_set_light`，`kitchen_ceiling_light=off`
- `fire_smoke` -> `raise_alert`，`fire_alarm`
- `health_event` -> `set_environment`，卧室冷光/音乐辅助
- `away_mode_stranger` -> `raise_alert`，`home_security_alarm`

查看 Agent 当前四房间状态：

```powershell
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8019/api/state').read().decode('utf-8'))"
```

查看 VirtualHome 侧收到的动作：

```powershell
Get-Content .\VIRTUAL_HOME\outputs\agent_bridge\simulated_device_state.json -Raw
Get-Content .\VIRTUAL_HOME\outputs\agent_feedback\virtualhome_feedback_actions.jsonl -Tail 7
```

查看 Agent 主动提示队列：

```powershell
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8019/api/notices?since=0').read().decode('utf-8'))"
```

## 实时摄像头文件流

如果 VirtualHome showcase 面板连接了 Unity live camera，01 会更新：

```text
VIRTUAL_HOME/outputs/showcase_panel/live_overview/latest_overview_camera.jpg
```

可以用桥接脚本跟随这个文件，把实时图像路径发送给 Agent：

```powershell
.\VIRTUAL_HOME\vhome\Scripts\python.exe .\VIRTUAL_HOME\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --use-default-live-file --scene whole_home_overview --max-frames 10
```

当前没有 A210/YOLO 时，实时文件流只负责把摄像头帧交给 Agent；结构化检测结果仍使用样本或外部传入结果。接上 A210/YOLO 后，把其输出放在请求体的 `external_result` 字段即可。

03-07 交互样本播放时不会切换到 01 的全屋摄像头；它们会把当前播放帧持续写入：

```text
VIRTUAL_HOME/outputs/showcase_panel/live_agent_stream/<scene>/latest.jpg
```

这个文件对应面板里正在显示的原样本摄像头画面，也是发送给 Agent/YOLO 的实时图像路径。

## 当前验证结果

本机已验证：

- 新 Agent Web：`http://127.0.0.1:8019`
- `/api/scenes` 返回 7 个 VirtualHome 场景。
- `/api/virtualhome/frame` 可接收 VirtualHome 样本帧。
- `/api/state` 返回四房间状态，不再返回 `bedroom1/bedroom2`。
- 全部 7 个 VirtualHome 样本都能返回 Agent feedback。
- `VirtualHome.exe` 真实 API 已验证：Agent 对话“打开卧室灯”会让 Unity graph 中卧室 `tablelamp/lightswitch` 从 `OFF` 变成 `ON`；“停止卧室音乐”会让卧室 `radio` 变成 `OFF`。
- `simulated_device_state.json` 仍保留 Agent 侧状态、Unity 控制返回值和告警联动日志，作为 UI/排障辅助。

## 端口排查

如果 8000 被旧服务占用：

```powershell
netstat -ano | findstr :8000
```

不确定旧进程能否关闭时，直接换端口启动：

```powershell
$env:WEB_PORT="8019"
python .\agent\web.py
```

