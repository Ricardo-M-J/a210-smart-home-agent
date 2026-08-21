# A210 边缘视觉 Agent 项目 —— 接手文档

> 用途：这份文档供**新的 AI 会话**接手继续工作。读完本文档，接手的 AI 应能完整理解项目背景、已确定的决策、当前进度和下一步动作，无需再向用户复述背景。
> 生成日期：2026-08-20

---

## 0. 一句话项目定位

在 A210 开发板（RISC-V、12TOPS NPU、Linux Debian）上，做一个**智能家居边缘视觉 Agent**：摄像头持续检测家居状态（有没有人、灯开没开、宠物、电源等），Agent 接收「用户提问」和「异常事件」两种触发，调用三个 Tool 拿数据、调云端大模型（通义千问）推理，回答组合式家居问题（如"家里现在安全吗""是不是忘关灯了"）并智能告警。

选题核心逻辑：智能家居的判断是**"有人 × 开灯 × 时间 × 房间 × 习惯"的组合式开放判断**，if-else 写不完，只有 Agent 的语言理解能覆盖——这是 Agent 超越 if-else 的唯一理由，也是方案创新分的来源。

---

## 1. 赛题核心信息（来自官网，已完整抓取）

竞赛名：**A210 边缘视觉 Agent 应用**（CIE 玄铁 RISC-V 应用创新赛道）
官网：https://rv.cie.org.cn/direction?id=3

关键时间：报名至 2026-11-08；总决算 2026-12-21 至 2027-01-16。**用户团队只有约 1 周开发时间。**

### 基本要求（必须全满足）
- 设计 Agent 系统，**至少包含图像采集、模型推理、结果决策三个 Tool**
- Agent 能根据视觉输入**自主判断**并触发相应动作
- 支持**自然语言交互问答**（可调用云端大模型 API）
- 开发板 A210、Linux Debian、C/C++ 或 Python

### 评分表（满分 100，这是所有决策的依据）

| 维度 | 分值 | 评审项与分值 |
|------|:---:|------|
| Agent 功能实现 | **35** | Tool完整性 15 + Agent调度 10 + 自然语言交互 10 |
| 系统可用性 | **25** | 部署运行 15 + 稳定性 10 |
| 扩展功能 | **20** | 实时视频渲染 7 + 记忆多轮对话 6 + Web服务集成 7 |
| 方案创新 | **10** | 创新亮点 |
| 文档与演示 | **10** | 设计文档 5 + 演示视频 5 |

**关键结论**：26 分（调度10+交互10+记忆6）只有"Agent 智能"能拿到；部署运行+稳定性 25 分是"底线分"——演示当场崩掉，会重创这 25 分，并连带拖低功能/演示两项的实际展示分（评审难以完整看到功能）。**宁可功能少而稳，绝不功能多而崩。**（注：评分表是加法不是乘法，"全归零"是激励性说法，不是评分规则。）

---

## 2. 已经确定的技术决策（接手的 AI 不要推翻，直接沿用）

### 架构：三层 + 事件驱动双触发源

```
感知层（持续流式运行，队友负责）
  iGibson虚拟环境/摄像头 → YOLO检测(视觉模型) → 家居状态快照(文件IPC)
                                              ├─→ HDMI本地渲染（可选）
                                              └─→ 规则引擎发现异常 → 推事件

Agent层（事件驱动，用户负责，本项目的核心）
  触发源①用户提问 / ②异常事件
    → Agent循环（自写，function calling）
    → 调三个Tool → 调云端通义千问 → 回答/告警
    → 写记忆模块

交互层（用户负责）
  Web服务（Gradio或Flask，板子实测后定）+ 告警可视化
```

**关键理解**：感知层是"眼睛"（一直跑），Agent 是"大脑"（被触发才想）。两者通过**文件 IPC** 解耦（感知进程原子写 JSON，Agent 轮询读），不是同进程的 queue.Queue——因为 BEV/YOLO 推理大概率跑在队友的独立进程里。

### 技术栈（全部轻量，已定）

| 模块 | 决策 | 理由 |
|------|------|------|
| Agent 循环 | **自写**（function calling） | 3个tool的简单Agent，LangChain过重；自写答辩时更能讲清原理 |
| 云端 LLM | 通义千问 **requests 直调 OpenAI 兼容端点**，不用 dashscope SDK | SDK 依赖 cryptography（riscv64 无预编译包）；requests 零编译 |
| 三个 Tool | 自写类 + JSON Schema | function calling 本身就是 Tool 机制 |
| 记忆-对话 | messages 列表 + 截断 | API 原生用法 |
| 记忆-历史 | SQLite（标准库 sqlite3） | 零依赖 |
| 事件总线 | 文件轮询 / 条件变量，**不是 queue.Queue** | 跨进程要用文件 IPC |
| UI | **Gradio 优先，Flask+简单HTML 兜底** | D1 上板实测决定（见风险） |

