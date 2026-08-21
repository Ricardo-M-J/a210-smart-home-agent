# 上板部署说明（队友版）

> 这份文档给队友：拿到代码后，怎么在 A210 上编译板端 C++、部署 Agent、连上 UI。

---

## 0. 先了解两端的角色

| 端 | 语言 | 职责 | 输出/输入 |
|----|------|------|----------|
| 板端 `agent-butler` | C++ | 收帧 → YOLO 检测 → 写全屋快照 | 写 `/tmp/home_state.json` |
| 云端 Agent | Python | 读快照 → 规则判断 → 问答/告警 | 读 `/tmp/home_state.json`，监听 8000 |

两端通过 `/tmp/home_state.json` 文件解耦，各自独立进程。

---

## 1. 拉代码

```bash
git clone <仓库地址>
cd <项目目录>
```

---

## 2. 编译板端 C++（你负责的部分）

**先说重点**：我改了 `main.cc`，改动说明见 `yolo/agent-butler_K_copy_20260821/examples/agent-butler/docs/BOARD_CPP_CHANGES.md`。编译命令不变：

```bash
cd /home/public/ai/tools/torq-model-zoo
./build-linux.sh -t a210 -d agent-butler
```

产物在 `install/a210_linux/torq_agent-butler_demo/`。

> ⚠️ 如果编译报错，把报错贴回来，我来改（我本地没有 A210 编译环境）。

---

## 3. 启动板端程序

```bash
cd torq_agent-butler_demo
./torq_agent_butler_demo \
  --det-model model/yolo11.torq \
  --pose-model model/yolo11_pose.torq \
  --labels model/coco_80_labels_list.txt \
  --port 9000
```

**注意**：不要加 `--emit-events`，用默认的"只写快照"模式。

验证快照是否正常：

```bash
cat /tmp/home_state.json
# 应看到 {"timestamp_ms":..., "rooms":{五个房间...}}
```

---

## 4. 部署 Agent（Python）

### 4.1 配置 .env

Agent 代码在 `agent/` 目录。先配置环境变量：

```bash
cd agent
cp .env.example .env
```

编辑 `.env`，改这几项：

```bash
DASHSCOPE_API_KEY=你的_API_KEY          # 我单独私发给你
DASHSCOPE_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-flash
HOME_STATE_FILE=/tmp/home_state.json     # 改成这个，指向板端写的快照
BACKEND=real                              # 上板用 real
```

### 4.2 装依赖 + 启动

```bash
bash install.sh    # 建 venv + 装 requests/flask
bash run.sh        # 启动 web 服务（默认）
```

启动后应看到：

```
[web] 服务已启动：http://0.0.0.0:8000  （后端: real，快照: /tmp/home_state.json）
```

---

## 5. 连 UI

在**你的电脑**浏览器打开：

```
http://<板子的IP>:8000
```

（板子 IP 用 `ip addr` 或 `hostname -I` 查）

页面包含：聊天框（问答）、当前家居状态面板、事件告警列表。

---

## 6. 联调流程（完整跑一遍）

1. 板端程序跑着（步骤 3）
2. PC 发帧给板端（模拟摄像头）：
   ```bash
   python3 send_frame.py --host $BOARD_IP --room kitchen --image assets/kitchen/danger.jpg --repeat 5
   ```
3. 确认快照更新：`cat /tmp/home_state.json` 里 kitchen 的 `has_cat` 变成 true
4. Agent 服务跑着（步骤 4）
5. 电脑浏览器开 UI，问"现在家里安全吗"，或下指令"厨房有猫没人就报警"

---

## 7. 常见问题

| 问题 | 排查 |
|------|------|
| 板端编译报错 | 贴报错给我，多半是我改的 main.cc 有语法/头文件问题 |
| 快照文件不存在 | 板端程序没收到帧；确认 send_frame.py 的 host/port 对 |
| Agent 读不到快照 | 确认 .env 的 HOME_STATE_FILE 和板端写的路径一致（都是 /tmp/home_state.json） |
| 问答返回"暂无检测数据" | 确认 BACKEND=real 且快照文件有合法 JSON |
| Flask 装不上（riscv64） | 告诉我，可能降级成纯标准库 http.server |
| 调 LLM 失败 | 确认 API Key 填对、板子能上网 |
