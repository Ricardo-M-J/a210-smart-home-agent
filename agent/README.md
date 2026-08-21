# A210 智能家居边缘视觉 Agent

> 在 A210 开发板（RISC-V · 12 TOPS NPU · Linux Debian）上，做一个**智能家居边缘视觉 Agent**：
> 板端 YOLO 检测全屋状态（有人/有猫/有狗/跌倒），Agent 接收「用户提问」和「可疑事件」两种触发，
> 让用户用自然语言**动态布置监控任务**，Agent 自主判断、调云端大模型推理、回答并告警。

---

## 一、核心价值：规则由用户下指令，LLM 动态生成

传统做法（也是最初的方案）是：开发者把"什么算异常"写死成枚举（宠物危险/跌倒/…），LLM 只做"翻译"。
这本质上还是硬编码，Agent 退化成对话工具。

本项目的核心设计是：**规则不是预设枚举，而是 LLM 从用户指令动态生成的条件**。

- 用户说"厨房有猫没人就报警" → LLM 生成 `{"room":"kitchen","has_cat":true,"has_person":false}`
- 用户说"有人跌倒就报警" → `{"fall_like":true}`
- 用户说"我出门了，有人进来就报警" → 先设离家模式，再生成 `{"has_person":true}` + 要求 `away` 模式

事件引擎只提供一个**通用匹配器**，不预设任何"异常类型"。什么算异常，由用户 + LLM 决定——这才是赛题要的"自主决策"。

---

## 二、架构：三层 + 两级判断

```
感知层（队友，C++）
  摄像头 → YOLO 检测 → 维护全屋状态表 → 原子写快照 JSON
        （只做感知，不做"算不算异常"的判断）

Agent 层（本项目，Python）
  触发源① 用户提问 / ② 事件引擎发现可疑事件
    → 通用匹配 check(快照, 规则) → 边沿触发
    → 调云端 LLM 二次判断 → 告警/回答
    → 写记忆

交互层（本项目）
  Web 服务（Flask + 简单 HTML）：聊天 + 状态面板 + 告警列表
```

**两级判断**：

1. **事件引擎**（确定性，免费，可离线）：按规则表扫快照，产出「可疑事件」——只描述"检测到了什么"，不判断"要不要报警"。
2. **Agent + 云端 LLM**（智能）：结合时间/房间/上下文，做最终判断是否告警。

**硬件分工**：Agent 循环、云端 LLM 调用、决策跑在 CPU；只有 YOLO 推理跑在 NPU。

---

## 三、目录结构

```
agent/
├── agent.py            Agent 核心：function calling 循环 + 断网降级 + 对话截断
├── event_engine.py     事件引擎：通用条件匹配 check() + 边沿触发
├── memory.py           SQLite 记忆：decisions / events / conversations / rules / settings
├── simulator.py        模拟感知进程（本地模拟摄像头持续采集）
├── runtime.py          运行时装配：共享 Agent + 事件监控线程 + 告警缓冲
├── config.py           配置加载（.env / 环境变量，绝不硬编码 API Key）
├── main.py             命令行入口（问答 / --watch 事件轮询 / --history）
├── web.py              Web 服务（Flask，监听 0.0.0.0）
├── tools/
│   ├── backend.py       端侧动作后端抽象（mock / real 可切换）
│   ├── reader.py        快照文件读取（文件 IPC 消费方）
│   ├── capture_image.py 图像采集 Tool
│   ├── run_detection.py 模型推理 Tool
│   ├── make_decision.py 结果决策 Tool
│   ├── monitor_rules.py 监控规则 + 在家/离家模式 Tool
│   └── __init__.py      Tool 注册表
├── mock/
│   └── __init__.py      Mock 场景（全屋聚合格式）
├── templates/
│   └── index.html       前端页面（聊天框 + 状态面板 + 告警列表）
├── .env.example         环境变量模板
└── requirements.txt     依赖（requests + flask）
```

---

## 四、三个核心 Tool 与后端抽象

赛题硬要求「至少包含图像采集、模型推理、结果决策三个 Tool」。为应对"Tool 只是读文件"的评分质疑，
把"端侧动作"抽象成可替换的后端接口 [tools/backend.py](tools/backend.py)。

| 接口 | 语义 | mock | real（上板） |
|------|------|------|-------------|
| `capture()` | 主动采集一帧 | 读快照 | 读队友写的快照 |
| `latest_frame()` | 读最近缓存帧 | 读快照 | 读队友写的快照 |
| `infer()` | 触发端侧推理 | 读快照 | 读队友写的快照 |

- `capture_image(mode="latest"/"fresh")`：fresh 走 `capture()`，latest 走 `latest_frame()`
- `run_detection()`：走 `infer()`
- `make_decision()`：落地告警 + 写 SQLite

后端由 `config.BACKEND` 选择（默认 `mock`）。上板后改成 `real`，读队友 C++ 写的全屋快照。

> 核心认知：设备持续运行（实时监控）是加分项，但每个 Tool 必须保留"被主动触发、真实执行一次动作"的能力，读缓存只是性能优化路径。

