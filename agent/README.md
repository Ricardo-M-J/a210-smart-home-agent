# A210 智能家居边缘视觉 Agent

> 在 A210 开发板（RISC-V · 12 TOPS NPU · Linux Debian）上，做一个**智能家居边缘视觉 Agent**：
> 摄像头持续检测家居状态（有没有人、灯开没开、宠物、家电），Agent 接收「用户提问」和「异常事件」两种触发，
> 调用三个 Tool 拿数据、调云端大模型推理，回答组合式家居问题（"家里安全吗""是不是忘关灯了"）并智能告警。

---

## 一、为什么是"组合式判断"

智能家居的判断是 **有人 × 开灯 × 时间 × 房间 × 姿态** 的组合式开放判断，`if-else` 写不完，
只有 Agent 的语言理解能覆盖——这是 Agent 超越 `if-else` 的唯一理由，也是方案创新分的来源。

核心聚焦场景：**独居安全** = 多房间人数检测 + 有人→躺卧监测、无人→电源检查 + "家里安全吗"组合问答 + 忘关灯提醒。

---

## 二、架构总览

三层 + 事件驱动双触发源：

```
感知层（队友，持续流式运行）
  摄像头/iGibson仿真 → YOLO 检测（NPU） → 家居状态快照（文件 IPC）
                                            ├─→ HDMI 本地渲染（可选）
                                            └─→ 规则引擎发现异常 → 推事件

Agent 层（本项目核心，事件驱动）
  触发源① 用户提问 / ② 异常事件
    → Agent 循环（自写 function calling）
    → 调三个 Tool → 调云端大模型 → 回答/告警
    → 写记忆模块

交互层（本项目）
  Web 服务（Flask + 简单 HTML）+ 告警可视化
```

**关键理解**：感知层是"眼睛"（一直跑），Agent 是"大脑"（被触发才想）。两者通过**文件 IPC** 解耦——
感知进程原子写 JSON，Agent 轮询读。队友用 C++、我们用 Python，互不影响。

**硬件分工**（易混点）：Agent 循环、云端 LLM 调用、决策逻辑跑在 **CPU**；只有 YOLO 推理跑在 **NPU**。
两个计算单元各干各的，不是一回事。

---

## 三、目录结构

```
agent/
├── agent.py            Agent 核心：function calling 循环 + 断网降级 + 对话截断
├── event_engine.py     事件引擎：确定性规则 + 去重冷却
├── memory.py           SQLite 记忆：decisions / events / conversations
├── simulator.py        模拟感知进程（本地模拟摄像头持续采集）
├── runtime.py          运行时装配：共享 Agent + 事件监控线程 + 告警缓冲
├── config.py           配置加载（.env / 环境变量，绝不硬编码 API Key）
├── main.py             命令行入口（问答 / --watch 事件轮询 / --history）
├── web.py              Web 服务（Flask，监听 0.0.0.0）
├── tools/
│   ├── backend.py       端侧动作后端抽象（mock / real 可切换）★ 关键
│   ├── reader.py        快照文件读取（文件 IPC 消费方）
│   ├── capture_image.py 图像采集 Tool
│   ├── run_detection.py 模型推理 Tool
│   ├── make_decision.py 结果决策 Tool
│   ├── monitor_rules.py 监控规则 + 在家/离家模式 Tool
│   └── __init__.py      Tool 注册表（name → run 派发）
├── schema/
│   ├── CONTRACT.md      家居状态快照接口契约（字段枚举全表 + 文件 IPC 协议）
│   └── home_state_schema.json  快照 JSON Schema
├── mock/
│   └── __init__.py      9 个 Mock 场景（有人/无人 × 灯亮/灯灭 × 昼夜 + 躺卧）
├── templates/
│   └── index.html       前端页面（聊天框 + 状态面板 + 告警列表）
├── .env.example         环境变量模板
└── requirements.txt     依赖（requests + flask）
```

---

## 四、三个 Tool 与后端抽象（关键设计）

赛题硬要求「至少包含图像采集、模型推理、结果决策三个 Tool」，且要"完整实现可正常工作"。
这里有评分隐患：如果 Tool 只是"读文件"，评审会质疑"你的端侧推理在哪"。

**解决方式**：把"端侧动作"抽象成可替换的后端接口 [tools/backend.py](tools/backend.py)，Tool 只调接口，不关心实现。

| 接口 | 语义 | mock（当前） | real（上板后） |
|------|------|-------------|---------------|
| `capture()` | 主动采集一帧 | 读快照 | 调队友摄像头采集 |
| `latest_frame()` | 读最近缓存帧 | 读快照 | 读摄像头缓存 |
| `infer()` | 触发一次端侧推理 | 读快照 | 调队友 YOLO 推理 |

- `capture_image(mode="latest"/"fresh")`：`fresh` 走 `capture()`（主动采集），`latest` 走 `latest_frame()`（读缓存）
- `run_detection()`：走 `infer()`（主动触发推理）
- `make_decision()`：走云端 LLM 判断结果，落地告警 + 写 SQLite

后端由 `config.BACKEND` 选择（默认 `mock`）。上板后只需填充 `RealBackend` 三个 TODO 方法，
Tool 层、Agent 层一行不改——**队友选方案 A（可调用）还是方案 B（完全独立）都不用返工**。

> 核心认知：赛题不是要"设备平时关着、等命令才开"。设备持续运行（实时监控）是加分项，
> 但每个 Tool 必须保留"被主动触发、真实执行一次动作"的能力，读缓存只是性能优化路径。

---

## 五、接口契约（家居状态快照）

Agent 与感知层的唯一数据契约，详见 [schema/CONTRACT.md](schema/CONTRACT.md)。

