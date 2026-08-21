# 家居状态快照 —— 接口契约（v1.0 冻结版）

> 本文档是 Agent 层与感知层（摄像头采集 + YOLO 端侧检测进程，由队友负责）之间的**唯一数据契约**。
> 感知层负责「往这个结构里填数据」，Agent 层负责「消费这个结构」。
> 队友换模型、换场景、砍功能，都只改变填数据的一方，Agent 代码不动。

---

## 1. 交换方式：文件 IPC

| 项 | 约定 |
|----|------|
| 文件路径 | 由环境变量 `HOME_STATE_FILE` 指定，默认 `/tmp/home_state.json`（上板）或 `./mock/home_state.json`（本地 Mock） |
| 写入方 | 感知进程（队友） |
| 读取方 | Agent 进程 |
| 写入协议 | **原子写**：先写临时文件 `home_state.json.tmp`，再 `os.replace()` 覆盖正式文件，避免 Agent 读到半截 JSON |
| 读取协议 | Agent **轮询读**（默认 0.5s 一次），读到即用；读取失败或文件不存在时按「无数据」降级处理 |

> 设计原因：感知层的 BEV/YOLO 推理大概率跑在队友的独立进程里，跨进程不能用同进程的 `queue.Queue`，必须用文件 IPC 解耦。

---

## 2. 顶层结构

```json
{
  "timestamp": "2026-08-20 23:10:00",
  "rooms": [ { "room": "...", "objects": [ ... ] } ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `timestamp` | string | 是 | 快照生成时间，`YYYY-MM-DD HH:MM:SS`（24 小时制，用于判断白天/夜间） |
| `rooms` | array | 是 | 房间列表，至少 1 个；每个元素见 §3 |

---

## 3. room 结构

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `room` | string | 是 | 房间名 |
| `objects` | array | 是 | 该房间检测到的对象列表，每个元素见 §4 |

**房间名枚举（当前冻结）**：`客厅`、`卧室`、`厨房`、`卫生间`、`玄关`、`阳台`。
（队友如需扩展，在本文档增补枚举并同步队友，不影响 Agent 代码结构。）

---

## 4. object 结构：按 category 分派

每个对象必须有 `category`，然后按类别带不同字段。**扩展能力 = 扩展 category 枚举 + 对应字段，不改现有结构。**

| category | 含义 | 字段 | 类型 | 说明 |
|----------|------|------|------|------|
| `person` | 人 | `count` | int | 该房间人数（≥0） |
|  |  | `pose` | string\|null | 姿态枚举：`standing`/`sitting`/`lying`/`null`（无人时为 null） |
| `light` | 灯 | `state` | string | `on` / `off` |
| `pet` | 宠物 | `count` | int | 宠物数量（≥0） |
| `appliance` | 家电 | `name` | string | 家电名（如 `空调`/`插座`） |
|  |  | `state` | string | `on` / `off` / `standby` |

**字段枚举全表（评审/队友对齐用）**：

- `category`：`person` | `light` | `pet` | `appliance`
- `pose`：`standing` | `sitting` | `lying` | `null`
- `light.state`：`on` | `off`
- `appliance.state`：`on` | `off` | `standby`

---

## 5. 示例（独居安全场景）

```json
{
  "timestamp": "2026-08-20 23:10:00",
  "rooms": [
    {
      "room": "客厅",
      "objects": [
        { "category": "person", "count": 0, "pose": null },
        { "category": "light", "state": "on" }
      ]
    },
    {
      "room": "卧室",
      "objects": [
        { "category": "person", "count": 1, "pose": "lying" },
        { "category": "light", "state": "off" }
      ]
    }
  ]
}
```

---

## 6. 校验

JSON Schema 见同目录 `home_state_schema.json`。可用以下命令校验任意快照：

```bash
python -c "import jsonschema,json; from pathlib import Path; jsonschema.validate(json.load(open('mock/home_state.json',encoding='utf-8')), json.load(open('schema/home_state_schema.json',encoding='utf-8')))"
```

（jsonschema 仅用于开发期校验，运行时代码不依赖它，保持零依赖。）
