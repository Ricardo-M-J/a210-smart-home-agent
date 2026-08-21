# agent-butler 队友开发 README

这个文档给两条并行工作线使用：

- 云端 API + Agent 队友：负责自然语言交互、事件解释、用户问答和动作建议。
- 虚拟家居环境队友：负责生成家庭场景图像帧，并按协议推送给 A210 板端。

板端同学已经提供 `agent-butler` C++ 程序，负责 TCP 收图、YOLO11 检测、YOLO11-pose 跌倒判断、手环数据模拟、规则告警和动作脚本钩子。

## 1. 系统分工

```text
虚拟家居环境 / PC 摄像头
        |
        | TCP: JSON header + JPEG bytes
        v
A210 agent-butler 板端程序
        |
        | 事件 JSON / 日志 / action_hook.sh
        v
云端 Agent / 自然语言交互
        |
        | 用户问答、事件解释、动作建议
        v
用户 / 演示界面 / 语音或文本终端
```

A210 板端默认监听：

```bash
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000 \
  --action-hook scripts/action_hook.sh
```

板端安装目录：

```text
install/a210_linux/torq_agent-butler_demo/
```

## 2. 共同协议

### 2.1 房间枚举

所有模块必须使用下面五个 `room` 字符串，不要另起名字：

```text
living_room
bedroom1
bedroom2
kitchen
bathroom
```

### 2.2 PC 到 A210 的帧协议

每一帧由一行 JSON header 加 JPEG bytes 组成：

```json
{"room":"kitchen","frame_id":1,"timestamp_ms":123456789,"jpeg_bytes":12345}
```

header 后面紧跟 `jpeg_bytes` 长度的 JPEG 二进制数据。header 以 `\n` 结尾。

字段含义：

```text
room          房间名，必须是五个枚举之一
frame_id      单调递增帧编号
timestamp_ms  毫秒时间戳
jpeg_bytes    后续 JPEG 二进制长度
```

### 2.3 A210 到 Agent 的事件协议

板端触发事件时会打印并调用：

```bash
scripts/action_hook.sh '<event-json>'
```

事件 JSON 示例：

```json
{
  "event_type": "PET_IN_DANGER_ROOM",
  "room": "kitchen",
  "severity": "warning",
  "message": "Pet detected in kitchen without a person nearby.",
  "timestamp_ms": 123456789,
  "detections": [
    {"label":"cat","score":0.82,"box":[120,80,300,360]}
  ],
  "bracelet": {
    "spo2": 98,
    "heart_rate": 76,
    "stress": 34,
    "timestamp_ms": 123456789
  }
}
```

当前事件类型：

```text
PET_IN_DANGER_ROOM  宠物独自在厨房等危险区域
FALL_DETECTED       卧室/卫生间疑似跌倒
HEALTH_ABNORMAL     手环模拟指标异常
```

默认事件日志文件：

```text
agent_butler_events.log
```

可以通过环境变量改日志位置：

```bash
export AGENT_BUTLER_LOG=/tmp/agent_butler_events.log
```

## 3. 云端 API + Agent 队友任务

### 3.1 目标

实现自然语言交互能力，满足赛题“自然语言交互”要求。用户能用中文问：

```text
刚才厨房发生了什么？
现在家里安全吗？
为什么触发了跌倒告警？
如果老人摔倒了，下一步应该做什么？
把最近一分钟的事件总结一下。
```

Agent 应读取板端事件日志，结合当前告警和手环数据，给出自然语言回答和建议动作。

### 3.2 推荐目录

在 `examples/agent-butler/python/` 下实现：

```text
python/
├── cloud_agent.py
├── event_store.py
├── llm_client.py
├── config.example.json
└── requirements.txt
```

各文件职责：

```text
cloud_agent.py       命令行交互入口，负责用户输入、调用工具、输出回答
event_store.py       读取 agent_butler_events.log，解析最近事件
llm_client.py        封装云端大模型 API 调用
config.example.json  API 地址、模型名、日志路径等配置样例
requirements.txt     Python 依赖
```