---

## 五、快照契约（全屋聚合）

Agent 与感知层的唯一数据契约，完整定义见 [docs/board-snapshot-contract.md](../docs/board-snapshot-contract.md)。

- **交换方式**：文件 IPC，感知进程（队友 C++）原子写 `HOME_STATE_FILE`，Agent 轮询读
- **格式**：全屋聚合，五个房间每个带 4 个信号字段

```json
{
  "timestamp_ms": 123456789,
  "rooms": {
    "living_room": {"has_person": false, "has_cat": false, "has_dog": false, "fall_like": false},
    "bedroom1":    {"has_person": true,  "has_cat": false, "has_dog": false, "fall_like": true},
    "kitchen":     {"has_person": false, "has_cat": true,  "has_dog": false, "fall_like": false},
    "...": "..."
  }
}
```

房间名英文（`living_room` 等），中文映射在 Agent 侧做。

---

## 六、动态监控 + 记忆

### 规则（用户下指令，LLM 生成条件）

规则是 LLM 从用户指令生成的条件字典，存在 SQLite `rules` 表。信号字段固定（YOLO 能力决定）：

- 每个房间：`has_person` / `has_cat` / `has_dog` / `fall_like`
- 房间：`living_room` / `bedroom1` / `bedroom2` / `kitchen` / `bathroom`
- 时间：`is_night`（是否夜间）

### 在家/离家模式（规则的前置条件）

`home` / `away` 两个固定模式。某些规则（如"有人进入报警"）只有在 `away` 模式才武装，
否则用户自己在家走动会误报。模式由 `set_home_mode` 工具写入，事件引擎检测前查模式。

### 边沿触发（避免重复告警）

事件引擎只在状态"从无→有"那一刻上报一次，持续命中不重复、状态消失后再出现才重新上报，
避免同一异常反复烧 LLM。

### 断网降级

云端 LLM 不可用时，事件触发退化为**保守告警**（规则命中即报，宁可多报不漏报）。

### 记忆

[memory.py](memory.py)：SQLite 五张表（零依赖），
`decisions`（决策）、`events`（可疑事件）、`conversations`（对话）、`rules`（监控规则）、`settings`（模式等）。

---

## 七、运行方式

### 命令行（本地 Mock 闭环）

```bash
cd agent
pip install -r requirements.txt

python main.py --scene pet_in_kitchen --ask "家里有宠物在危险区域吗？"
python main.py --list-scenes                 # 列出 Mock 场景
python main.py --watch --scene pet_in_kitchen   # 事件轮询
python main.py --history rules               # 查规则/记忆
```

### Web 服务

```bash
python web.py
# 打开 http://127.0.0.1:8000
```

### 配置（.env）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DASHSCOPE_API_KEY` | 云端大模型 API Key（绝不硬编码） | — |
| `DASHSCOPE_BASE_URL` | OpenAI 兼容端点 | token-plan 端点 |
| `DASHSCOPE_MODEL` | 模型名 | `qwen3.6-flash` |
| `HOME_STATE_FILE` | 快照文件路径 | `./mock/home_state.json`（上板改 `/tmp/home_state.json`） |
| `BACKEND` | 端侧后端 `mock`/`real` | `mock` |
| `WEB_HOST` / `WEB_PORT` | Web 监听 | `0.0.0.0` / `8000` |

---

## 八、稳定性设计

- **断网降级**：云端 LLM 失败时不抛异常，自动切本地规则
- **Mock/真实双通道**：`BACKEND` 一键切换，队友延误或现场翻车可切回 Mock
- **零编译依赖**：只用 `requests` + `flask` + 标准库，规避 riscv64 上的 Rust 扩展编译地狱（不用 Gradio、不用 dashscope SDK）

---

## 九、当前进度

**已完成**：
1. ✅ 动态规则（LLM 生成条件）+ 通用匹配引擎
2. ✅ 三个核心 Tool + 后端抽象（mock/real）
3. ✅ 在家/离家模式 + 边沿触发 + 断网降级
4. ✅ SQLite 记忆（五表）
5. ✅ Web 服务（Flask + 简单 HTML）+ 模拟感知进程
6. ✅ 部署脚本（install.sh / run.sh / systemd）+ 部署文档

**待办**：
- [ ] 队友 C++ 上板编译验证（代码已改，待编译）
- [ ] 上板联调（板端快照 ↔ Agent 读写）
- [ ] 评测 harness（eval_cases + judge + pytest）
- [ ] 设计文档 + 演示视频

---

相关文档：
- 板端快照契约：[../docs/board-snapshot-contract.md](../docs/board-snapshot-contract.md)
- 上板部署说明：[../docs/DEPLOY.md](../docs/DEPLOY.md)
- 板端 C++ 改动交接：[../yolo/agent-butler_K_copy_20260821/examples/agent-butler/docs/BOARD_CPP_CHANGES.md](../yolo/agent-butler_K_copy_20260821/examples/agent-butler/docs/BOARD_CPP_CHANGES.md)
