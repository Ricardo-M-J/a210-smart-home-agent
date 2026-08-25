# Unity Editor 中运行 VirtualHome 并让 Python 控制

当前工程路径：

```text
D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project
```

这个源码工程已经包含 VirtualHome 的 Python API 通信服务。核心启动脚本是：

```text
Assets\Story Generator\Scripts\TestDriver.cs
Assets\Story Generator\Scripts\Communication.cs
```

`TestDriver` 在 `Start()` 中启动 HTTP 通信服务，默认端口是 `8080`。Python 端使用已有 `virtualhome` API 连接即可。

## 1. Editor 里空白怎么办

Unity 打开工程后空白通常不是项目坏了，而是还没有打开主场景。

在 Unity 的 `Project` 面板中打开：

```text
Assets -> Story Generator -> Scene -> Scene_0.unity
```

也可以打开：

```text
Assets -> Story Generator -> Scene -> Scene_1.unity
```

当前 `Build Settings` 中启用的场景是：

```text
Assets/Story Generator/Scene/Scene_0.unity
Assets/Story Generator/Scene/Scene_1.unity
```

打开场景后，如果 `Scene` 视图还是看不见户型：

1. 打开 `Hierarchy`。
2. 选中房间、地板、家具或根节点。
3. 按 `F` 聚焦。
4. 用鼠标右键 + `WASD` 移动视角。

## 2. 在 Editor 中启动通信服务

1. 打开 `Scene_0.unity`。
2. 看 `Hierarchy` 顶部应有一个名为 `GameObject` 的对象。
3. 选中它，Inspector 里应能看到：

   ```text
   TestDriver
   Recorder
   LightingManager
   Gravity
   ```

4. 点击 Unity 顶部的 `Play`。
5. 保持 Unity Editor 处于 Play 模式。

如果 Console 中反复出现：

```text
Waiting for request
```

说明 Unity 侧已经在等 Python 请求。

## 3. Python 连接 Editor Play 模式

另开 PowerShell，进入工作区：

```powershell
cd D:\AAApersonal\VIRTUAL_HOME
```

运行通信测试：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\smoke_test.py --attach --port 8080
```

成功时应该看到类似：

```text
Communication link: True
environment_graph: True
camera_count: success=True
camera_image([0], mode='normal'): True
image[0].shape: ...
Saved image: D:\AAApersonal\VIRTUAL_HOME\outputs\smoke_test\camera_0.png
```

如果连接失败：

```text
Connection refused
Communication link: False
```

通常是 Unity 没有进入 Play，或者端口不是 `8080`。

## 4. 采集每个房间摄像头

Editor 保持 Play 模式，然后运行：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --attach --port 8080 --snapshot-only --width 1280 --height 720
```

输出目录：

```text
outputs\room_cameras
```

这里会导出：

```text
rooms.json
room_cameras.json
room_camera_contact_sheet_normal.png
每个房间一张 720p JPG/PNG
```

录制 10fps 视频：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --attach --port 8080 --width 1280 --height 720 --fps 10 --duration 5
```

## 5. 做“人物自然走进/走出 + YOLO + 关灯”的正确路线

短期演示：

```text
Python 面板生成/播放 demo
VirtualHome 输出 JPG
YOLO/A210 读取 JPG
外部系统返回 set_light(off)
Python/Unity 接收反馈并显示关灯
```

已经有的 Python-only 演示：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\bedroom_walk_light_demo.py
.\vhome\Scripts\python.exe .\src\virtualhome_env\showcase_panel.py
```

长期 Unity 源码版本：

```text
1. 在 Unity 场景中保留真实人物 CharacterControl / Animator / NavMeshAgent。
2. 新增或扩展 HTTP action，例如 smart_home_event、set_light、move_character_route。
3. Python 发送人物进入/离开脚本。
4. Unity 真实移动人物。
5. Python 每帧 camera_image 取 720p JPG。
6. 外部 YOLO/A210 返回 person_count。
7. Python/agent 返回 set_light(off)。
8. Unity 关闭真实灯光。
```

## 6. 当前最小闭环

当前可以先验证这条链：

```text
Unity Editor Play
  -> Python attach
  -> camera_image 720p/10fps
  -> JPG manifest
  -> 外部 agent 接口样例
  -> Python 面板展示关灯反馈
```

真正修改 Unity 里的人物自然行走和灯光开关接口，需要在 `TestDriver.cs` 增加新的 action，并在 Unity 场景中找到目标角色、目标灯光对象后控制它们。
