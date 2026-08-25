# VirtualHome 展示运行手册

本文对应当前工作区的实际实现。现在先放置 Unity 源码修复，优先使用官方预编译模拟器和 Python 展示面板完成结项展示：VirtualHome 负责家居环境、画面输出、场景事件和反馈接口；YOLO、A210、云端大语言模型、真实蓝牙、真实拨号/短信由外部模块负责。

## 1. 当前目录边界

```text
windows_exec/                  官方预编译 Windows 模拟器
virtualhome/                   官方 Python API 仓库
virtualhome_unity_project/     Unity 源码项目，当前保留备用
vhome/                         当前 Python 虚拟环境
src/virtualhome_env/           VirtualHome 侧脚本、展示面板、接口 schema
demo/virtualhome/              可双击运行的 demo 批处理入口
assets/demo_sources/           Python-only demo 使用的 VirtualHome 截图素材
outputs/showcase_panel/        展示视频、逐帧 JPG、JSONL 接口样例
outputs/room_cameras/          房间摄像头截图和全屋预览图
```

## 2. 推荐展示顺序

1. 先运行 `10_generate_scripted_showcase_demos.bat`，生成火灾烟雾报警和健康助手两个补充视频。
2. 如果要展示官方自然动画，打开 `windows_exec/windows_exec.v2.2.4/VirtualHome.exe`，选择 Windowed，点击 `Play!`。
3. 运行 `08_api_bedroom_walk_light_attach.bat`，生成人员计数 + YOLO 人数 + 卧室无人关灯联动视频。
4. 运行 `11_generate_kitchen_pet_alert.bat`，生成真实宠物模型进入厨房 + 手机告警视频。
5. 运行 `14_generate_smart_mode_security_demos.bat`，生成 04 普通模式宠物留守告警和 07 离家模式陌生人告警两个优化样本。
6. 运行 `03_export_interface_samples.bat`，导出最新接口样例。
7. 双击 `02_showcase_panel.bat` 打开 Python 展示面板。
8. 在面板中依次点击 01-07 场景。
9. 最后打开输出目录，展示 MP4、JPG 帧和 JSONL 数据契约。

## 3. 一键脚本

在 `demo/virtualhome` 目录中可以直接双击这些批处理文件，也可以在 PowerShell 中运行。

```text
01_generate_bedroom_walk_light.bat       生成 Python-only 卧室人员进出 + YOLO 跟随 + 无人关灯 demo
02_showcase_panel.bat                    打开本地展示控制台
03_export_interface_samples.bat          导出接口 JSONL 样例
04_editor_attach_smoke_test.bat          Unity Editor Play 模式连接测试，源码路线备用
05_capture_room_cameras_720p.bat         从 Unity Editor Play 模式采集房间摄像头，源码路线备用
06_export_kitchen_pet_jpg_stream.bat     从当前可显示的宠物视频重新导出 720p/10fps JPG 帧
07_generate_fall_bluetooth_emergency.bat 生成跌倒检测 + 蓝牙手表/手机应急联动扩展示例
08_api_bedroom_walk_light_attach.bat     连接可视化 VirtualHome.exe，运行固定卧室摄像头人员进出 + 关灯脚本
09_api_fall_lie_ble_attach.bat           连接可视化 VirtualHome.exe，运行官方 API 异常姿态 + 蓝牙应急扩展示例
10_generate_scripted_showcase_demos.bat  生成火灾烟雾、健康助手两个补充 demo
11_generate_kitchen_pet_alert.bat        连接 VirtualHome.exe，生成真实宠物模型 + 手机 BLE 告警 demo
12_generate_fire_smoke_alarm.bat         只生成火灾烟雾 + 手机告警 demo
13_generate_health_assistant.bat         只生成健康助手 + 可播放音乐 demo
14_generate_smart_mode_security_demos.bat 生成 04 普通模式宠物留守告警和 07 离家模式陌生人告警优化样本
```

常用命令：

```powershell
.\demo\virtualhome\10_generate_scripted_showcase_demos.bat
.\demo\virtualhome\14_generate_smart_mode_security_demos.bat
.\demo\virtualhome\03_export_interface_samples.bat
.\demo\virtualhome\02_showcase_panel.bat
```

官方 API 自然动画需要先手动打开：

```text
windows_exec/windows_exec.v2.2.4/VirtualHome.exe
```

进入 Unity 启动窗口后选择 Windowed，点击 `Play!`，等场景出现后运行：

```powershell
.\demo\virtualhome\08_api_bedroom_walk_light_attach.bat
.\demo\virtualhome\11_generate_kitchen_pet_alert.bat
.\demo\virtualhome\09_api_fall_lie_ble_attach.bat
```

## 4. 展示面板

