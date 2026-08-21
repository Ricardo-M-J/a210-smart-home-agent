"""Agent 核心：自写 function calling 循环，requests 直调通义千问（OpenAI 兼容端点）。

职责：
- 维护对话 messages（含记忆/多轮，超长自动截断）
- 循环：调 LLM → 若返回 tool_calls 则执行 Tool → 把结果回填 → 再调 LLM
- 对话持久化到 SQLite（conversations）
- 事件触发入口 on_event（异常事件 → 决策 → 告警）
- LLM 调用失败时降级到本地规则回答（稳定性底线）
"""
import json
import threading

import requests

import config
from memory import Memory
from tools import TOOL_DISPATCH, TOOL_SPECS

# 对话消息保留上限（不含 system），超出截断，防止上下文无限增长
MAX_MESSAGES = 20

SYSTEM_PROMPT = """你是部署在 A210 边缘开发板上的智能家居视觉 Agent。

你的工作分两类：
1. 即时问答：结合端侧视觉检测结果，回答用户关于家居状态的问题。
2. 持续监控：用户下达「如果发生X就报警/提醒」这类指令时，调用 add_monitor_rule 登记规则；后台会按规则持续检测，检测到可疑事件时你再做二次判断。

可用工具：
1. capture_image —— 获取当前画面
2. run_detection —— 触发端侧视觉检测，返回各房间的人/灯/宠物/家电状态
3. make_decision —— 做出判断并触发告警/记录
4. add_monitor_rule —— 登记持续监控规则（用户下监控指令时用）
5. list_monitor_rules —— 查看已登记的监控规则
6. remove_monitor_rule —— 取消一条监控规则
7. set_home_mode —— 设置在家/离家模式
8. get_home_mode —— 查询当前模式

即时问答规则：
- 涉及"当前状态/是否安全/有没有人/灯"等问题时，先调用 run_detection 获取真实检测结果，再据此回答，不要凭空编造。
- 组合判断示例：夜间无人但灯亮 → 可能忘关灯；有人呈 lying 躺姿 → 需关注是否跌倒；白天无人灯灭 → 正常。
- 回答用中文，简洁，先给结论再给依据。

持续监控规则：
- 用户说"我离开家了，有人进来就报警"→ 先调 set_home_mode("away")，再调 add_monitor_rule(rule_type="person_enter", ...)。
- 用户说"我回来了"→ 调 set_home_mode("home")，人员进入类规则自动解除武装。
- 用户说"帮我看看/取消监控"→ 调 list_monitor_rules / remove_monitor_rule。
- 判断出异常时，调用 make_decision 落地告警。
- 若检测结果返回 error（无数据），如实说明"暂无检测数据"并建议稍后重试，不要臆测。"""


