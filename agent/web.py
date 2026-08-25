"""Flask Web service for the A210 smart-home agent."""

from __future__ import annotations

import threading
import time

from flask import Flask, jsonify, render_template, request

import config
import runtime
from memory import Memory
from rooms import ROOM_CN, ROOMS
from tools.backend import get_backend
from tools.reader import read_home_state

app = Flask(__name__)

_ABNORMAL_NOTICE_COOLDOWN_SECONDS = 60.0
_abnormal_notice_lock = threading.Lock()
_recent_abnormal_notices: dict[str, float] = {}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    return jsonify(read_home_state())


@app.get("/api/alerts")
def api_alerts():
    return jsonify(runtime.get_alerts())


@app.get("/api/home-mode")
def api_home_mode():
    return jsonify({"mode": Memory().get_home_mode()})


@app.get("/api/llm/status")
def api_llm_status():
    return jsonify(runtime.get_agent().cloud_status())


@app.post("/api/home-mode")
def api_set_home_mode():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "").strip().lower()
    if mode not in {"home", "away"}:
        return jsonify({"error": "mode 只能是 home 或 away"}), 400
    Memory().set_home_mode(mode)
    return jsonify({"mode": mode, "ok": True})


@app.get("/api/notices")
def api_notices():
    try:
        since = int(request.args.get("since", "0"))
    except ValueError:
        since = 0
    return jsonify(runtime.get_notices(since=since))


@app.post("/api/chat")
def api_chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question 不能为空"}), 400
    answer = runtime.get_agent().ask(question)
    return jsonify({"answer": answer})


@app.get("/api/scenes")
def api_scenes():
    if config.BACKEND.lower() == "real":
        return jsonify([])
    return jsonify(get_backend().list_scenes())


@app.post("/api/scene")
def api_scene():
    backend_name = config.BACKEND.lower()
    if backend_name == "real":
        return jsonify({"error": "real 后端没有本地模拟场景可切换"}), 400

    data = request.get_json(silent=True) or {}
    scene = (data.get("scene") or "").strip()
    backend = get_backend()
    if not backend.set_scene(scene):
        return jsonify({"error": f"未知场景: {scene}", "scenes": backend.list_scenes()}), 400
    if backend_name == "mock":
        simulator = runtime.get_simulator()
        if simulator is not None and hasattr(simulator, "set_scene"):
            simulator.set_scene(scene)
    return jsonify({"scene": scene, "ok": True, "backend": backend_name})


@app.post("/api/virtualhome/frame")
def api_virtualhome_frame():
    """Receive a VirtualHome frame/external-result packet and return agent feedback."""
    if config.BACKEND.lower() != "virtualhome":
        return jsonify({"error": "BACKEND is not virtualhome"}), 400
    payload = request.get_json(silent=True) or {}
    response = get_backend().ingest_virtualhome_frame(payload)
    _log_virtualhome_sync(response)

    abnormal_event = _virtualhome_abnormal_event(response)
    if abnormal_event and _should_emit_abnormal_notice(abnormal_event):
        _emit_virtualhome_abnormal_notice(abnormal_event)
    return jsonify(response)


@app.get("/api/virtualhome/feedback")
def api_virtualhome_feedback():
    """Return recent feedback actions written for VirtualHome."""
    if config.BACKEND.lower() != "virtualhome":
        return jsonify([])
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    return jsonify(get_backend().latest_feedback(limit))


@app.get("/api/history/<table>")
def api_history(table: str):
    if table not in ("decisions", "events", "conversations", "rules"):
        return jsonify({"error": f"未知表: {table}"}), 400
    return jsonify(Memory().query(table))


@app.get("/api/rules")
def api_rules():
    return jsonify(Memory().list_rules(active_only=True))