### 开工前置条件（接手 AI 动手前必须先向用户确认，缺一项就无法产出可运行代码）

1. **通义千问模型名**：尚未确定（qwen-plus / qwen-turbo / qwen-max / qwen3 系 等）。模型不同，function calling 稳定性、回答质量、成本差异很大。**待用户确认后填入。**
2. **API Key 鉴权**：约定环境变量 `DASHSCOPE_API_KEY`，代码里**绝不硬编码**（赛题明文规则，硬编码会直接违规）。
3. **代码落点与运行环境**：代码写到哪个目录/仓库、在 x86 开发机跑闭环还是直接上板、Python 版本、依赖是否用 requirements.txt 锁定。**待用户确认。**
4. **接口契约冻结状态**：见第 5 节，当前仍是"草案"，尚未有正式 schema 文件 + 队友签字。**接手 AI 阶段一的第一步就是把它落成正式文件。**

### 明确不做的（战略放弃）
流式输出打磨、UI 美化、多用户并发、复杂 RAG 检索、额外新 Tool、LangChain/AutoGen/Qwen-Agent 框架、手环健康监测（超纲，偏离视觉主题）。

---

## 3. 选题演进（重要背景，避免接手 AI 误解）

1. 最初方案：BEV 交通场景（车辆/行人检测 + 问答），用户负责 Agent。
2. **已放弃**：交通场景"行人→刹车"是 if-else 能做的，凸显不出 Agent 价值。
3. **当前方向**：老师建议的**智能家居**——检测"有没有人、开没开灯"等状态，利用 AI 的灵活性做组合判断。
4. 队友画的方案图（多场景：独居安全/宠物友好/健康监测）**已评审，结论是超载**：砍掉手环（跑题）、宠物监测压后（最后有时间再加）、核心做"独居安全"这一条线。
5. iGibson 虚拟环境→虚拟相机→推流 A210 的仿真思路**保留**（省去搭真实场景成本）。

**当前聚焦的核心场景**：独居安全 = 多房间人数检测 + 有人→跌倒/晕倒监测、无人→电源检查 + "家里安全吗"组合问答 + 忘关灯提醒。

---

## 4. 队友工作（只作了解，不阻塞用户）

- 队友 A：视觉模型（原 BEV 已降级，现做 YOLO 检测，推荐 YOLOv8 而非 YOLOv11）
- 队友 B：摄像头采集 / iGibson 仿真环境 / HDMI 渲染（可选）
- 用户本人：Agent 部分（本项目全部重心）

