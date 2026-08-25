# VirtualHome Unity 源码手动下载与可编辑场景搭建

本文只写手动下载流程，不再使用命令行下载、`git clone` 或 `scripts/download_virtualhome_unity.ps1`。

目标是把 `virtualhome_unity` 源码工程下载到本机，用 Unity Editor 打开后自行编辑场景、拖动物体、修改摄像机和灯光，再重新打包成可由 Python API 控制的模拟器。

官方入口：

- VirtualHome Python/API 仓库：<https://github.com/xavierpuigf/virtualhome>
- VirtualHome Unity 源码仓库：<https://github.com/xavierpuigf/virtualhome_unity>
- VirtualHome 文档：<http://virtual-home.org/documentation/v2.2.0/get_started/get_started.html>
- VirtualHome API 交互文档：<http://virtual-home.org/documentation/v2.2.0/api/interaction.html>

## 1. 当前本机约定

工作区：

```text
D:\AAApersonal\VIRTUAL_HOME
```

已经可用的部分：

```text
vhome Python 虚拟环境
virtualhome Python/API 仓库
windows_exec\windows_exec.v2.2.4\VirtualHome.exe 预编译模拟器
```

后续手动下载的 Unity 源码工程建议放在：

```text
D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project
```

如果资源管理器里还能看到下面这些旧名字，并且它们不是你刚刚手动完整下载并确认过的工程，就把它们手动删除或改名，避免混淆：

```text
virtualhome_unity
virtualhome_unity_src
virtualhome_unity_src.zip
downloads
virtualhome_unity_extract_*
```

完整 Unity 工程至少应该包含：

```text
Assets
Packages
ProjectSettings
ProjectSettings\ProjectVersion.txt
```

只有一个 ZIP、只有 `.git`、或者缺少 `Assets` / `ProjectSettings`，都不要当作可用工程。

## 2. 手动下载 Unity 源码

1. 用浏览器打开：

   ```text
   https://github.com/xavierpuigf/virtualhome_unity
   ```

2. 点击页面右上方绿色的 `Code` 按钮。

3. 选择 `Download ZIP`。

4. 等浏览器下载完成。建议先下载到 `Downloads` 或桌面，不要覆盖工作区里旧的半成品目录。

5. 右键 ZIP，选择 `全部解压缩`，或用 7-Zip / WinRAR 解压。

6. 解压后通常会得到类似下面的文件夹名：

   ```text
   virtualhome_unity-master
   ```

7. 打开这个文件夹，确认里面直接能看到：

   ```text
   Assets
   Packages
   ProjectSettings
   ```

8. 把这个文件夹重命名为：

   ```text
   virtualhome_unity_project
   ```

9. 移动到工作区：

   ```text
   D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project
   ```

最终路径应类似：

```text
D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project\Assets
D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project\Packages
D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project\ProjectSettings\ProjectVersion.txt
```

## 3. 查看 Unity 版本

用记事本或 VS Code 打开：

```text
D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project\ProjectSettings\ProjectVersion.txt
```

找到这一行：

```text
m_EditorVersion: x.x.xfx
```

后面安装 Unity Editor 时，以这个版本为准。不要只按网上文章或旧文档猜版本，因为 Unity 工程对版本比较敏感。

## 4. 安装 Unity Hub 和 Unity Editor

1. 打开 Unity 下载页面：

   ```text
   https://unity.com/download
   ```

2. 下载并安装 `Unity Hub`。

3. 打开 Unity Hub，登录账号。

4. 进入 `Installs`。

5. 点击 `Install Editor`。

6. 安装 `ProjectVersion.txt` 指定的 Unity Editor 版本。

7. 安装模块时建议勾选：

   ```text
   Microsoft Visual Studio Community 或 Visual Studio Build Tools
   Windows Build Support
   ```

如果 Unity Hub 里找不到精确版本，进入 Unity Download Archive 搜索对应版本：

```text
https://unity.com/releases/editor/archive
```

## 5. 用 Unity Hub 打开源码工程

1. 打开 Unity Hub。

2. 进入 `Projects`。

3. 点击 `Add` / `Open` / `Add project from disk`。

4. 选择：

   ```text
   D:\AAApersonal\VIRTUAL_HOME\virtualhome_unity_project
   ```

5. 使用 `ProjectVersion.txt` 对应的 Unity Editor 打开。

6. 第一次打开会重新导入资源，可能需要较长时间。等右下角导入结束，Console 不再连续刷新后再操作。

7. 如果 Console 出现缺包提示，优先让 Unity 自动恢复 Packages。若是资源或脚本引用缺失，先记录具体错误，不要急着删除资源。

## 6. 在 Unity Editor 中查看和拖动场景

可以编辑的是 Unity Editor 里的 `Scene` 视图，不是预编译 exe 的运行窗口。

常用视角操作：

```text
鼠标右键 + WASD：飞行移动视角
鼠标滚轮：缩放
鼠标中键拖动：平移
Alt + 鼠标左键：围绕选中对象旋转
F：聚焦当前选中对象
```

常用编辑入口：

