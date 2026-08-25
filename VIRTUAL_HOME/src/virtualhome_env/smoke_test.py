"""
VirtualHome Unity simulator smoke tests.

运行方式：
    D:\\AAApersonal\\VIRTUAL_HOME\\vhome\\Scripts\\python.exe .\\src\\virtualhome_env\\smoke_test.py

如果模拟器 exe 不在默认位置，可以先设置环境变量：
    $env:VIRTUALHOME_SIMULATOR_PATH = "D:\\path\\to\\VirtualHome.exe"

测试用例在 TEST_CASES 中配置。当前本地 windows_exec.v2.2.4 可以通信、
读取默认环境图和获取相机图片，但不支持新版 API 的 reset(0) 所需
clear/environment 动作，所以 reset 失败时脚本会继续测试默认已加载场景。
"""

import os
import sys
import time
import argparse
from pathlib import Path

from PIL import Image


# 根目录：D:\AAApersonal\VIRTUAL_HOME
REPO_ROOT = Path(__file__).resolve().parents[2]

# Python API 仓库目录：D:\AAApersonal\VIRTUAL_HOME\virtualhome
# 加入 sys.path 后，即使没有 pip install -e，也可以导入本地 virtualhome 包。
PACKAGE_REPO = REPO_ROOT / "virtualhome"

# 当前工作区里已有的 Windows 模拟器可执行文件。
DEFAULT_SIMULATOR = REPO_ROOT / "windows_exec" / "windows_exec.v2.2.4" / "VirtualHome.exe"

sys.path.insert(0, str(PACKAGE_REPO))

from virtualhome.simulation.unity_simulator import comm_unity


# 在这里设置测试用例。
# 需要增加测试时，复制一个 dict，然后修改 name/camera_index/分辨率/输出文件名。
TEST_CASES = [
    {
        "name": "default_scene_camera_0",
        "environment": 0,
        "camera_index": 0,
        "mode": "normal",
        "image_width": 1280,
        "image_height": 720,
        "output": "outputs/smoke_test/camera_0.png",
    },
    # 示例：打开后可测试另一个相机或较小分辨率。
    # {
    #     "name": "default_scene_camera_1_small",
    #     "environment": 0,
    #     "camera_index": 1,
    #     "mode": "normal",
    #     "image_width": 320,
    #     "image_height": 240,
    #     "output": "camera_1_small.png",
    # },
]


def simulator_command(comm, action, int_params=None, string_params=None):
    """发送底层 Unity HTTP action，用于打印更详细的原始响应。"""
    request = {"id": str(time.time()), "action": action}
    if int_params is not None:
        request["intParams"] = int_params
    if string_params is not None:
        request["stringParams"] = string_params
    return comm.post_command(request)


def reset_environment(comm, environment):
    """按官方新版 API 的 reset 逻辑测试指定环境。

    comm.reset(environment) 内部会发送 clear 和 environment 两个 action。
    当前本地 windows_exec.v2.2.4 返回 Unknown action，因此这里不直接抛错，
    而是把原始响应打印出来，方便判断是不是模拟器协议版本不匹配。
    """
    int_params = [] if environment is None else [environment]

    clear_response = simulator_command(comm, "clear", int_params)
    print(f"clear response: {clear_response}")

    environment_response = simulator_command(comm, "environment", int_params)
    print(f"environment response: {environment_response}")

    return environment_response.get("success", False)


