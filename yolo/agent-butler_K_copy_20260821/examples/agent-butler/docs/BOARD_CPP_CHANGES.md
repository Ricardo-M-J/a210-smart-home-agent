# agent-butler C++ 改动交接说明

> 这份文档说明我在 `examples/agent-butler/cpp/main.cc` 上改了什么、为什么改、以及哪些地方需要你自己核对。
> 目标是让你（或你的 AI 助手）能独立理解和继续修改，而不是照着我给的结论盲改。

---

## 一、改动的设计意图

原来板端的链路是：**检测 → 硬编码规则判断 → 发事件**，规则（宠物危险/跌倒/健康异常）写死在 C++ 里。

我们的架构调整为：

```
板端 C++：检测 → 写「全屋状态快照」文件    ← 只做感知，不做判断
云端 Agent（Python）：读快照 → 规则判断 → 问答/告警   ← 规则由用户下指令、LLM 动态生成
```

原因：赛题要求 Agent 有「自主决策」能力。如果"什么算异常"写死在 C++ 里，Agent 就退化成了对话工具。所以把规则判断从 C++ 移到 Python 侧，让用户能动态布置监控任务。

**核心改动只有一件事**：板端不再只发"已判断好的事件"，而是把**每一帧检测到的原始状态**，聚合成全屋快照写到一个文件。

---

## 二、具体改了什么（都在 main.cc）

| # | 位置 | 改动 |
|---|------|------|
| 1 | `Options` 结构体 | 加 `snapshot_path`（默认 `/tmp/home_state.json`）、`emit_events`（默认 false） |
| 2 | 新增 `RoomState` 结构体 | 4 个 bool：`has_person / has_cat / has_dog / fall_like` |
| 3 | `RuleState` 结构体 | 加 `std::map<std::string, RoomState> home_state`（全屋状态表） |
| 4 | `parse_args` | 加 `--snapshot`（带值）、`--emit-events`（布尔开关，不带值，用 `continue` 跳过取值） |
| 5 | 新增 `write_snapshot()` | 把 `home_state` 序列化成 JSON，`.tmp` + `rename` 原子写 |
| 6 | `process_frame` | 检测完更新 `home_state[room]` 并写快照；`evaluate_rules` 改成受 `--emit-events` 控制 |

**我没有动的**（你原来的逻辑都保留）：

- `is_pose_room`（卧室/卫生间才跑 pose 的省算力逻辑）
- `inference_det_yolo11_model` / `inference_pose_yolo11_model`（推理本身）
- `detections_json` / `has_detection_label` / `any_fall_like_person`（我复用了它们）
- TCP 收图协议、`action_hook.sh`

---

## 三、快照格式（Agent 和板端对齐的契约）

```json
{
  "timestamp_ms": 123456789,
  "rooms": {
    "living_room": {"has_person": false, "has_cat": false, "has_dog": false, "fall_like": false},
    "bedroom1":    {"has_person": true,  "has_cat": false, "has_dog": false, "fall_like": true},
    "bedroom2":    {"has_person": false, "has_cat": false, "has_dog": false, "fall_like": false},
    "kitchen":     {"has_person": false, "has_cat": true,  "has_dog": false, "fall_like": false},
    "bathroom":    {"has_person": false, "has_cat": false, "has_dog": false, "fall_like": false}
  }
}
```

语义：

- `rooms` 是**全屋五个房间，永远整表输出**，不是只有最新一帧那个房间
- 某个房间这一帧没更新，就输出它**上一次**的状态（靠 `home_state` map 跨帧保留）
- 房间名用英文，中文映射在 Agent 侧做

---

## 四、需要你自己核对的点（我不确定的，别照抄）

1. **`fall_like` 的语义**：我在 `process_frame` 里用 `any_fall_like_person(*pose_results)` 给当前房间赋值。请确认这个函数是不是"一个房间只要有人像跌倒就返回 true"——如果不是我要的语义，改这里。

2. **`fall_like` 在非 pose 房间**：我的实现是 `pose_ptr ? any_fall_like_person(...) : false`，即非卧室/卫生间恒 false。这是否符合你的预期？如果跌倒检测不只在 pose 房间，需要改。

3. **全屋状态表在收图断流时**：如果 PC 只发了一个房间的图就停，其他房间会一直保留"初始 false"。演示时是否需要在启动时初始化所有房间？目前是 `home_state` 空 map，输出时用默认值补全。

4. **`--emit-events` 开关**：我把原来的 `evaluate_rules` 默认关了。如果你还想保留"板端独立发事件"的能力，启动时加 `--emit-events` 即可，两边并行不冲突。

---

## 五、编译验证

编译命令不变：

```bash
cd /home/public/ai/tools/torq-model-zoo
./build-linux.sh -t a210 -d agent-butler
```

产物在 `install/a210_linux/torq_agent-butler_demo/`。

启动（默认只写快照）：

```bash
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000
```

发帧后验证：

```bash
cat /tmp/home_state.json
```

预期：合法 JSON，含 `timestamp_ms` + `rooms`（5 个房间），发过图的房间状态被更新、其他房间保留上次状态。

---

## 六、可能的问题点（供排查，不预设答案）

- 若编译报错，先看是不是 `strerror` 需要 `<cstring>`、或 `RoomState` 声明位置（结构体定义在 `RuleState` 之前，依赖关系要满足）
- 若快照文件不存在：程序没收到帧，或 `write_snapshot` 打开文件失败（stdout 会有 `write_snapshot open failed`）
- 若 JSON 不完整：检查 `rename` 原子写是否正常，或是否有并发写（本程序单线程收帧，应该不会）

---

## 七、Agent 侧怎么配合

Agent 侧（Python）已经按上面第三节的格式读快照。所以**只要快照格式对，两边就能通**。Agent 的规则是用户下指令、LLM 动态生成的条件，事件引擎通用匹配 + 边沿触发，不依赖 C++ 里的任何硬编码规则。
