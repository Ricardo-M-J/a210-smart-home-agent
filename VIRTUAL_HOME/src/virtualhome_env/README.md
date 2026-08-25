# VirtualHome Environment Module

This folder contains only the VirtualHome-side work:

- Unity/Python communication smoke test
- 720p/10fps room-camera image stream
- local showcase panel
- example scene media generation
- frame-stream and feedback-action interface samples
- Bluetooth watch/phone emergency-link placeholder samples
- JSON schema files for external integration

It intentionally does not implement YOLO, A210 inference, cloud LLM, or agent decision logic.

Run from the repository root:

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\smoke_test.py --attach --port 8080
.\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --attach --port 8080 --snapshot-only --width 1280 --height 720
.\vhome\Scripts\python.exe .\src\virtualhome_env\bedroom_walk_light_demo.py
.\vhome\Scripts\python.exe .\src\virtualhome_env\fall_bluetooth_emergency_demo.py
.\vhome\Scripts\python.exe .\src\virtualhome_env\scripted_showcase_demos.py --scenario all
.\vhome\Scripts\python.exe .\src\virtualhome_env\smart_mode_showcase_demos.py --scenario all
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_pet_demo.py --attach
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_motion_demo.py --attach --scenario bedroom_walk_light
.\vhome\Scripts\python.exe .\src\virtualhome_env\virtualhome_api_motion_demo.py --attach --scenario fall_lie_ble
.\vhome\Scripts\python.exe .\src\virtualhome_env\video_to_jpg_stream.py --video .\outputs\showcase_panel\virtualhome_api_pet\kitchen_pet\kitchen_pet_api_detection.mp4 --jpg-dir .\outputs\showcase_panel\virtualhome_api_pet\kitchen_pet\jpg\kitchen --manifest .\outputs\showcase_panel\virtualhome_api_pet\kitchen_pet\frame_manifest.jsonl --scene kitchen_pet --room kitchen --stream-id kitchen_camera_0
.\vhome\Scripts\python.exe .\src\virtualhome_env\showcase_panel.py
.\vhome\Scripts\python.exe .\src\virtualhome_env\agent_bridge.py --agent-url http://127.0.0.1:8019 --scene kitchen_pet
```

Shortcut batch files are in:

```text
demo\virtualhome
```

Main runbook:

```text
docs\virtualhome_demo_runbook.md
```

`virtualhome_api_motion_demo.py --scenario bedroom_walk_light` 是当前主展示脚本：它使用一个固定卧室摄像头，导出 `jpg/bedroom/frame_*.jpg` 给 YOLO 替代输入，并同步生成 `yolo_person_count.jsonl` 与 `feedback_actions.jsonl`。

全屋俯瞰场景默认使用 `outputs/room_cameras/full_scene_overview_normal.png`。VirtualHome API 没有公开旋转整套房屋模型的接口，因此不再保留全屋旋转脚本；展示面板改为在 01 场景中提供 `VIEW CAMERA` 按键。连接 `VirtualHome.exe` 后优先通过 `update_camera + camera_image` 移动/旋转 Unity 摄像机；如果 exe 返回 `Unknown action update_camera`，自动降级为 `add_camera + camera_image` 刷新 720p 图像。

`virtualhome_api_pet_demo.py` 使用 `environment_graph + expand_scene` 添加 VirtualHome 官方真实宠物模型。`smart_mode_showcase_demos.py` 在此基础上生成 04 普通模式宠物留守告警和 07 离家模式陌生人告警：04 的猫来自真实 VirtualHome 模型帧，主人/陌生人动作来自 03 的 VirtualHome 官方人物行走渲染帧。面板不再回退到旧合成宠物视频；真实宠物视频缺失时先运行 11 号脚本，再运行 14 号脚本。`scripted_showcase_demos.py` 生成火灾烟雾报警和健康助手联动。

