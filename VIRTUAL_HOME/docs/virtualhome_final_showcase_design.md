# VirtualHome 结项展示设计

本文只设计 VirtualHome 虚拟环境侧的交付内容。YOLO、A210 边缘推理、云端大语言模型、真实智能手表/手机蓝牙通信不写入本仓库，只保留接口和可测试的替代数据。

## 1. 总体目标

结项现场展示一条完整闭环：

```text
VirtualHome 家居环境
  -> 720p / 10fps / JPG 图像流
  -> 外部 YOLO/A210 返回检测结果
  -> 外部 agent 返回动作决策
  -> VirtualHome 展示反馈效果和手机/手表占位通知
```

当前主路线使用官方预编译 `VirtualHome.exe` 加 Python 展示面板。Unity 源码项目保留为后续可编辑场景路线，但不是现场稳定展示的必要条件。

VirtualHome 侧只负责：

```text
1. 展示普通户型家居环境和房间摄像头画面。
2. 输出 1280x720、10fps、JPG 图像流。
3. 提供人员计数、普通模式宠物留守、火灾烟雾、健康助手、离家模式陌生人告警等示例事件。
4. 接收外部 agent 反馈动作：关灯、告警、环境调节、手机/手表通知占位。
5. 生成可复查的 MP4、JPG、JSONL 日志。
```

明确不做：

```text
1. 不在 VirtualHome 中训练或运行 YOLO。
2. 不在 VirtualHome 中实现 A210 推理。
3. 不在 VirtualHome 中实现云端大语言模型。
4. 不真实拨号、不真实发短信、不真实连接蓝牙设备。
```

## 2. 最终展示形式

现场推荐两个窗口并排：

```text
左侧：VirtualHome.exe 可视化模拟器窗口
右侧：Python 高科技风格展示面板
```