@app.post("/api/rules/remove")
def api_rules_remove():
    data = request.get_json(silent=True) or {}
    rule_id = data.get("rule_id")
    if rule_id is None:
        return jsonify({"error": "rule_id 不能为空"}), 400
    ok = Memory().disable_rule(int(rule_id))
    return jsonify({"ok": ok})


def _log_virtualhome_sync(response: dict) -> None:
    line = _virtualhome_sync_line(response)
    if line:
        print(line, flush=True)


def _virtualhome_sync_line(response: dict) -> str:
    if response.get("status") != "ok":
        return f"[virtualhome-sync] status={response.get('status')} detail={response.get('detail') or response.get('error') or '-'}"

    scene = str(response.get("scene") or "VirtualHome")
    feedback = response.get("feedback_action") if isinstance(response.get("feedback_action"), dict) else {}
    action = feedback.get("action") or "none"
    target = feedback.get("target") or "-"
    value = feedback.get("value") or "-"
    state = response.get("home_state") if isinstance(response.get("home_state"), dict) else {}
    rooms = state.get("rooms") if isinstance(state.get("rooms"), dict) else {}
    virtualhome = state.get("virtualhome") if isinstance(state.get("virtualhome"), dict) else {}
    source = "live" if virtualhome.get("live") else "sample"

    room_parts = []
    for room in ROOMS:
        signals = rooms.get(room) if isinstance(rooms.get(room), dict) else {}
        room_parts.append(
            f"{ROOM_CN.get(room, room)}=人{_int_value(signals.get('person_count'))}/"
            f"猫{_int_value(signals.get('cat_count'))}/狗{_int_value(signals.get('dog_count'))}/"
            f"陌生人{_int_value(signals.get('unknown_person_count'))}"
        )

    return (
        f"[virtualhome-sync] scene={scene} source={source} "
        f"action={action} target={target} value={value} rooms: {'; '.join(room_parts)}"
    )


def _virtualhome_abnormal_event(response: dict) -> dict | None:
    if response.get("status") != "ok":
        return None

    scene = str(response.get("scene") or "VirtualHome")
    feedback = response.get("feedback_action") if isinstance(response.get("feedback_action"), dict) else {}
    state = response.get("home_state") if isinstance(response.get("home_state"), dict) else {}
    rooms = state.get("rooms") if isinstance(state.get("rooms"), dict) else {}
    virtualhome = state.get("virtualhome") if isinstance(state.get("virtualhome"), dict) else {}
    external = virtualhome.get("external_result") if isinstance(virtualhome.get("external_result"), dict) else {}

    events: list[dict] = []
    for room in ROOMS:
        signals = rooms.get(room)
        if not isinstance(signals, dict):
            continue
        events.extend(_room_abnormal_events(scene, room, signals))

    if not events:
        return None

    priority = {"hazard": 0, "unknown_person": 1, "fall_like": 2, "health_event": 3, "pet_unattended": 4}
    events.sort(key=lambda item: priority.get(str(item.get("type")), 99))
    primary = events[0]
    summary = "；".join(_describe_abnormal_event(item) for item in events)
    return {
        "schema": "a210.virtualhome_abnormal.v1",
        "scene": scene,
        "room": primary.get("room"),
        "room_label": primary.get("room_label"),
        "primary_type": primary.get("type"),
        "summary": summary,
        "signals": primary.get("signals") or {},
        "events": events,
        "external_result": external,
        "feedback_action": feedback,
    }


