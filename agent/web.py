"""Web 服务：Flask 封装 Agent，通过网口对外提供检测与问答接口。

路由：
    GET  /                前端页面
    GET  /api/state       当前家居状态快照
    GET  /api/alerts      事件告警列表
    POST /api/chat        问答（body: {"question": "..."}）
    GET  /api/scenes      所有 Mock 场景
    POST /api/scene       切换模拟场景（body: {"scene": "..."}）
    GET  /api/history/<table>  记忆查询（decisions/events/conversations）

监听 0.0.0.0，上板后通过网口 IP 访问，不改代码只改 .env。
"""
from flask import Flask, jsonify, render_template, request

import config
import runtime
from memory import Memory
from mock import SCENARIOS
from tools.reader import read_home_state

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    """当前家居状态快照（含时间、各房间对象）。"""
    return jsonify(read_home_state())


@app.get("/api/alerts")
def api_alerts():
    return jsonify(runtime.get_alerts())


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
    if config.BACKEND == "real":
        return jsonify([])
    return jsonify(list(SCENARIOS.keys()))


@app.post("/api/scene")
def api_scene():
    if config.BACKEND == "real":
        return jsonify({"error": "real 模式下无模拟感知进程，场景切换不可用"}), 400
    data = request.get_json(silent=True) or {}
    scene = (data.get("scene") or "").strip()
    sim = runtime.get_simulator()
    if not sim.set_scene(scene):
        return jsonify({"error": f"未知场景: {scene}", "scenes": list(SCENARIOS.keys())}), 400
    return jsonify({"scene": scene, "ok": True})


@app.get("/api/history/<table>")
def api_history(table: str):
    if table not in ("decisions", "events", "conversations", "rules"):
        return jsonify({"error": f"未知表: {table}"}), 400
    return jsonify(Memory().query(table))


@app.get("/api/rules")
def api_rules():
    """当前启用的监控规则。"""
    return jsonify(Memory().list_rules(active_only=True))


@app.post("/api/rules/remove")
def api_rules_remove():
    data = request.get_json(silent=True) or {}
    rule_id = data.get("rule_id")
    if rule_id is None:
        return jsonify({"error": "rule_id 不能为空"}), 400
    ok = Memory().disable_rule(int(rule_id))
    return jsonify({"ok": ok})


def main() -> None:
    # 按 BACKEND 装配运行时（mock 起模拟器+监控；real 只起监控）
    runtime.start()
    host = config.WEB_HOST
    port = config.WEB_PORT
    print(f"[web] 服务已启动：http://{host}:{port}  （后端: {config.BACKEND}，快照: {config.HOME_STATE_FILE}）")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