class Agent:
    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None):
        self.model = model or config.DASHSCOPE_MODEL
        self.base_url = base_url or config.DASHSCOPE_BASE_URL
        self.api_key = api_key or config.DASHSCOPE_API_KEY
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.memory = Memory()
        self._lock = threading.Lock()

    def _chat(self, tools: list[dict] | None) -> dict:
        """调用云端大模型，返回 message 对象。"""
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": self.messages,
        }
        if tools:
            payload["tools"] = tools
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]

    def ask(self, question: str, max_steps: int = 6) -> str:
        """处理一次用户提问，返回最终回答。加锁保证多线程安全。"""
        with self._lock:
            answer, _ = self._process(question, max_steps)
            return answer

    def on_event(self, event: dict) -> str:
        """事件触发入口：疑似事件 → Agent 二次判断 → 决定是否告警。

        由事件引擎检测到「疑似事件」后调用。事件引擎只做初筛（确定性、免费），
        不判断要不要报警；本方法让 LLM 结合上下文做最终判断。
        若 LLM 不可用（断网），则保守告警——规则命中即报，宁可多报不漏报。
        """
        prompt = (
            f"后台检测到可疑事件：{event.get('summary')}。"
            f"（规则说明：{event.get('rule_description') or '无'}）"
            "请调用 run_detection 获取当前检测结果，结合时间、房间、姿态等上下文，"
            "判断这是否构成需要提醒/告警的异常。若确实异常，调用 make_decision 落地；"
            "若属正常情况（如深夜卧室休息），则说明无需告警即可。最后用一句话中文向我报告。"
        )
        with self._lock:
            answer, degraded = self._process(prompt, 6)
            if degraded:
                # 断网降级：保守告警（规则命中即报，保证不漏报）
                import runtime
                runtime.push_alert("warning", event.get("summary"), "（云端不可用，按规则保守告警）")
                answer = f"（云端不可用，已按规则保守告警）检测到：{event.get('summary')}。"
            return answer

    def _process(self, question: str, max_steps: int) -> tuple[str, bool]:
        """执行一次问答的核心流程，返回 (回答, 是否降级)。"""
        self.messages.append({"role": "user", "content": question})
        self.memory.log_conversation("user", question)

        degraded = False
        try:
            answer = self._run_loop(max_steps)
        except Exception as e:
            # 断网 / API 失败：降级到本地规则回答，不抛异常
            degraded = True
            answer = self._fallback(question, e)

        self.memory.log_conversation("assistant", answer)
        self._trim()
        return answer, degraded

    def _trim(self) -> None:
        """截断对话历史：保留 system + 最近 MAX_MESSAGES 条消息。"""
        system = [m for m in self.messages if m["role"] == "system"]
        rest = [m for m in self.messages if m["role"] != "system"]
        if len(rest) > MAX_MESSAGES:
            rest = rest[-MAX_MESSAGES:]
        self.messages = system + rest

    def _run_loop(self, max_steps: int) -> str:
        for _ in range(max_steps):
            message = self._chat(TOOL_SPECS)
            self.messages.append(message)

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                return message.get("content") or "（模型未返回内容）"

            # 执行每个 tool call，结果回填为 tool 消息
            for tc in tool_calls:
                call_id = tc["id"]
                name = tc["function"]["name"]
                args = json.loads(tc["function"].get("arguments") or "{}")
                result = self._dispatch(name, args)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)}
                )

        return "（超过最大调用轮次，未能完成）"

    @staticmethod
    def _dispatch(name: str, args: dict) -> dict:
        fn = TOOL_DISPATCH.get(name)
        if fn is None:
            return {"status": "error", "detail": f"未知工具: {name}"}
        try:
            return fn(**args)
        except TypeError as e:
            return {"status": "error", "detail": f"工具参数错误: {e}"}
        except Exception as e:  # 工具内部异常不向上抛
            return {"status": "error", "detail": str(e)}

    def _fallback(self, question: str, error: Exception) -> str:
        """本地规则降级：不依赖云端，用简单规则给确定性回答。"""
        from tools.reader import read_home_state

        state = read_home_state()
        if "error" in state:
            return "（云端不可用，已降级为本地规则）当前无法获取检测数据，请稍后重试。"

        # 简单规则：统计是否有人、是否有灯亮着
        anyone = False
        any_light_on = False
        lying = False
        for room in state.get("rooms", []):
            for obj in room.get("objects", []):
                if obj.get("category") == "person" and obj.get("count", 0) > 0:
                    anyone = True
                    if obj.get("pose") == "lying":
                        lying = True
                if obj.get("category") == "light" and obj.get("state") == "on":
                    any_light_on = True

        rules = []
        if not anyone and any_light_on:
            rules.append("检测到无人但仍有灯亮，可能忘关灯")
        if lying:
            rules.append("检测到有人呈躺卧姿态，建议关注")
        if not anyone and not any_light_on:
            rules.append("家中无人且灯已关闭，状态正常")
        if anyone and not any_light_on:
            rules.append("家中有人的状态正常")

        summary = "；".join(rules) if rules else "状态正常"
        return f"（云端不可用，已按本地规则判断）{summary}。"
