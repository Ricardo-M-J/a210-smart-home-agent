# VirtualHome 智能家居视觉仿真展示

首次克隆本仓库的协作者请先阅读根目录 `README.md` 的“协作者首次配置”。其中写明了 Git LFS、`vhome` 环境、Agent `.env`、以及 GitHub 无法托管的 `VirtualHome_Data/resources.assets.resS` 外部大文件如何恢复。本文件只说明 VirtualHome 侧展示脚本。

本仓库当前只维护 VirtualHome 虚拟环境侧：家居场景展示、房间摄像头图像流、示例事件脚本、反馈动作接口和演示 UI。YOLO、A210 边缘推理、云端大语言模型、真实蓝牙/拨号/短信由外部模块集成。

## 快速运行

从仓库根目录运行：

```powershell
.\demo\virtualhome\01_generate_bedroom_walk_light.bat
.\demo\virtualhome\07_generate_fall_bluetooth_emergency.bat
.\demo\virtualhome\10_generate_scripted_showcase_demos.bat
.\demo\virtualhome\14_generate_smart_mode_security_demos.bat
.\demo\virtualhome\03_export_interface_samples.bat
.\demo\virtualhome\02_showcase_panel.bat
```

也可以直接打开 `demo/virtualhome` 目录双击批处理脚本。

如果要使用 VirtualHome 官方角色动画，而不是 Python 合成动画，先手动打开 `windows_exec/windows_exec.v2.2.4/VirtualHome.exe`，选择 Windowed 并点击 `Play!`，再运行：

```powershell
.\demo\virtualhome\08_api_bedroom_walk_light_attach.bat
.\demo\virtualhome\11_generate_kitchen_pet_alert.bat
.\demo\virtualhome\09_api_fall_lie_ble_attach.bat
```

我已用当前预编译 exe 跑通过 API 自然动画版：

```text
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/bedroom_walk_light_api_recording.mp4
outputs/showcase_panel/virtualhome_api_motion/bedroom_walk_light/bedroom_walk_light_yolo_light_feedback.mp4
outputs/showcase_panel/virtualhome_api_motion/fall_lie_ble/fall_lie_ble_api_recording.mp4
```

主展示场景现在只使用一个固定卧室摄像头：人物走进房间后 `yolo_person_count.jsonl` 中 `person_count=1`，人物离开后 `person_count=0`，脚本会根据真实渲染后的人物出现区间自动写入 `feedback_actions.jsonl` 触发 `set_light(off)`。重新运行 `08_api_bedroom_walk_light_attach.bat` 后，视频目标约为 200 帧。

全屋俯瞰说明：VirtualHome Python API 没有公开“旋转整套房屋模型”的接口。当前 01 场景采用两级展示：未连接模拟器时显示静态全屋图并支持平移/缩放；打开 `VirtualHome.exe` 并点击 `Play!` 后，可在面板右侧 `VIEW CAMERA` 中连接、旋转/移动 Unity 摄像机，并实时刷新 720p 画面。若当前 exe 不支持 `update_camera`，面板会自动改用 `add_camera + camera_image` 刷新。`Reset View` 会回到全屋俯瞰相机位。

## 当前展示内容

```text
全屋环境俯瞰交互
多摄像头布设
人员计数和无人关灯
普通模式宠物留守告警
火灾烟雾报警
健康助手：暖光 -> 冷光 + 音乐 -> 暖光
离家模式陌生人告警
```

展示面板已加入状态卡片呼吸高亮、底部数据流 ticker、手机联动脉冲边框和右侧可滚动控制区。左侧视频区只保留轻量四角锁定框，避免遮挡仿真画面。

跌倒检测与蓝牙手表/手机应急联动脚本仍保留为扩展示例：`07_generate_fall_bluetooth_emergency.bat` 和 `09_api_fall_lie_ble_attach.bat`。

## 主要文档

```text
docs/virtualhome_demo_runbook.md            运行步骤和输出说明
docs/virtualhome_final_showcase_design.md   结项展示设计
src/virtualhome_env/README.md               VirtualHome 侧脚本说明
demo/virtualhome/README.md                  可双击脚本说明
```

## 主要接口

```text
src/virtualhome_env/interfaces/frame_stream_schema.json
src/virtualhome_env/interfaces/external_result_schema.json
src/virtualhome_env/interfaces/feedback_action_schema.json
src/virtualhome_env/interfaces/bluetooth_action_schema.json
```

所有真实外部能力都走接口占位：当前 demo 不会真实连接蓝牙设备，不会真实拨号，也不会真实发送短信。

说明：VirtualHome 官方渲染器已经验证可自然执行 `[walk]`、`[sit]`；当前预编译 `windows_exec.v2.2.4` 不支持 `[fall]`，并且实测 `[lie]` 会返回 `Requested value 'lie' was not found`。真实“摔倒到地面”需要在 Unity 源码中加入 fall 动画或状态机后重新构建模拟器。