**⚠️ 已发现的技术风险**：
- YOLO 版本待定（YOLOv11 与 YOLOv8 用的是同一套 ultralytics + PyTorch，两者在 A210 上都不能 `pip install` 直接跑）。端侧 NPU 部署的正确姿势是走 ONNX / 厂商 NPU runtime 工具链，**YOLOv8 的导出链路、教程、边缘 NPU 适配案例更成熟、模型更轻，且赛题原文以 YOLOv5/v8 举例**，因此倾向 YOLOv8。**需队友 D1 内查智绘官方文档确认工具链实际支持的版本，以官方为准。**
- Gradio 在 A210 上依赖 orjson/numpy/pandas/pillow 等包，其中 orjson 是 Rust 扩展，**大概率缺 riscv64 预编译 wheel、需源码编译（推断，未实测）**；numpy/pandas/pillow 可能有源码回退或走系统包。整体有变"编译地狱"的风险。**D1 必须上板 2 小时实测**，装不通立即切 Flask+简单 HTML。
- dashscope SDK 依赖 cryptography（Rust 扩展，riscv64 无现成 wheel），**改用 requests 直调** OpenAI 兼容端点 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`（支持 tools 参数）。

---

## 5. 需要和队友对齐的接口：家居状态快照（⚠️ 当前是草案，未冻结）

用户已确定用一份"家居状态快照"JSON 作为 Agent 与感知层的契约方向，但**下面只是示例草案，尚未落成正式 schema 文件、也没有队友签字**。接手 AI 阶段一的第一步就是把它定稿：写出 schema 文件、确认字段枚举全表、文件路径、原子写/轮询读协议，然后让队友签字冻结。队友换模型、换场景、砍功能，都只改变"谁往这个结构里填数据"，Agent 代码不动。

```json
{
  "timestamp": "2026-08-20 23:10:00",
  "rooms": [
    {
      "room": "客厅",
      "objects": [
        {"category": "person", "count": 0, "pose": null},
        {"category": "light", "state": "on"},
        {"category": "pet", "count": 0}
      ]
    },
    {
      "room": "卧室",
      "objects": [
        {"category": "person", "count": 1, "pose": "lying"},
        {"category": "light", "state": "off"}
      ]
    }
  ]
}
```

检测对象用 `category` 枚举扩展（person / light / pet / appliance 等），不加新字段就能扩展能力。

---

## 6. 三个 Tool 的设计

| Tool | 名称 | 功能 | 备注 |
|------|------|------|------|
| 图像采集 Tool | `capture_image` | 获取当前家居画面（帧/图像） | 支持 latest（读缓存）/ fresh（主动拍） |
| 模型推理 Tool | `run_detection` | 触发一次端侧视觉检测，返回结构化检测结果 | ⚠️ 见下方"评分隐患"，必须真正触发推理 |
| 结果决策 Tool | `make_decision` | 判断 + 告警 + 记录日志 | 智能决策走 LLM，简单确定性动作走规则 |

**⚠️ 评分隐患（必须处理，否则被评审问倒）**：赛题要求"模型推理 Tool = 在 A210 端侧部署轻量视觉模型完成图像识别分析"。当前架构里，YOLO 推理由队友的独立进程持续跑、Agent 只读 JSON 快照——这样 Agent 的"模型推理 Tool"会退化成"读文件"，评审可能质疑"你的端侧推理 Tool 在哪"。

**处理方式（二选一，接手 AI 与队友确认后定）**：
- 方案 A（推荐）：Agent 进程内**直接调用**队友提供的 YOLO 推理函数/子进程（队友把推理封装成可被 Agent 调用的接口）。`run_detection` Tool 真正触发一次端侧推理，返回原始检测结果；"读快照"只是性能优化路径（若快照足够新则直接用）。
- 方案 B：若队友坚持推理完全独立、无法被 Agent 调用，则把"读快照"明确包装并命名为推理 Tool，文档/答辩时讲清"端侧推理持续运行、Agent 通过共享契约消费其结果"，并准备好在答辩时解释架构取舍。

无论选哪个，`get_home_state`（读快照）与 `run_detection`（触发推理）的职责边界必须清晰，不能在代码里混成一个函数。

---

## 7. 当前进度与待办

**已完成**：方案调研、技术选型、架构设计、风险评审、接口契约草案（对话中确定，尚未落成文档）。

**待办（接手 AI 应推动的）**：

### 阶段一：接口契约 + Mock 数据（不依赖任何队友）
1. 把"家居状态快照"JSON 写成正式契约文档
2. 生成 Mock 数据模块（几组典型场景：有人/无人 × 灯亮/灯灭 × 时间）
3. 生成三个 Tool 的类 + function calling 循环（requests 直调通义千问）
4. 命令行问答跑通第一个闭环

### 阶段二：评测 harness（goal 模式自迭代的关键）
5. 写 `eval_cases.json`（测试问题 + 预期要点，见下方）
6. 写 `judge` 打分函数 + `run_eval.py`
7. 让 AI 用"写→检验→看失分点→调整→再检验"循环迭代 Prompt 直到达标

### 阶段三：事件触发 + 记忆
8. 异常事件（如"无人但灯亮超时"）规则引擎 + 去重冷却
9. 事件→Agent 决策→告警链路
10. SQLite 历史记录 + messages 多轮对话

### 阶段四：UI + 部署
11. D1 上板实测 Gradio 可否安装，定 UI 路线
12. Web 界面（聊天框 + 画面 + 告警列表）
13. 上板部署 + systemd 自启 + 断网降级 + 稳定性连测
14. 文档 + 演示视频

---

## 8. goal 模式自检验工作流（接手 AI 直接照做）

### 核心原则（务必记住）

1. **职责分离**：规格（测试集、预期、验收标准、judge 规则）由**用户/人**在迭代前定死冻结；AI 的自由度只在**实现侧**（代码、Prompt）。**禁止 AI 为了通过而改 eval_cases.json 或改 judge 阈值。**
2. **目标用"硬断言"，不用"关键词打分"当目标**：关键词覆盖只能当"回归护栏"（确认没退化），不能当质量验收——否则 AI 会去刷关键词而不是把回答写对。
3. **judge 用确定性规则为主**：对本任务（验证是否覆盖预期要点），规则 judge 比 LLM judge 更客观、可复现、零成本。若要 LLM judge，必须换更强/不同的模型 + temperature=0 + rubric + 参考答案，且只用来标记异常、不用作通过标准。
4. **设硬预算**：goal 模式最多 N 轮（建议 ≤5）或 X 分钟，到点冻结当前最好版本；**分数达标立即停，不追 100**。每轮留 diff 日志，最终改动必须用户人工 review 才合并。

### 验收标准（全部可自动执行，缺一条对应的测试就是假标准）

```
1. pytest 全绿（见下方测试清单）
2. 给定 snapshot + 问题，Agent 能正确路由到正确的 Tool（tool_calls 断言）
3. 模拟断网（mock 让 API 抛异常），Agent 降级到本地规则回答，且不抛异常
4. 回答格式可解析（JSON 或纯文本，写清解析规则）
5. 关键词覆盖作为"不退化"下限：每例至少命中预期同义词集合的 60%
```

### 测试清单（pytest，这是真正的验收，不是关键词打分）

```python
# test_tools.py          —— Tool 类单元测试
# test_schema.py         —— 快照 JSON 的 schema 校验（字段枚举、必填项）
# test_routing.py        —— 给定 snapshot+question，断言调用了正确的 Tool
# test_fallback.py       —— mock API 抛异常，断言返回本地规则答案且不抛错
# test_format.py         —— 断言输出可被解析（JSON/文本）
# test_keywords.py       —— 关键词同义词集合的回归检查（下限，不作目标）
```

### eval_cases.json 结构（示例，关键词用"同义词数组"，不再是 OR 字符串）

```json
[
  {
    "scenario": "家里没人，客厅灯亮，晚上11点",
    "snapshot": {"rooms":[{"room":"客厅","objects":[{"category":"person","count":0},{"category":"light","state":"on"}]}]},
    "question": "我家里现在安全吗？",
    "expected_synonyms": [["没人","无人","没有人"], ["灯","灯亮","亮着"], ["提醒","忘关","忘记关"]],
    "forbidden_keywords": []
  },
  {
    "scenario": "卧室有人躺着",
    "snapshot": {"rooms":[{"room":"卧室","objects":[{"category":"person","count":1,"pose":"lying"},{"category":"light","state":"off"}]}]},
    "question": "老人现在状态怎么样？",
    "expected_synonyms": [["卧室"], ["有人","老人"], ["躺着","休息","躺"]],
    "forbidden_keywords": []
  }
]
```

> ⚠️ 规则：每个 `expected_synonyms` 是一组同义词，**命中组内任意一个即算覆盖该要点**（旧版的 `"提醒或忘关"` 是单个字符串，几乎永远判0，已废弃）。`forbidden_keywords` 用于标记"不该出现的内容"，出现即扣分/判负。

### judge 打分函数（规则版，供 test_keywords.py 使用）

```python
def judge(expected_synonyms, forbidden_keywords, actual_answer):
    text = actual_answer  # 可先做归一化：小写、去空格
    hit = sum(1 for group in expected_synonyms if any(s in text for s in group))
    cover = hit / len(expected_synonyms)
    forbidden_hit = [k for k in forbidden_keywords if k in text]
    return {"coverage": cover, "forbidden_hit": forbidden_hit,
            "missing": [g[0] for g in expected_synonyms if not any(s in text for s in g)]}