### 3.3 API 配置

优先使用 OpenAI-compatible 调用方式，方便切换通义千问、OpenAI 或其他兼容服务。

环境变量建议：

```bash
export AGENT_LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export AGENT_LLM_API_KEY="你的 API Key"
export AGENT_LLM_MODEL="qwen-plus"
export AGENT_BUTLER_LOG="./agent_butler_events.log"
```

不要把 API Key 写进代码或提交到仓库。

### 3.4 Agent 工具设计

Agent 至少实现 4 个工具函数：

```python
def get_recent_events(minutes: int = 5) -> list[dict]:
    """读取最近 N 分钟事件。"""


def summarize_home_state() -> dict:
    """基于事件日志返回当前家庭状态摘要。"""


def recommend_actions(event: dict) -> list[str]:
    """根据事件类型给出建议动作。"""


def answer_user_question(question: str) -> str:
    """把用户问题、最近事件和工具结果交给云端 LLM，返回中文回答。"""
```

### 3.5 Prompt 要求

系统提示词建议包含：

```text
你是一个智能家居管家 Agent。
你只能基于板端事件日志和用户问题回答，不要编造未观测到的事情。
当事件 severity 为 critical 时，优先建议联系家人、紧急联系人或 120。
当事件是 HEALTH_ABNORMAL 时，说明这是模拟手环数据，不要给出医疗诊断。
回答要简洁、明确、中文。
```

### 3.6 最小可运行版本

第一版不需要复杂框架，命令行交互即可：

```bash
python3 cloud_agent.py --log ./agent_butler_events.log
```

交互示例：

```text
用户：刚才厨房有什么异常？
Agent：最近厨房触发了 PET_IN_DANGER_ROOM，检测到宠物且未检测到人员。建议立即查看厨房，必要时通过语音提醒或联系主人。
```

### 3.7 验收标准

云端 Agent 队友完成后，应满足：

```text
能读取 action_hook.sh 写出的事件日志
能解析 PET_IN_DANGER_ROOM / FALL_DETECTED / HEALTH_ABNORMAL
能用中文回答最近状态、原因和建议动作
API Key 通过环境变量读取
网络失败时能给出本地降级回答，不直接崩溃
```

## 4. 虚拟家居环境队友任务

### 4.1 目标

实现一个 PC 端虚拟家庭环境，把不同房间的图像帧推送给 A210。第一版不追求复杂物理仿真，优先保证演示稳定。

推荐优先级：

```text
1. 本地图像/视频帧发送器
2. 简单 2D/3D 虚拟房间场景
3. PyBullet 或类似仿真环境
```

先跑通协议，再做漂亮场景。

### 4.2 推荐目录

在 `examples/agent-butler/simulator/` 下实现：

```text
simulator/
├── send_frame.py
├── send_video.py
├── virtual_home.py
├── assets/
│   ├── living_room/
│   ├── bedroom1/
│   ├── bedroom2/
│   ├── kitchen/
│   └── bathroom/
└── README.md
```

各文件职责：

```text
send_frame.py    发送单张图片到板端
send_video.py    从视频文件抽帧发送到板端
virtual_home.py  生成或读取虚拟家庭场景帧，并推给板端
assets/          每个房间的测试图片或录制帧
```

### 4.3 最小发送脚本

必须实现如下命令：

```bash
python3 send_frame.py \
  --host 192.168.0.23 \
  --port 9000 \
  --room kitchen \
  --image ../model/bus.jpg \
  --repeat 5 \
  --interval 0.2
```

发送逻辑：

```python
import json
import socket
import time

with open(image_path, "rb") as f:
    jpeg = f.read()

with socket.create_connection((host, port)) as sock:
    for frame_id in range(1, repeat + 1):
        header = {
            "room": room,
            "frame_id": frame_id,
            "timestamp_ms": int(time.time() * 1000),
            "jpeg_bytes": len(jpeg),
        }
        sock.sendall(json.dumps(header).encode("utf-8") + b"\n")
        sock.sendall(jpeg)
        time.sleep(interval)
```