def _room_abnormal_events(scene: str, room: str, signals: dict) -> list[dict]:
    room_label = ROOM_CN.get(room, room)
    base = {"room": room, "room_label": room_label, "signals": signals}
    events: list[dict] = []
    home_mode = Memory().get_home_mode()

    if signals.get("hazard_detected"):
        events.append({**base, "type": "hazard", "value": signals.get("hazard_type") or "hazard_detected"})
    if home_mode == "away" and _security_intrusion_signal(scene, signals):
        events.append(
            {
                **base,
                "type": "unknown_person",
                "value": _int_value(signals.get("unknown_person_count")) or _int_value(signals.get("person_count")) or 1,
            }
        )
    if signals.get("fall_like"):
        events.append({**base, "type": "fall_like", "value": "fall_like_detected"})
    if signals.get("health_event"):
        events.append({**base, "type": "health_event", "value": "health_event_detected"})

    pet_count = _int_value(signals.get("pet_count"))
    if pet_count == 0:
        pet_count = _int_value(signals.get("cat_count")) + _int_value(signals.get("dog_count"))
    if pet_count > 0 and _int_value(signals.get("person_count")) == 0:
        events.append({**base, "type": "pet_unattended", "value": pet_count})
    return events


def _security_intrusion_signal(scene: str, signals: dict) -> bool:
    if signals.get("unknown_person") or _int_value(signals.get("unknown_person_count")) > 0:
        return True
    return scene == "away_mode_stranger" and _int_value(signals.get("person_count")) > 0


def _describe_abnormal_event(event: dict) -> str:
    room_label = str(event.get("room_label") or event.get("room") or "当前房间")
    kind = str(event.get("type") or "")
    signals = event.get("signals") if isinstance(event.get("signals"), dict) else {}
    if kind == "hazard":
        return f"{room_label}检测到{signals.get('hazard_type') or '危险信号'}"
    if kind == "unknown_person":
        count = _int_value(signals.get("unknown_person_count")) or _int_value(signals.get("person_count")) or 1
        return f"{room_label}检测到{count}名陌生人"
    if kind == "fall_like":
        return f"{room_label}检测到疑似跌倒"
    if kind == "health_event":
        return f"{room_label}检测到健康异常"
    if kind == "pet_unattended":
        cat_count = _int_value(signals.get("cat_count"))
        dog_count = _int_value(signals.get("dog_count"))
        pieces = []
        if cat_count:
            pieces.append(f"{cat_count}只猫")
        if dog_count:
            pieces.append(f"{dog_count}只狗")
        return f"{room_label}无人但有{'、'.join(pieces) or '宠物'}"
    return f"{room_label}检测到异常"


def _should_emit_abnormal_notice(event: dict) -> bool:
    now = time.time()
    key = _abnormal_notice_key(event)
    with _abnormal_notice_lock:
        for item_key, ts in list(_recent_abnormal_notices.items()):
            if now - ts > 300:
                _recent_abnormal_notices.pop(item_key, None)
        last_ts = _recent_abnormal_notices.get(key)
        if last_ts is not None and now - last_ts < _ABNORMAL_NOTICE_COOLDOWN_SECONDS:
            return False
        _recent_abnormal_notices[key] = now
        return True


def _abnormal_notice_key(event: dict) -> str:
    parts = []
    for item in event.get("events") or []:
        if not isinstance(item, dict):
            continue
        parts.append(f"{item.get('room')}:{item.get('type')}:{item.get('value')}")
    return f"{event.get('scene')}|" + "|".join(parts)


def _emit_virtualhome_abnormal_notice(event: dict) -> None:
    thread = threading.Thread(target=_push_virtualhome_abnormal_notice, args=(event,), daemon=True)
    thread.start()


def _push_virtualhome_abnormal_notice(event: dict) -> None:
    try:
        message = runtime.get_agent().on_virtualhome_abnormal(event)
    except Exception as exc:
        print(f"[virtualhome-alert] failed to generate LLM notice: {exc}", flush=True)
        message = f"{event.get('summary') or '检测到 VirtualHome 异常'}，请及时确认。"
    runtime.push_notice("virtualhome_abnormal", message, event)


def _int_value(value: object) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    runtime.start()
    host = config.WEB_HOST
    port = config.WEB_PORT
    print(f"[web] 服务已启动：http://{host}:{port}  （后端: {config.BACKEND}，快照: {config.HOME_STATE_FILE}）")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