def resolve_simulator_path() -> Path:
    """优先使用环境变量指定的 exe，否则使用工作区里的默认 exe。"""
    env_path = os.environ.get("VIRTUALHOME_SIMULATOR_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_SIMULATOR


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VirtualHome Unity simulator smoke tests")
    parser.add_argument("--simulator-path", type=Path, default=None, help="Path to VirtualHome.exe")
    parser.add_argument("--attach", action="store_true", help="Attach to Unity Editor Play mode or a manually started exe")
    parser.add_argument("--port", default="8080", help="HTTP port used by Unity")
    parser.add_argument("--timeout-wait", type=int, default=10, help="HTTP timeout in seconds")
    return parser


def save_image(image, output_path: Path) -> None:
    """保存 camera_image 返回的图像。

    comm_unity 内部用 OpenCV 解码普通 RGB 图像，返回数组通道顺序是 BGR；
    Pillow 保存时需要 RGB，因此 3 通道图像保存前要反转通道。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if image.ndim == 3 and image.shape[2] == 3:
        Image.fromarray(image[:, :, ::-1]).save(output_path)
    else:
        Image.fromarray(image).save(output_path)


def run_test_case(comm, test_case) -> None:
    """执行一个测试用例：reset、读取环境图、检查相机、获取图片。"""
    name = test_case["name"]
    environment = test_case.get("environment")
    camera_index = test_case["camera_index"]
    mode = test_case.get("mode", "normal")
    image_width = test_case.get("image_width", 640)
    image_height = test_case.get("image_height", 480)
    output_path = REPO_ROOT / test_case.get("output", f"{name}.png")

    print()
    print(f"=== Test case: {name} ===")

    reset_ok = reset_environment(comm, environment)
    print(f"reset({environment}): {reset_ok}")
    if not reset_ok:
        print("reset is not supported by this local executable; continuing with the default loaded scene.")

    graph_ok, graph = comm.environment_graph()
    print(f"environment_graph: {graph_ok}")
    if not graph_ok:
        raise RuntimeError("environment_graph failed")
    print(f"environment nodes: {len(graph.get('nodes', []))}")
    print(f"environment edges: {len(graph.get('edges', []))}")

    camera_ok, camera_count = comm.camera_count()
    print(f"camera_count: success={camera_ok}, count={camera_count}")
    if not camera_ok:
        raise RuntimeError("camera_count failed")
    if camera_index < 0 or camera_index >= camera_count:
        raise ValueError(f"camera_index {camera_index} is outside valid range 0..{camera_count - 1}")

    success, images = comm.camera_image(
        [camera_index],
        mode=mode,
        image_width=image_width,
        image_height=image_height,
    )
    print(f"camera_image([{camera_index}], mode={mode!r}): {success}")
    if not success or not images:
        raise RuntimeError(f"camera_image([{camera_index}]) failed")

    image = images[0]
    print(f"image[0].shape: {image.shape}")

    save_image(image, output_path)
    print(f"Saved image: {output_path}")


def main() -> None:
    args = build_arg_parser().parse_args()
    simulator_path = args.simulator_path or resolve_simulator_path()

    if args.attach:
        print(f"Attaching to an already running Unity simulator/editor on port {args.port}")
    else:
        if not simulator_path.exists():
            raise FileNotFoundError(f"Simulator not found: {simulator_path}")
        print(f"Using simulator: {simulator_path}")

    comm = None
    try:
        if args.attach:
            # 不传 file_name 时，UnityCommunication 只连接已有端口，不会启动或关闭 Unity Editor。
            comm = comm_unity.UnityCommunication(
                port=args.port,
                logging=False,
                timeout_wait=args.timeout_wait,
            )
        else:
            # file_name 指向 exe 后，UnityCommunication 会自动启动模拟器并连接 HTTP API。
            comm = comm_unity.UnityCommunication(
                file_name=str(simulator_path),
                port=args.port,
                logging=False,
                timeout_wait=args.timeout_wait,
            )

        connected = comm.check_connection()
        print(f"Communication link: {connected}")
        if not connected:
            raise RuntimeError("Simulator did not respond to the idle check")

        for test_case in TEST_CASES:
            run_test_case(comm, test_case)
    finally:
        # 关闭由本脚本启动的 Unity 进程，避免端口 8080 被占用。
        if comm is not None:
            comm.close()


if __name__ == "__main__":
    main()