展示面板入口：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\showcase_panel.py
```

面板包含：

```text
SCENARIO SCRIPTS       可点击切换 01-07 示例脚本
CAMERA STREAM          当前 720p/10fps 视频或图像
EDGE VISION            YOLO/A210 占位检测结果
PHONE / WATCH          手机或手表占位通知界面
FEEDBACK               VirtualHome 接收的 agent 决策动作
ACTIVE DATA CONTRACT   当前 JSON 数据契约
```

面板右侧增加了模拟手机界面，用于展示 agent 联动后手机收到的告警、宠物留守、焦虑缓解、陌生人进入等消息。该手机界面只展示占位消息，不会触发真实设备。

## 3. 主展示 Demo

### 01 全屋环境俯瞰交互

目标：展示完整家居户型，方便现场说明每个房间的摄像头和智能家居事件位置。

交互：

```text
左键拖动：平移画面
鼠标滚轮：放大/缩小
VIEW CAMERA / Connect：连接已进入 Play 的 VirtualHome.exe
Yaw - / Yaw +：左右旋转 Unity 摄像机
Pitch + / Pitch -：调整俯仰角
Left / Right / Forward / Back / Up / Down：移动 Unity 摄像机
FOV - / FOV +：调整视场角
Reset View / Reset Overview：恢复全屋俯瞰相机位
```

说明：VirtualHome Python API 没有公开“旋转整套房屋模型”的接口；面板 01 不旋转房屋本体，而是通过摄像机移动/旋转刷新画面。若模拟器支持 `update_camera` 就直接更新；若返回 `Unknown action update_camera`，面板自动降级为每次 `add_camera + camera_image` 刷新。未连接模拟器时显示静态俯瞰图；连接后每次点击 VIEW CAMERA 按钮都会刷新一帧 1280x720 图像。

输入文件：

```text
outputs/room_cameras/full_scene_overview_normal.png
outputs/room_cameras/rooms.json
```

### 02 多摄像头布设

目标：展示每个关键房间一路固定摄像头，并说明这些画面会以 720p/10fps/JPG 形式给外部 YOLO/A210。

输出：

```text
outputs/room_cameras/room_camera_contact_sheet_normal.png
outputs/room_cameras/room_cameras.json
outputs/showcase_panel/interface_samples/virtualhome_frame_stream_sample.jsonl
```

### 03 人员计数和无人关灯

目标：人物自然走进卧室，YOLO 替代检测返回 `person_count=1`；人物自然走出后返回 `person_count=0`，agent 决策 `set_light(off)`，视频中只压暗卧室主体区域，避免厨房和旁边卫生间看起来也被关灯。

推荐使用官方 API 自然动画版：

```powershell
.\demo\virtualhome\08_api_bedroom_walk_light_attach.bat
```

运行前先打开：

```text
windows_exec/windows_exec.v2.2.4/VirtualHome.exe
```

选择 Windowed，点击 `Play!`，等场景出现后再运行脚本。

当前脚本设置：

```text
分辨率：1280x720
帧率：10fps
摄像头：固定卧室摄像头
摄像头高度：较低，减少跨墙看到其他房间
FOV：58
time_scale：1.35，目标视频约 200 帧
```

核心反馈动作：

```json
{
  "schema": "virtualhome.feedback.v1",
  "source": "external_agent",
  "scene": "virtualhome_api_bedroom_walk_light",
  "room": "bedroom",
  "action": "set_light",
  "target": "bedroom_ceiling_light",
  "value": "off",
  "reason": "person_count=0_after_person_left"
}
```

输出：

```text
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/bedroom_walk_light_yolo_light_feedback.mp4
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/jpg/bedroom/frame_*.jpg
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/yolo_person_count.jsonl
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/feedback_actions.jsonl
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/bedroom_yolo_light_sync_metadata.json
```

说明：关灯帧由脚本根据真实渲染帧中的人物出现区间自动计算，不再写死房间切换或第二摄像头。

### 04 普通模式宠物留守告警

目标：系统处于普通模式，VirtualHome 自带 `cat` 模型一直在厨房；主人通过官方人物行走帧进入厨房并离开。外部 YOLO/A210 占位结果检测到 `person_count=0` 且 `pet_count=1` 后，agent 占位反馈触发宠物留守告警，并只关闭厨房灯。

运行：

```powershell
.\demo\virtualhome\11_generate_kitchen_pet_alert.bat
.\demo\virtualhome\14_generate_smart_mode_security_demos.bat
```

`11` 运行前需要先打开 `VirtualHome.exe` 并点击 `Play!`，用于生成真实 cat 模型帧；`14` 复用 03 的 VirtualHome 人物行走帧和 11 的真实 cat 帧，生成最终面板使用的视频、JPG 和 JSONL。

当前实现不再使用简笔画宠物。真实宠物来源仍由 `environment_graph + expand_scene` 添加：

```text
默认 pet_type=cat
可改为 --pet-type dog
```

核心检测结果：

```json
{
  "schema": "external.vision_result.v1",
  "source": "placeholder_yolov11_or_a210",
  "scene": "kitchen_pet",
  "room": "kitchen",
  "smart_home_mode": "normal",
  "person_count": 0,
  "pet_type": "cat",
  "pet_count": 1,
  "kitchen_light": "off",
  "event": "pet_unattended_alert_light_off"
}
```

核心反馈动作：

```json
{
  "schema": "virtualhome.feedback.v1",
  "source": "external_agent",
  "scene": "kitchen_pet",
  "room": "kitchen",
  "action": "raise_alert_and_set_light",
  "target": "kitchen_pet_guard_and_light",
  "value": "alert_on_light_off",
  "reason": "normal_mode_person_count=0_pet_count=1",
  "payload": {
    "mode": "normal",
    "alert": "pet_unattended_in_kitchen",
    "set_light": {
      "target": "kitchen_ceiling_light",
      "value": "off"
    }
  }
}
```

真实宠物 API 原始输出：

```text
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/kitchen_pet_api_detection.mp4
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/jpg/kitchen/frame_*.jpg
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/external_result.jsonl
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/feedback_actions.jsonl
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/bluetooth_actions.jsonl
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/frame_manifest.jsonl
```

最终面板输出：

```text
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_alert.mp4
outputs/showcase_panel/kitchen_pet_owner_leave/jpg/kitchen/frame_*.jpg
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_external_result.jsonl
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_feedback_actions.jsonl
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_bluetooth_actions.jsonl
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_frame_manifest.jsonl
```

限制：预编译模拟器目前没有稳定的宠物 `[walk]` 动作接口，也无法在同一条 API `render_script` 中稳定驱动真实 cat 路径动画。因此最终展示使用“真实 cat 模型帧 + VirtualHome 官方人物行走渲染帧”的展示层合成，确保 720p/10fps、JPG 图像流、YOLO 替代结果和 agent 反馈时间线可稳定复现。

### 05 火灾烟雾报警

目标：出现火灾烟雾，视觉侧检测到 `fire_smoke`，agent 决策触发告警，手机界面收到告警通知。

运行：

```powershell
.\demo\virtualhome\12_generate_fire_smoke_alarm.bat
```

核心反馈动作：

```json
{
  "schema": "virtualhome.feedback.v1",
  "source": "external_agent",
  "scene": "fire_smoke",
  "room": "kitchen",
  "action": "raise_alert",
  "target": "fire_alarm",
  "value": "fire_smoke_detected",
  "reason": "person_count=0_and_smoke_detected",
  "payload": {
    "severity": "critical",
    "suggested_action": "notify_and_start_fire_alarm",
    "transport": "ble_placeholder"
  }
}
```

输出：

```text
outputs/showcase_panel/fire_smoke/fire_smoke_alarm.mp4
outputs/showcase_panel/fire_smoke/jpg/kitchen/frame_*.jpg
outputs/showcase_panel/fire_smoke/fire_smoke_external_detections.jsonl
outputs/showcase_panel/fire_smoke/fire_smoke_feedback_actions.jsonl
outputs/showcase_panel/fire_smoke/fire_smoke_bluetooth_actions.jsonl
```

说明：我检查了当前 Python API，只有场景图、摄像机、角色脚本等接口，没有稳定的烟雾/火焰粒子或火焰模型调用。为了避免画面粗糙，demo 只做烟雾叠加，不加入火焰模拟。

### 06 健康助手

目标：普通状态下保持暖光；人物心率升高后，agent 反馈冷光、播放预设音乐，并在模拟手机上显示缓解焦虑文字提示；30 秒音乐结束后，心率回归正常，音乐关闭，灯光回到暖光。

运行：

```powershell
.\demo\virtualhome\13_generate_health_assistant.bat
```

核心输入事件：

```json
{
  "schema": "external.health_event.v1",
  "source": "wearable_or_agent_placeholder",
  "scene": "health_event",
  "room": "bedroom",
  "event": "anxiety_detected",
  "payload": {
    "heart_rate": 114,
    "anxiety_score": 0.88,
    "light_state": "cool_blue",
    "music_state": "on",
    "confidence": 0.91
  }
}
```

核心反馈动作：

```json
{
  "schema": "virtualhome.feedback.v1",
  "source": "external_agent",
  "scene": "health_event",
  "room": "bedroom",
  "action": "set_environment",
  "target": "bedroom_ambient_light_and_music",
  "value": "anxiety_relief_mode",
  "reason": "wearable_detected_anxiety_high_heart_rate",
  "payload": {
    "light": "cool_blue",
    "music": "Debussy - Clair de Lune",
    "music_path": "outputs/showcase_panel/health_event/clair_de_lune_relief_demo.wav",
    "duration_seconds": 30,
    "agent_message": "检测到心率升高。请跟随 4-7-8 呼吸，放松肩颈，音乐将在 30 秒后自动关闭。"
  }
}
```

输出：

```text
outputs/showcase_panel/health_event/health_assistant.mp4
outputs/showcase_panel/health_event/clair_de_lune_relief_demo.wav
outputs/showcase_panel/health_event/jpg/bedroom/frame_*.jpg
outputs/showcase_panel/health_event/health_event_external_events.jsonl
outputs/showcase_panel/health_event/health_event_feedback_actions.jsonl
outputs/showcase_panel/health_event/health_event_bluetooth_actions.jsonl
```

### 07 离家模式陌生人告警

目标：系统状态设置为离家模式。全屋视角中出现陌生人，YOLO/身份识别占位结果返回 `unknown_person_count=1`，agent 占位反馈触发安防告警，并在模拟手机界面提示已通知紧急联系人。

运行：

```powershell
.\demo\virtualhome\14_generate_smart_mode_security_demos.bat
```

核心输入事件：

```json
{
  "schema": "external.security_result.v1",
  "source": "placeholder_yolov11_or_a210",
  "scene": "away_mode_stranger",
  "room": "all_rooms",
  "smart_home_mode": "away",
  "person_count": 1,
  "known_resident_count": 0,
  "unknown_person_count": 1,
  "alarm_active": true,
  "event": "away_mode_stranger_alert"
}
```

核心反馈动作：

```json
{
  "schema": "virtualhome.feedback.v1",
  "source": "external_agent",
  "scene": "away_mode_stranger",
  "room": "all_rooms",
  "action": "raise_alert",
  "target": "home_security_alarm",
  "value": "stranger_detected",
  "reason": "away_mode_unknown_person_detected",
  "payload": {
    "mode": "away",
    "severity": "critical",
    "message": "away_mode_stranger_detected"
  }
}
```

输出：

```text
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_alert.mp4
outputs/showcase_panel/away_mode_stranger/jpg/all_rooms/frame_*.jpg
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_external_result.jsonl
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_feedback_actions.jsonl
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_bluetooth_actions.jsonl
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_frame_manifest.jsonl
```

## 4. 接口文件

```text
src/virtualhome_env/interfaces/frame_stream_schema.json
src/virtualhome_env/interfaces/external_result_schema.json
src/virtualhome_env/interfaces/feedback_action_schema.json
src/virtualhome_env/interfaces/bluetooth_action_schema.json
```

导出接口样例：

```powershell
.\demo\virtualhome\03_export_interface_samples.bat
```

## 5. 与外部 Agent 的集成方式

当前最稳定的测试替代方案是文件夹接口：

```text
VirtualHome/Python 写出 JPG 帧和 frame_manifest.jsonl
外部 YOLO/A210 读取 JPG
外部 agent 写出 detection/feedback JSONL
展示面板读取 JSONL 并展示动作结果
```

后续可替换为：

```text
HTTP POST: 推送 JPG bytes 和元数据给 A210 服务
WebSocket: 双向传输帧事件、检测结果和反馈动作
RTSP/WebRTC: 需要连续视频流时由独立推流模块处理
BLE Gateway: 手机或 PC 服务读取蓝牙动作 JSON，再连接真实手表/手机
```

字段保持稳定，传输方式可以替换。

## 6. 当前可交付内容

```text
src/virtualhome_env/showcase_panel.py
src/virtualhome_env/virtualhome_api_motion_demo.py
src/virtualhome_env/virtualhome_api_pet_demo.py
src/virtualhome_env/scripted_showcase_demos.py
src/virtualhome_env/smart_mode_showcase_demos.py
src/virtualhome_env/video_to_jpg_stream.py
src/virtualhome_env/interfaces/*.json
demo/virtualhome/*.bat
docs/virtualhome_demo_runbook.md
docs/virtualhome_final_showcase_design.md
```

主展示优先保证稳定、清晰、可复查：视频至少 720p，帧率 10fps，逐帧 JPG 可直接作为 YOLO 输入替代，JSONL 记录可供队友接入或写测试。
