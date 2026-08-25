"""Command-line entry point for the A210 smart-home agent."""

from __future__ import annotations

import argparse
import sys
import time

import config
from agent import Agent
from event_engine import EventEngine
from memory import Memory
from tools.backend import get_backend
from tools.reader import read_home_state


def _mock_module():
    import mock as mock_module

    return mock_module


def list_scenes() -> None:
    backend_name = config.BACKEND.lower()
    if backend_name == "real":
        print("  (real backend has no local scenes)")
        return

    if backend_name == "mock":
        mock = _mock_module()
        for name, snap in mock.SCENARIOS.items():
            active = [room for room, signals in snap["rooms"].items() if any(signals.values())]
            print(f"  {name:<18} ts={snap.get('timestamp_ms', '?')}  active={', '.join(active) if active else '(empty)'}")
        return

    for name in get_backend().list_scenes():
        print(f"  {name}")


def show_history(table: str) -> None:
    rows = Memory().query(table)
    if not rows:
        print(f"({table} 暂无记录)")
        return
    for row in rows:
        if table == "decisions":
            print(f"[{row['time']}] {row['action']} | {row['conclusion']} | {row['message']}")
        elif table == "events":
            print(f"[{row['time']}] {row['severity']} | {row['event_type']} | {row['key']} | {row['summary']}")
        elif table == "rules":
            active = "启用" if row.get("active") else "停用"
            print(
                f"[{row['time']}] #{row['id']} {active} | "
                f"{row.get('description', '')} | when={row.get('when_json', '')} | {row.get('action', 'alert')}"
            )
        else:
            print(f"[{row['time']}] {row['role']}: {row['content']}")


def watch(scene: str, interval: float = 1.0) -> None:
    engine = EventEngine()
    agent = Agent()
    print(f"[watch] scene={scene} snapshot={config.HOME_STATE_FILE} (Ctrl+C to stop)")
    try:
        while True:
            state = read_home_state()
            for event in engine.detect(state):
                print(f"\n[event] {event['summary']} (rule={event['rule_description']})")
                print(f"[Agent] {agent.on_event(event)}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[watch] stopped")


def _run_virtualhome(args: argparse.Namespace) -> None:
    scene_was_set = "--scene" in sys.argv
    backend = get_backend()
    if scene_was_set and not backend.set_scene(args.scene):
        print(f"Unknown VirtualHome scene: {args.scene}")
        print("Available scenes:")
        list_scenes()
        sys.exit(1)

    active_frame = backend.latest_frame()
    active_scene = active_frame.get("scene")
    print(f"[VirtualHome] scene={active_scene} frame={active_frame.get('image_path')}")

    if not config.DASHSCOPE_API_KEY:
        print("[warning] DASHSCOPE_API_KEY is not configured; cloud LLM calls will degrade to local rules.")

    if args.watch:
        watch(active_scene)
        return

    _ask_loop(args)


def _run_mock(args: argparse.Namespace) -> None:
    mock = _mock_module()
    scene = args.scene or mock.DEFAULT_SCENE
    if scene not in mock.SCENARIOS:
        print(f"未知场景: {scene}")
        print("可用场景:")
        list_scenes()
        sys.exit(1)

    mock.write_scene(scene)
    print(f"[mock] scene={scene} snapshot={config.HOME_STATE_FILE}")

    if not config.DASHSCOPE_API_KEY:
        print("[warning] DASHSCOPE_API_KEY is not configured; cloud LLM calls will degrade to local rules.")

    if args.watch:
        watch(scene)
        return

    _ask_loop(args)


def _ask_loop(args: argparse.Namespace) -> None:
    agent = Agent()
    if args.ask:
        print(f"[User] {args.ask}")
        print(f"[Agent] {agent.ask(args.ask)}")
        return

    print("Enter a question. Use /quit or /exit to leave.")
    while True:
        try:
            question = input("User: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if not question:
            continue
        if question in ("/quit", "/exit"):
            return
        print(f"Agent: {agent.ask(question)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="A210 smart-home vision agent")
    parser.add_argument("--scene", default=None, help="local scene name")
    parser.add_argument("--ask", default=None, help="ask one question and exit")
    parser.add_argument("--list-scenes", action="store_true", help="list available local scenes")
    parser.add_argument("--watch", action="store_true", help="poll monitor rules")
    parser.add_argument("--history", choices=["decisions", "events", "conversations", "rules"], help="show memory table")
    args = parser.parse_args()

    if args.list_scenes:
        list_scenes()
        return

    if args.history:
        show_history(args.history)
        return

    backend_name = config.BACKEND.lower()
    if backend_name == "virtualhome":
        _run_virtualhome(args)
    elif backend_name == "real":
        _ask_loop(args)
    else:
        _run_mock(args)


if __name__ == "__main__":
    main()