主入口：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\showcase_panel.py
```

面板左侧播放当前场景视频或截图，右侧提供场景按钮、局部操作按钮、模拟手机界面和数据契约。底部状态区显示：

```text
CAMERA STREAM    720p / 10fps / JPG 图像流
EDGE VISION      YOLO/A210 占位检测结果
BLE DEVICES      智能手表/手机蓝牙联动占位动作
FEEDBACK         VirtualHome 接收的外部 agent 决策动作
```

展示面板包含轻量科幻风 UI 和自适应布局：

```text
CAMERA STREAM 画布：四角锁定框，不遮挡主体视频
状态卡片：按不同相位呼吸高亮
底部 ticker：滚动显示当前 stream、vision、feedback、BLE 状态
PHONE / AGENT LINK：有手机联动的 demo 会显示脉冲边框和 BLE ACTIVE 状态
右侧控制区：可用鼠标滚轮滑动，小窗口下也能看到全部 UI
```

全屋俯瞰交互：

```text
左键拖动：平移
鼠标滚轮：缩放
VIEW CAMERA / Connect API：连接已进入 Play 的 VirtualHome.exe，让面板可以调用 `camera_image`
Yaw - / Yaw +：左右旋转 Unity 摄像机
Pitch + / Pitch -：调整俯仰角
Left / Right / Forward / Back / Up / Down：移动 Unity 摄像机
FOV - / FOV +：调整视场角
Reset View / Reset Overview：恢复全屋俯瞰相机位
Sound ON/OFF：健康助手场景中开启或关闭本地音乐播放
```

说明：VirtualHome API 没有公开旋转整套房屋模型的接口，所以 01 不旋转房屋本体；面板通过摄像机控制刷新 1280x720 画面。若当前预编译模拟器支持 `update_camera`，则直接更新摄像机；若返回 `Unknown action update_camera`，面板会自动降级为每次 `add_camera + camera_image` 刷新，不再在 UI 中报错。未连接模拟器时仍显示静态俯瞰图。

注意：蓝牙、拨号、短信均为 demo-only 占位记录，不会触发真实设备。后续真实接入时，应由独立蓝牙/手机网关读取这些 JSON 或 HTTP 消息，再调用实际设备能力。

## 5. 主展示输出

人员计数和无人关灯：

```text
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/bedroom_walk_light_yolo_light_feedback.mp4
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/jpg/bedroom/frame_*.jpg
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/yolo_person_count.jsonl
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/feedback_actions.jsonl
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/bedroom_yolo_light_sync_metadata.json
```

厨房宠物真实模型原始输出：

```text
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/kitchen_pet_api_detection.mp4
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/jpg/kitchen/frame_*.jpg
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/external_result.jsonl
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/feedback_actions.jsonl
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/bluetooth_actions.jsonl
outputs/showcase_panel/virtualhome_api_pet/kitchen_pet/frame_manifest.jsonl
```

04 面板最终使用的普通模式宠物留守联动输出：

```text
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_alert.mp4
outputs/showcase_panel/kitchen_pet_owner_leave/jpg/kitchen/frame_*.jpg
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_external_result.jsonl
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_feedback_actions.jsonl
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_bluetooth_actions.jsonl
outputs/showcase_panel/kitchen_pet_owner_leave/kitchen_pet_owner_leave_frame_manifest.jsonl
```

04 使用 VirtualHome 自带 `cat` 模型作为真实宠物来源。当前预编译模拟器没有稳定的 cat 行走动画，所以 `11` 号脚本负责生成真实 cat 模型帧；`14` 号脚本再复用 03 的 VirtualHome 官方人物行走渲染帧，组成“cat 一直在厨房 -> 主人进入/离开 -> person_count=0 + pet_count=1 -> 告警 + 只关闭厨房灯”的展示链路。脚本会先清理上一次失败运行残留的 cat/dog 节点，再把 cat 放到厨房 `floor` 上；`expand_scene` 偶发 `unaligned_ids` 时会自动短暂重试。

火灾烟雾报警：

```text
outputs/showcase_panel/fire_smoke/fire_smoke_alarm.mp4
outputs/showcase_panel/fire_smoke/jpg/kitchen/frame_*.jpg
outputs/showcase_panel/fire_smoke/fire_smoke_frame_manifest.jsonl
outputs/showcase_panel/fire_smoke/fire_smoke_external_detections.jsonl
outputs/showcase_panel/fire_smoke/fire_smoke_feedback_actions.jsonl
outputs/showcase_panel/fire_smoke/fire_smoke_bluetooth_actions.jsonl
```

健康助手：

```text
outputs/showcase_panel/health_event/health_assistant.mp4
outputs/showcase_panel/health_event/clair_de_lune_relief_demo.wav
outputs/showcase_panel/health_event/jpg/bedroom/frame_*.jpg
outputs/showcase_panel/health_event/health_event_frame_manifest.jsonl
outputs/showcase_panel/health_event/health_event_external_events.jsonl
outputs/showcase_panel/health_event/health_event_feedback_actions.jsonl
outputs/showcase_panel/health_event/health_event_bluetooth_actions.jsonl
```

离家模式陌生人告警：

```text
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_alert.mp4
outputs/showcase_panel/away_mode_stranger/jpg/all_rooms/frame_*.jpg
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_external_result.jsonl
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_feedback_actions.jsonl
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_bluetooth_actions.jsonl
outputs/showcase_panel/away_mode_stranger/away_mode_stranger_frame_manifest.jsonl
```

统一接口样例：

```text
outputs/showcase_panel/interface_samples/virtualhome_frame_stream_sample.jsonl
outputs/showcase_panel/interface_samples/external_result_sample.jsonl
outputs/showcase_panel/interface_samples/virtualhome_feedback_action_sample.jsonl
outputs/showcase_panel/interface_samples/virtualhome_bluetooth_action_sample.jsonl
outputs/showcase_panel/interface_samples/showcase_scenarios.json
```

01 实时相机按键刷新后，会额外保存最新画面：

```text
outputs/showcase_panel/live_overview/latest_overview_camera.jpg
```

## 6. 图像流接口

VirtualHome 输出给外部视觉模块的单帧消息：

```json
{
  "schema": "virtualhome.frame.v1",
  "stream_id": "bedroom_camera_0",
  "scene": "virtualhome_api_bedroom_walk_light",
  "room": "bedroom",
  "camera_id": 0,
  "frame_index": 10,
  "timestamp": 1.0,
  "resolution": [1280, 720],
  "fps": 10,
  "image": {
    "encoding": "jpg",
    "mime": "image/jpeg",
    "path": "outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/jpg/bedroom/frame_000010.jpg"
  }
}
```

Schema 文件：

```text
src/virtualhome_env/interfaces/frame_stream_schema.json
```

## 7. 外部检测结果接口

人员检测示例：

```json
{
  "schema": "external.vision_result.v1",
  "source": "placeholder_yolov11_or_a210",
  "scene": "virtualhome_api_bedroom_walk_light",
  "room": "bedroom",
  "person_count": 1,
  "event": "person_present"
}
```

宠物检测示例：

```json
{
  "schema": "external.vision_result.v1",
  "source": "placeholder_yolov11_or_a210",
  "scene": "kitchen_pet",
  "room": "kitchen",
  "pet_type": "cat",
  "pet_count": 1,
  "event": "pet_entered_sensitive_area"
}
```

火灾烟雾示例：

```json
{
  "schema": "external.vision_result.v1",
  "source": "placeholder_yolov11_or_a210",
  "scene": "fire_smoke",
  "room": "kitchen",
  "hazard_detected": true,
  "hazard_type": "fire_smoke",
  "risk_level": "critical"
}
```

焦虑检测示例：

```json
{
  "schema": "external.health_event.v1",
  "source": "wearable_or_agent_placeholder",
  "scene": "health_event",
  "room": "bedroom",
  "event": "anxiety_detected",
  "payload": {
    "heart_rate": 114,
    "anxiety_score": 0.88
  }
}
```

Schema 文件：

```text
src/virtualhome_env/interfaces/external_result_schema.json
```

## 8. VirtualHome 反馈动作接口

无人关灯示例：

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

健康助手示例：

```json
{
  "schema": "virtualhome.feedback.v1",
  "source": "external_agent",
  "scene": "health_event",
  "room": "bedroom",
  "action": "set_environment",
  "target": "bedroom_ambient_light_and_music",
  "value": "anxiety_relief_mode",
  "payload": {
    "light": "cool_blue",
    "music": "Debussy - Clair de Lune",
    "agent_message": "检测到心率升高。请跟随 4-7-8 呼吸，放松肩颈，音乐将在 30 秒后自动关闭。"
  }
}
```

Schema 文件：

```text
src/virtualhome_env/interfaces/feedback_action_schema.json
```

## 9. 蓝牙手表/手机占位接口

蓝牙动作目前只写 JSONL，不做真实设备连接：

```json
{
  "schema": "virtualhome.bluetooth_action.v1",
  "scene": "fire_smoke",
  "timestamp": 1.6,
  "transport": "ble_placeholder",
  "device_type": "mobile_phone",
  "device_id": "phone_demo_01",
  "action": "notify",
  "payload": {
    "title": "Fire smoke alert",
    "hazard_type": "fire_smoke",
    "mode": "demo_only"
  }
}
```

Schema 文件：

```text
src/virtualhome_env/interfaces/bluetooth_action_schema.json
```

## 10. 当前限制

Python-only demo 使用 VirtualHome 截图和画面叠加，适合验证数据流、时间线和闭环逻辑；官方 API demo 使用 `comm.add_character()`、`comm.render_script()` 和固定摄像头，更适合展示人物自然行走。

人员计数和无人关灯：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_motion_demo.py --attach --scenario bedroom_walk_light --fps 10 --width 1280 --height 720 --camera-mode AUTO --fixed-camera-fov 58 --fixed-camera-height-ratio 0.38 --time-scale 1.35
```

厨房宠物：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_pet_demo.py --attach --pet-type cat --fps 10 --width 1280 --height 720
```

当前预编译模拟器没有稳定的宠物行走动作，也没有稳定烟雾/火焰粒子 API。因此宠物 demo 使用真实宠物模型实例进入检测链路，火灾 demo 只使用烟雾视频叠加。真实宠物路径动画和真实 Unity 粒子效果需要在 Unity 源码项目依赖补齐后实现。