```text
Hierarchy：选择房间、家具、人物、摄像机、灯光
Scene：拖动、旋转、缩放对象
Inspector：修改 Transform、Camera、Light、脚本参数
Project：查找 scene、prefab、material、script
Console：查看编译错误和运行错误
```

建议先另存一份测试场景：

```text
File -> Save As...
SmartHome_Agent_Demo.unity
```

这样不会直接覆盖官方原始场景。

## 7. 预编译 exe 和源码工程的区别

`windows_exec\windows_exec.v2.2.4\VirtualHome.exe` 是已经打包好的运行程序：

- 可以被 Python API 控制；
- 可以打开窗口显示画面；
- 不能像 Unity 工程一样直接拖动物体、改摄像机、改灯光；
- 双击后 Unity logo 之后黑屏，不一定代表坏了，它通常需要 Python API 去 reset、加载环境和请求画面。

`virtualhome_unity_project` 是 Unity 源码工程：

- 可以在 Unity Editor 里编辑场景；
- 可以修改脚本和通信逻辑；
- 可以加入稳定的人物移动、隐藏、灯光控制接口；
- 修改后需要重新 Build 成新的 exe，再给 Python API 使用。

## 8. 在 Editor 里运行并连接 Python

如果 Unity 工程的通信服务在 Play 模式下会启动 HTTP 端口，可以这样测试：

1. 在 Unity Editor 中打开主场景。

2. 点击顶部 `Play`。

3. 看 Console 是否出现 HTTP 服务或通信端口信息。

4. 如果监听端口是 `8080`，可以另开 PowerShell 运行：

   ```powershell
   .\vhome\Scripts\python.exe .\src\virtualhome_env\smoke_test.py --attach --port 8080
   ```

5. 也可以采集房间摄像头的 720p 图像：

   ```powershell
   .\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --attach --port 8080 --snapshot-only --width 1280 --height 720
   ```

如果 Play 模式没有启动通信服务，就需要在 Unity 工程里定位 HTTP / communication 相关脚本，确认端口和启动逻辑。

## 9. 重新打包 Windows 模拟器

在 Unity Editor 中：

1. 打开 `File -> Build Settings`。

2. Platform 选择：

   ```text
   PC, Mac & Linux Standalone
   Windows
   x86_64
   ```

3. 确认 `Scenes In Build` 包含你编辑后的场景。

4. 点击 `Build`。

5. 输出到一个新的目录，例如：

   ```text
   D:\AAApersonal\VIRTUAL_HOME\custom_exec\VirtualHome.exe
   ```

不要覆盖官方预编译 exe，后续对比测试会更方便。

## 10. 用新 exe 跑 Python 测试

通信链接测试：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\smoke_test.py --simulator-path D:\AAApersonal\VIRTUAL_HOME\custom_exec\VirtualHome.exe
```

房间摄像头 720p / 10fps 采集：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --simulator-path D:\AAApersonal\VIRTUAL_HOME\custom_exec\VirtualHome.exe --width 1280 --height 720 --fps 10
```

如果你手动打开 exe 并指定端口：

```powershell
D:\AAApersonal\VIRTUAL_HOME\custom_exec\VirtualHome.exe -screen-fullscreen 0 -screen-quality 4 -http-port=8080
```

另开 PowerShell 连接：

```powershell
.\vhome\Scripts\python.exe .\src\virtualhome_env\room_camera_framework.py --attach --port 8080 --width 1280 --height 720 --fps 10
```

## 11. 和“自然走进/走出 + YOLO + 关灯”联动的关系

如果只用当前预编译 exe，人物离开房间的演示容易变成重载或瞬移，因为当前接口里没有稳定的 `remove_character` 能力。

更自然的路线有两种：

```text
短期展示：使用官方 render_script 录制动画，开启 skip_animation=False，输出 10fps/720p 视频和 JPG，再跑 YOLO/agent 决策。
长期实时系统：在 Unity 源码工程里加入稳定的人物移动、隐藏/移除、灯光控制 HTTP 接口，再由 Python 实时闭环控制。
```

源码工程最大的价值就在第二条：你可以在同一个场景里保持连续动画，把“人走进卧室 -> YOLO 检测人数 1 -> 人走出卧室 -> YOLO 检测人数 0 -> agent 决策关灯 -> Unity 灯光关闭”做成真正同步的闭环，而不是靠重建场景模拟。

## 12. 手动下载失败时怎么判断

常见问题：

```text
ZIP 很小或解压报错：下载中断，重新用浏览器下载。
没有 ProjectSettings：下载错仓库，可能下成了 virtualhome Python/API 仓库。
Unity Hub 要求升级工程：先取消，确认 ProjectVersion.txt 后安装对应 Editor。
Console 大量 missing asset：可能源码工程缺第三方资源，先截图或复制错误，再决定补资源还是换官方可执行版本。
双击 exe 黑屏：预编译运行窗口不是编辑器，先用 Python API reset/camera_image 测试。
```

最终判断标准：

```text
能用 Unity Hub 打开工程
能在 Scene 视图里看到户型场景
能拖动摄像机、灯光或家具
能 Build 出新的 Windows exe
Python API 能连接这个新 exe
```