```

### 迭代闭环（带硬预算）

```
AI 写代码/改Prompt → pytest 全量跑 → 输出失败项和 diff
  → AI 只针对失败项调实现 → 再跑 → 直到全绿或到达 N 轮上限
  → 达标即停，用户人工 review 后合并
```

> 补充：开发阶段把 LLM 调用做成 record/replay 或 mock 数据，让 pytest 离线可复现、不烧 API 钱、不依赖网络。

---

## 9. 关键保命原则（接手 AI 要记住）

1. **Mock/真实双通道保留到答辩当天**：队友延误或现场翻车，一键切回 Mock，演示照常。
2. **LLM 失败降级本地规则告警**：会场断网是常态，对应稳定性 10 分的底线。
3. **接口契约 D1 冻结**：家居状态快照 JSON 定死，让队友签字。
4. **宁稳勿全**：35 分 Agent + 25 分稳定性是底线，功能少而稳 > 功能多而崩。
5. **场景别贪多**：核心只做"独居安全"一线，砍手环，宠物监测最后再加。

---

## 10. 给接手 AI 的第一条指令模板

> 请先阅读 /workspace/a210-handoff.md，然后从"阶段一：接口契约 + Mock 数据"开始执行。第一步：把家居状态快照 JSON 写成正式契约文档，并生成 Mock 数据模块（至少覆盖：有人+灯亮、有人+灯灭、无人+灯亮、无人+灯灭 × 白天/夜间 的典型组合）。

---

## 附：相关文件

- 赛题官网完整内容：`/workspace/a210-competition-details.md`
- 本接手文档：`/workspace/a210-handoff.md`