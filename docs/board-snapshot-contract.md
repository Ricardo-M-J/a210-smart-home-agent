# 板端 C++ 快照输出契约（Agent ↔ 板端对接）

> 目标：让板端 C++ 只负责「检测到了什么」，把全屋状态原子写成一个快照文件；
> 「什么算异常、要不要告警」全部移到云端 Agent（Python）侧。
> 这样两端职责清晰：C++ 做感知，Python 做决策。

---

## 一、核心改动一句话

板端 C++ 维护一张「全屋状态表」（`room -> 最新检测结果`），每处理一帧就更新对应房间，然后把**全屋快照**原子写到 `/tmp/home_state.json`。

原有的事件输出（`evaluate_rules`）**保留但默认关闭**，通过 `--emit-events` 参数控制，需要时仍可切回。

---

## 二、快照格式（全屋聚合，两边对齐的唯一契约）

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

### 字段说明

**顶层**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp_ms` | int64 | 最近一次检测的毫秒时间戳（用于判断昼夜） |
| `rooms` | object | 全屋五个房间，key 是房间名，value 是该房间最新状态 |

**每个房间（value）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `has_person` | bool | 是否检测到人 |
| `has_cat` | bool | 是否检测到猫 |
| `has_dog` | bool | 是否检测到狗 |
| `fall_like` | bool | 是否像跌倒（仅卧室/卫生间跑 pose，其余房间恒 false） |

### 房间枚举（固定五个，英文）

```
living_room  客厅
bedroom1     卧室1
bedroom2     卧室2
kitchen      厨房
bathroom     卫生间
```

> 房间名到中文的映射放在 Python 侧做，C++ 不改。

### 全屋状态表语义

- C++ 维护 `std::map<std::string, RoomState> home_state`，初始全空（五个房间都默认 false）。
- 每收到一帧、检测完，就用本帧结果覆盖 `home_state[room]`。
- 每次写完都**整表输出**全屋快照——即使某房间这一帧没更新，也输出它上一次的状态。
- 这样云端 Agent 每次读快照，都能看到「全屋当前最新状态」，而不是「某一帧的某一个房间」。

---

## 三、C++ 改动点

### 1. 新增 `--emit-events` 开关（默认关闭）

`Options` 加 `bool emit_events = false;`，`parse_args` 加：

```cpp
if (arg == "--emit-events") {
    opts->emit_events = true;
    continue;   // 布尔开关不带值，不能走 argv[++i]
}
```

### 2. 新增 `--snapshot` 参数（默认 `/tmp/home_state.json`）

`Options` 加 `std::string snapshot_path = "/tmp/home_state.json";`，`parse_args` 加：

```cpp
} else if (arg == "--snapshot") {
    opts->snapshot_path = value;
}
```

### 3. 新增 RoomState 结构 + 全屋状态表

```cpp
struct RoomState {
    bool has_person = false;
    bool has_cat = false;
    bool has_dog = false;
    bool fall_like = false;
};

struct RuleState {
    std::map<std::string, RoomState> home_state;   // 新增
    // ... 原有字段保留
};
```

### 4. 新增 write_snapshot 函数（原子写全屋快照）

见 `main.cc` 中 `write_snapshot`，复用五个固定房间名，把 `home_state` 序列化成上面第二节的 JSON，先写 `.tmp` 再 `rename`。

### 5. process_frame 里维护状态 + 写快照

在 pose 检测之后、`evaluate_rules` 之前：

```cpp
// 更新全屋状态表
RoomState &room_state = state->home_state[header.room];
room_state.has_person = has_detection_label(det_results, "person");
room_state.has_cat = has_detection_label(det_results, "cat");
room_state.has_dog = has_detection_label(det_results, "dog");
room_state.fall_like = pose_ptr ? any_fall_like_person(*pose_ptr) : false;

// 输出全屋快照
int64_t ts_ms = header.timestamp_ms > 0 ? header.timestamp_ms : now_ms();
write_snapshot(opts, *state, ts_ms);

// 原有硬编码规则默认关闭
if (opts.emit_events) {
    evaluate_rules(opts, state, header, det_results, pose_ptr);
}
```

---

## 四、Python 侧对接

板端改完后，Python 侧（已完成）：

1. `.env`：`HOME_STATE_FILE=/tmp/home_state.json`、`BACKEND=real`
2. `RealBackend.infer()` 读全屋快照，返回 `{timestamp_ms, rooms}`
3. 规则是 LLM 生成的 `when` 条件字典，事件引擎通用匹配 + 边沿触发

---

## 五、验收标准

板端启动（默认不 emit events）：

```bash
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000
```

PC 发几帧不同房间的图，然后：

```bash
cat /tmp/home_state.json
```

应看到合法的全屋快照 JSON，且每发一帧、对应房间状态更新、整表重写。

---

## 六、未改动部分

- `is_pose_room` 的"卧室/卫生间有人才跑 pose"——**保留**（省算力，非规则判断）
- `detections_json`、`has_detection_label`、`any_fall_like_person`——**复用**，不改
- TCP 收图协议、`action_hook.sh`——**不改**
- `evaluate_rules` 三条硬编码规则——**保留但默认关闭**（`--emit-events` 控制）