### 4.4 场景设计建议

准备五个房间：

```text
living_room  正常活动场景，有人/无人均可
bedroom1     有人场景，用于触发姿态检测
bedroom2     有人或跌倒模拟场景
kitchen      宠物无人场景，用于触发危险告警
bathroom     有人/跌倒模拟场景
```

建议每个房间至少准备 3 类素材：

```text
normal.jpg       正常场景
person.jpg       有人场景
danger.jpg       危险或异常场景
```

注意：当前板端 YOLO11 是 COCO 检测模型，能稳定识别 `person`、`cat`、`dog`、`chair`、`bed` 等通用类别，但不会直接识别“厨房/卧室”。房间名由 PC 发送的 `room` 字段决定。

### 4.5 演示脚本建议

为比赛演示准备 3 个固定脚本：

```bash
# 场景 1：厨房宠物无人，触发 PET_IN_DANGER_ROOM
python3 send_frame.py --host $BOARD_IP --room kitchen --image assets/kitchen/danger.jpg --repeat 5

# 场景 2：卧室有人，板端启动姿态模型
python3 send_frame.py --host $BOARD_IP --room bedroom1 --image assets/bedroom1/person.jpg --repeat 5

# 场景 3：卫生间跌倒模拟，触发 FALL_DETECTED
python3 send_frame.py --host $BOARD_IP --room bathroom --image assets/bathroom/fall.jpg --repeat 5
```

跌倒检测依赖姿态关键点。若真实图片不稳定，先准备容易被姿态模型识别的人体跌倒图片；必要时让板端同学加一个 `--mock-fall` 演示开关。

### 4.6 验收标准

虚拟环境队友完成后，应满足：

```text
能连接 A210 的 9000 端口
能按协议发送 JPEG 帧
能切换五个 room
能重复发送同一场景，稳定触发连续帧规则
断线后能重新连接
能提供至少 3 个比赛演示场景脚本
```

## 5. 联调流程

### 5.1 板端启动

在 A210 上：

```bash
cd torq_agent-butler_demo
export AGENT_BUTLER_LOG=./agent_butler_events.log
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000 \
  --action-hook scripts/action_hook.sh
```

### 5.2 PC 发送场景

在 PC 上：

```bash
export BOARD_IP=192.168.0.23
python3 simulator/send_frame.py --host $BOARD_IP --room kitchen --image simulator/assets/kitchen/danger.jpg --repeat 5
```

### 5.3 Agent 问答

在能访问事件日志和云端 API 的机器上：

```bash
export AGENT_LLM_API_KEY="你的 API Key"
export AGENT_LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export AGENT_LLM_MODEL="qwen-plus"
python3 python/cloud_agent.py --log ./agent_butler_events.log
```

用户可问：

```text
最近一分钟有什么告警？
厨房为什么报警？
现在需要联系紧急联系人吗？
```

## 6. 比赛展示话术

推荐演示顺序：

```text
1. 展示 PC 虚拟家居环境，选择厨房宠物无人场景。
2. PC 通过网线把 kitchen 帧发到 A210。
3. A210 端侧 YOLO11 检测到宠物且无人，规则 Agent 触发告警。
4. action_hook.sh 写入事件日志。
5. 用户用自然语言询问“刚才厨房发生了什么”。
6. 云端 Agent 读取事件日志，调用大模型，总结原因并建议动作。
7. 再切换卧室/卫生间场景，展示姿态检测和跌倒告警。
```

核心表达：

```text
端侧负责实时视觉感知和安全决策，云端负责自然语言理解和解释，二者通过结构化事件协同。
```

## 7. 当前边界

```text
房间识别由 PC 端 room 字段提供，不由视觉模型分类。
手环数据目前由板端随机模拟。
真实电话、邮件、TTS、灯光、热水和音乐控制先通过 action_hook.sh 预留。
自然语言部分优先调用云端模型，不在 A210 本地跑大语言模型。
```
