# 给你的调试文档：agent-butler C++ 改动说明

> 我（Agent 侧）改动了 `examples/agent-butler/cpp/main.cc`，让板端把「全屋检测状态」写成一个快照文件，供云端 Agent 读取。
> 本文档说明我改了哪里、为什么改、你怎么编译验证、出问题怎么排查。

---

## 一、我改了什么（一句话）

原来：板端每检测一帧，只做硬编码规则判断，然后发事件。
现在：板端**维护一张全屋状态表**，每帧更新对应房间，然后把**全屋快照**原子写到 `/tmp/home_state.json`。

原来的硬编码规则（`evaluate_rules`）**没有删**，只是默认关闭了，加个 `--emit-events` 参数还能打开。

---

## 二、具体改动清单（都在 main.cc）

| # | 位置 | 改动 |
|---|------|------|
| 1 | `Options` 结构体 | 加了 `snapshot_path`（默认 `/tmp/home_state.json`）和 `emit_events`（默认 false） |
| 2 | 新增 `RoomState` 结构体 | 4 个 bool：`has_person / has_cat / has_dog / fall_like` |
| 3 | `RuleState` 结构体 | 加了 `std::map<std::string, RoomState> home_state` |
| 4 | `parse_args` | 加了 `--snapshot`（带值）和 `--emit-events`（布尔开关，不带值） |
| 5 | 新增 `write_snapshot()` 函数 | 把全屋状态表序列化成 JSON，先写 `.tmp` 再 `rename` 原子替换 |
| 6 | `process_frame` | 检测完更新 `home_state[room]`，然后调 `write_snapshot`；`evaluate_rules` 改成受 `--emit-events` 控制 |

**我没动的东西**（这些保持原样）：

- `is_pose_room`（卧室/卫生间才跑 pose 的省算力逻辑）
- `inference_det_yolo11_model` / `inference_pose_yolo11_model`（推理本身）
- `detections_json` / `has_detection_label` / `any_fall_like_person`（复用它们）
- TCP 收图协议、`action_hook.sh`

---

## 三、快照长什么样（我要读的格式）

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

关键点：
- `rooms` 是**全屋五个房间**，永远整表输出，不是只有最新一帧那个房间
- 房间名用英文（`living_room` 等），中文映射我 Agent 侧做
- 某个房间这一帧没更新，就输出它上一次的状态

---

## 四、怎么编译

编译命令**不变**（还是你原来的）：

```bash
cd /home/public/ai/tools/torq-model-zoo
./build-linux.sh -t a210 -d agent-butler
```

产物在 `install/a210_linux/torq_agent-butler_demo/`。

---

## 五、怎么验证改对了

启动板端程序（注意：**不加** `--emit-events`，用默认的"只写快照"模式）：

```bash
cd torq_agent-butler_demo
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000
```

PC 发几张不同房间的图（比如先发厨房，再发卧室）：

```bash
python3 send_frame.py --host $BOARD_IP --room kitchen --image assets/kitchen/danger.jpg --repeat 3
python3 send_frame.py --host $BOARD_IP --room bedroom1 --image assets/bedroom1/person.jpg --repeat 3
```

然后看快照：

```bash
cat /tmp/home_state.json
```

**预期结果**：

1. 是合法的 JSON（能 `python3 -m json.tool` 正常解析）
2. 有 `timestamp_ms` 和 `rooms` 两个字段
3. `rooms` 里有 5 个房间
4. 发过厨房的图后，`kitchen` 的状态被更新了（比如 `has_cat: true`）；卧室的图发了后 `bedroom1` 也更新了
5. 再发一次其他房间，`kitchen` 的状态**保持不变**（因为整表输出，不是清空）

---

## 六、出问题怎么排查

| 现象 | 可能原因 | 排查 |
|------|---------|------|
| 编译报错（找不到 RoomState / write_snapshot） | 头文件顺序或作用域问题 | 把报错信息发我，多半是漏了声明 |
| 编译报错 `strerror` 未定义 | 少了 `<cstring>` | 在 `main.cc` 顶部加 `#include <cstring>` |
| `/tmp/home_state.json` 不存在 | 没收到帧，或写文件失败 | 看程序 stdout 有没有 `write_snapshot open failed` |
| JSON 不完整/解析失败 | 写入和读取竞争 | 我用了 `.tmp` + `rename` 原子写，正常不会；若还出现，告诉我 |
| 快照只有最新房间、其他房间丢了 | `home_state` 没跨帧保留 | 确认 `RuleState` 是全局一份、传的是指针 `state` |

---

## 七、需要你确认/回我的一件事

帮我确认快照里的字段语义对不对：

- `fall_like`：是不是只有卧室/卫生间有人时才可能为 true，其他房间恒 false？
- 你那个 `any_fall_like_person` 判断"像跌倒"的逻辑，是不是一个房间只要有一个人像跌倒就返回 true？（我在 `process_frame` 里用它给当前房间的 `fall_like` 赋值）

如果语义对，我们 Agent 侧就能直接用它；如果不对，告诉我正确的取法，我改。
