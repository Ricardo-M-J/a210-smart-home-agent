# A210/VirtualHome 家居状态快照契约

Agent 侧统一消费一张“全屋当前状态表”。无论来源是真实 A210+YOLO、mock，还是 VirtualHome，最终都应映射为同一结构。

## 房间枚举

当前项目只有四个房间：

```text
living_room  客厅
bedroom      卧室
kitchen      厨房
bathroom     卫生间
```

兼容说明：旧的 `bedroom1`、`bedroom2` 只允许作为输入别名，进入 Agent 后统一归一化为 `bedroom`。

## JSON 格式

```json
{
  "timestamp_ms": 123456789,
  "rooms": {
    "living_room": {
      "has_person": false,
      "has_cat": false,
      "has_dog": false,
      "fall_like": false,
      "hazard_detected": false,
      "hazard_type": "",
      "health_event": false,
      "unknown_person": false
    },
    "bedroom": {
      "has_person": true,
      "has_cat": false,
      "has_dog": false,
      "fall_like": true,
      "hazard_detected": false,
      "hazard_type": "",
      "health_event": false,
      "unknown_person": false
    },
    "kitchen": {
      "has_person": false,
      "has_cat": true,
      "has_dog": false,
      "fall_like": false,
      "hazard_detected": false,
      "hazard_type": "",
      "health_event": false,
      "unknown_person": false
    },
    "bathroom": {
      "has_person": false,
      "has_cat": false,
      "has_dog": false,
      "fall_like": false,
      "hazard_detected": false,
      "hazard_type": "",
      "health_event": false,
      "unknown_person": false
    }
  }
}
```

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `timestamp_ms` | int | 快照生成时间，毫秒时间戳 |
| `rooms` | object | 四房间状态表 |
| `has_person` | bool | 是否检测到人 |
| `has_cat` | bool | 是否检测到猫 |
| `has_dog` | bool | 是否检测到狗 |
| `fall_like` | bool | 是否疑似跌倒/躺倒 |
| `hazard_detected` | bool | 是否检测到烟雾、火灾等危险 |
| `hazard_type` | string | 危险类型，例如 `fire_smoke` |
| `health_event` | bool | 是否有健康/可穿戴设备事件 |
| `unknown_person` | bool | 是否检测到陌生人 |

## VirtualHome 映射

VirtualHome 的 `external_result_sample.jsonl` 会映射到上述字段：

- `person_count > 0` -> `has_person=true`
- `pet_count > 0` + `pet_type=cat/dog` -> `has_cat`/`has_dog`
- `fall_detected` 或 `event/posture` 中出现 fall/lie -> `fall_like=true`
- `hazard_detected=true` 或存在 `hazard_type` -> `hazard_detected=true`
- `schema=external.health_event.v1` -> `health_event=true`
- `unknown_person_count > 0` -> `unknown_person=true`

`room=all_rooms` 的消息如果无法定位具体房间，会在 `virtualhome.external_result` 元数据中保留原始结果，并在 `rooms.living_room` 放置代表性信号，避免破坏旧规则引擎的房间级匹配。
