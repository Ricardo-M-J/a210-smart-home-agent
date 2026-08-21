# agent-butler

`agent-butler` is a board-side smart home butler demo. A local PC sends JPEG
frames and a room id over Ethernet. The board runs YOLO11 detection, starts
YOLO11-pose only for human presence in bedrooms or the bathroom, simulates
bracelet metrics, and emits structured events through a shell hook.

## Directory

```text
examples/agent-butler/
├── cpp/
│   ├── main.cc
│   ├── det_yolo11.cc/.h
│   ├── det_postprocess.cc/.h
│   ├── pose_yolo11.cc/.h
│   ├── pose_postprocess.cc/.h
│   └── CMakeLists.txt
├── model/
│   ├── bus.jpg
│   ├── coco_80_labels_list.txt
│   └── yolo11_pose_labels_list.txt
└── scripts/
    └── action_hook.sh
```

## Prepare Models

Generate or copy these two TORQ models into `examples/agent-butler/model/`:

```text
model/yolo11.torq
model/yolo11_pose.torq
```

You can reuse the existing examples:

```shell
cd examples/yolo11/model
./download_model.sh
cd ../python
python3 convert.py --model ../model/yolo11s_modified.onnx --target a210 --dtype u8 \
  --output_path ../../agent-butler/model/yolo11.torq

cd ../../yolo11_pose/model
./download_model.sh
cd ../python
python3 convert.py --model ../model/yolo11s_pose_modified.onnx --target a210 --dtype u8 \
  --output_path ../../agent-butler/model/yolo11_pose.torq
```

## Build

```shell
cd /home/public/ai/tools/torq-model-zoo
./build-linux.sh -t a210 -d agent-butler
```

The install directory is:

```text
install/a210_linux/torq_agent-butler_demo/
```

## Run On Board

```shell
cd torq_agent-butler_demo
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000 \
  --action-hook scripts/action_hook.sh
```

The demo listens on `0.0.0.0:9000`.

## PC Frame Protocol

Each frame is one JSON header line followed by JPEG bytes:

```json
{"room":"kitchen","frame_id":1,"timestamp_ms":123456789,"jpeg_bytes":12345}
```

Then send exactly `jpeg_bytes` bytes of JPEG data.

Valid rooms:

```text
living_room
bedroom1
bedroom2
kitchen
bathroom
```

Minimal PC sender:

```python
import json
import socket
import time

host = "192.168.0.23"
port = 9000
room = "kitchen"
image_path = "examples/agent-butler/model/bus.jpg"

with open(image_path, "rb") as f:
    jpeg = f.read()

with socket.create_connection((host, port)) as sock:
    for frame_id in range(1, 6):
        header = {
            "room": room,
            "frame_id": frame_id,
            "timestamp_ms": int(time.time() * 1000),
            "jpeg_bytes": len(jpeg),
        }
        sock.sendall(json.dumps(header).encode("utf-8") + b"\n")
        sock.sendall(jpeg)
        time.sleep(0.2)
```

## Rules

- `PET_IN_DANGER_ROOM`: `kitchen` sees `cat` or `dog`, no `person`, for 3
  consecutive frames.
- `FALL_DETECTED`: `bedroom1`, `bedroom2`, or `bathroom` sees `person`, pose
  inference looks like a fall for 3 consecutive frames.
- `HEALTH_ABNORMAL`: simulated bracelet metrics are abnormal twice in a row:
  `spo2 < 92`, `heart_rate > 120`, or `stress > 85`.
- The same event type in the same room is suppressed for 60 seconds.

Events are printed and passed to:

```shell
scripts/action_hook.sh '<event-json>'
```

Replace `scripts/action_hook.sh` to connect real phone, email, voice, light,
hot-water, music, MQTT, or HomeAssistant integrations.

## Team Work

For the cloud Agent teammate and virtual home simulator teammate, see:

```text
docs/TEAMMATE_README.md
```
