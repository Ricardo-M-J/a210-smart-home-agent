"""命令行入口：用 Mock 快照跑通「采集→推理→决策→问答」闭环，含事件触发与记忆。

用法：
    python main.py                              # 交互式问答（默认场景）
    python main.py --scene night_nobody_on      # 指定场景后交互
    python main.py --scene night_lying --ask "老人现在状态怎么样？"   # 单次提问
    python main.py --list-scenes                # 列出所有 Mock 场景
    python main.py --watch --scene night_nobody_on   # 事件轮询：检测异常→决策→告警
    python main.py --history decisions          # 查看记忆（decisions/events/conversations）
"""
import argparse
import sys
import time

import config
from agent import Agent
from event_engine import EventEngine
from memory import Memory
from mock import SCENARIOS, DEFAULT_SCENE, write_scene
from tools.reader import read_home_state


def list_scenes() -> None:
    for name, snap in SCENARIOS.items():
        rooms = "、".join(r["room"] for r in snap["rooms"])
        print(f"  {name:<18} {snap['timestamp']}  房间: {rooms}")


def show_history(table: str) -> None:
    rows = Memory().query(table)
    if not rows:
        print(f"（{table} 暂无记录）")
        return
    for r in rows:
        if table == "decisions":
            print(f"[{r['time']}] {r['action']} | {r['conclusion']} | {r['message']}")
        elif table == "events":
            print(f"[{r['time']}] {r['severity']} | {r['event_type']} | {r['key']} | {r['summary']}")
        else:
            print(f"[{r['time']}] {r['role']}: {r['content']}")


def watch(scene: str, interval: float = 1.0) -> None:
    """事件轮询：反复读快照 → 事件引擎检测 → 触发 Agent 二次判断告警。"""
    engine = EventEngine()
    agent = Agent()
    print(f"[watch] 开始轮询场景 {scene}（Ctrl+C 停止），快照: {config.HOME_STATE_FILE}")
    print("[watch] 提示：需先用 add_monitor_rule 登记规则，或调用 --history rules 查看")
    try:
        while True:
            state = read_home_state()
            events = engine.detect(state)
            for ev in events:
                print(f"\n[疑似事件] {ev['summary']}（规则: {ev['rule_type']}）")
                result = agent.on_event(ev)
                print(f"[Agent] {result}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[watch] 已停止。")


def main() -> None:
    parser = argparse.ArgumentParser(description="A210 智能家居边缘视觉 Agent（本地 Mock 闭环）")
    parser.add_argument("--scene", default=DEFAULT_SCENE, help="Mock 场景名")
    parser.add_argument("--ask", default=None, help="单次提问；不传则进入交互模式")
    parser.add_argument("--list-scenes", action="store_true", help="列出所有场景")
    parser.add_argument("--watch", action="store_true", help="事件轮询模式")
    parser.add_argument("--history", choices=["decisions", "events", "conversations"], help="查看记忆历史")
    args = parser.parse_args()

    if args.list_scenes:
        list_scenes()
        return

    if args.history:
        show_history(args.history)
        return

    if args.scene not in SCENARIOS:
        print(f"未知场景: {args.scene}")
        print("可用场景：")
        list_scenes()
        sys.exit(1)

    # 模拟感知进程：把所选场景写入快照文件
    write_scene(args.scene)
    print(f"[场景] {args.scene}（快照已写入 {config.HOME_STATE_FILE}）")

    if not config.DASHSCOPE_API_KEY:
        print("[警告] 未配置 DASHSCOPE_API_KEY，将走本地规则降级")

    if args.watch:
        watch(args.scene)
        return

    agent = Agent()

    if args.ask:
        print(f"[你] {args.ask}")
        print(f"[Agent] {agent.ask(args.ask)}")
        return

    print("输入问题开始（Ctrl+C 或输入 /quit 退出）：")
    while True:
        try:
            q = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return
        if not q:
            continue
        if q in ("/quit", "/exit"):
            return
        print(f"Agent：{agent.ask(q)}")


if __name__ == "__main__":
    main()