- **交换方式**：文件 IPC，感知进程原子写 `HOME_STATE_FILE`，Agent 轮询读
- **结构**：`{ timestamp, rooms: [{ room, objects: [{category, ...}] }] }`
- **扩展方式**：改 `category` 枚举（person / light / pet / appliance），不改结构

```json
{
  "timestamp": "2026-08-20 23:10:00",
  "rooms": [
    {"room": "客厅", "objects": [
      {"category": "person", "count": 0, "pose": null},
      {"category": "light", "state": "on"}
    ]},
    {"room": "卧室", "objects": [
      {"category": "person", "count": 1, "pose": "lying"},
      {"category": "light", "state": "off"}
    ]}
  ]
}
```

---

## 六、异步监控 + 记忆（两级判断架构）

监控采用**两级判断**（对应赛题"端云协同 + Agent 自主判断"），职责清晰分层：

```
第一级：事件引擎（确定性，免费，可离线）
   读规则表 + 当前模式 → 扫快照 → 产出「疑似事件」
   （只描述"检测到了什么"，不判断"要不要报警"）
        ↓
第二级：Agent + 云端 LLM（智能）
   结合时间/房间/姿态上下文 → 判断是否真的异常
   → 异常则 make_decision 告警，正常则说明无需告警
```

### 监控规则（用户下指令，非硬编码）

用户下"我离开家了，有人进来就报警"→ Agent 解析 → `add_monitor_rule` 入库 → 后台按规则表持续检测。

| 规则类型 | 触发条件 | 备注 |
|---------|---------|------|
| `no_person_light_on` | 房间无人但灯亮 | 可能忘关灯 |
| `person_lying` | 非卧室有人躺卧 | 可能跌倒 |
| `person_enter` | 房间从无人→有人 | **仅离家模式下生效** |

### 在家/离家模式（规则的前置条件）

`person_enter` 这类"人员进入"规则，只有在**离家模式**下才武装——否则用户自己在家走动会误报。

| 模式 | 用户触发 | person_enter 规则 |
|------|---------|:---:|
| home（在家） | "我回来了" | 解除武装，不检测 |
| away（离家） | "我出门了" | 武装，检测人员进入 |

模式由 `set_home_mode` 工具写入 SQLite settings 表，事件引擎检测 `person_enter` 前先查模式。

### 边沿触发（避免重复告警）

事件引擎只在状态"从无→有"那一刻上报一次，持续命中不重复、状态消失后再出现才重新上报，
避免同一异常反复烧 LLM / 反复告警。

### 断网降级

云端 LLM 不可用时，事件触发退化为**保守告警**（规则命中即报，宁可多报不漏报）。

### 记忆

[memory.py](memory.py)：SQLite 五张表（零依赖），
`decisions`（决策）、`events`（疑似事件）、`conversations`（对话）、`rules`（监控规则）、`settings`（模式等键值状态）。

**事件链路**：模拟感知进程写快照 → 事件监控线程轮询 → 事件引擎检测 → Agent 决策 → 告警入缓冲 + 落库。

---

## 七、运行方式

### 命令行（本地 Mock 闭环）

```bash
cd agent
pip install -r requirements.txt

python main.py                              # 交互式问答（默认场景）
python main.py --scene night_nobody_on --ask "家里安全吗？"
python main.py --list-scenes                # 列出所有场景
python main.py --watch --scene night_nobody_on   # 事件轮询
python main.py --history decisions          # 查记忆（decisions/events/conversations/rules）
```

### Web 服务

```bash
python web.py
# 打开 http://127.0.0.1:8000
```

页面含：聊天框（问答）、场景切换（模拟感知层）、当前家居状态面板、事件告警列表。

### 配置（.env）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DASHSCOPE_API_KEY` | 云端大模型 API Key（绝不硬编码） | — |
| `DASHSCOPE_BASE_URL` | OpenAI 兼容端点 | token-plan 端点 |
| `DASHSCOPE_MODEL` | 模型名 | `qwen3.6-flash` |
| `HOME_STATE_FILE` | 快照文件路径 | `./mock/home_state.json` |
| `BACKEND` | 端侧后端 `mock`/`real` | `mock` |
| `WEB_HOST` / `WEB_PORT` | Web 监听 | `0.0.0.0` / `8000` |

---

## 八、稳定性设计（保命原则）

- **断网降级**：云端 LLM 调用失败时，Agent 不抛异常，自动切本地规则回答
- **Mock/真实双通道**：`BACKEND` 一键切换，队友延误或现场翻车可切回 Mock，演示照常
- **零编译依赖**：只用 `requests` + `flask` + 标准库，规避 riscv64 上的 Rust 扩展编译地狱（这是不用 Gradio、不用 dashscope SDK 的原因）

---

## 九、当前进度

**已完成**：
1. ✅ 接口契约文档 + JSON Schema
2. ✅ Mock 数据（9 场景）
3. ✅ 三个 Tool + 后端抽象（mock/real 可切换）
4. ✅ Agent function calling 循环 + 断网降级 + 对话截断
5. ✅ 异步监控（规则表驱动 + 在家/离家模式 + 边沿触发 + 两级判断）+ SQLite 记忆
6. ✅ Web 服务（Flask + 简单 HTML）+ 模拟感知进程
7. ✅ 部署脚本（install.sh / run.sh / systemd unit）

**待办**：
- [ ] 冻结接口契约（队友签字）
- [ ] 填充 `RealBackend`（等队友采集/推理接口）
- [ ] 评测 harness（eval_cases + judge + pytest）
- [ ] 上板部署 + systemd 自启 + 稳定性连测
- [ ] 设计文档 + 演示视频
