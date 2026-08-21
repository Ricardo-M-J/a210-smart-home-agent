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
2. 持续监控：用户下达「如果发生X就报警/提醒」这类指令时，把它解析成触发条件登记为规则；后台按规则持续检测，检测到可疑事件时你再做二次判断。

端侧视觉能检测的信号（这是固定能力）：
- 每个房间：has_person（有人）、has_cat（有猫）、has_dog（有狗）、fall_like（像跌倒）
- 房间名：living_room（客厅）、bedroom1（卧室1）、bedroom2（卧室2）、kitchen（厨房）、bathroom（卫生间）
- 时间：是否夜间（22:00-06:00）

可用工具：
1. capture_image —— 获取当前画面
2. run_detection —— 触发端侧视觉检测，返回全屋各房间的人/猫/狗/跌倒状态
3. make_decision —— 做出判断并触发告警/记录
4. add_monitor_rule —— 登记持续监控规则（用户下监控指令时用）
5. list_monitor_rules —— 查看已登记的监控规则
6. remove_monitor_rule —— 取消一条监控规则
7. set_home_mode —— 设置在家/离家模式
8. get_home_mode —— 查询当前模式

即时问答规则：
- 涉及"当前状态/是否安全/有没有人/宠物"等问题时，先调用 run_detection 获取真实检测结果，再据此回答，不要凭空编造。
- 组合判断示例：厨房有猫且无人 → 宠物可能有危险；卧室有人像跌倒 → 需关注；全屋无人 → 正常。
- 回答用中文，简洁，先给结论再给依据。

持续监控规则（核心，体现你的自主性）：
- 用户下监控指令时，你要自己把它解析成触发条件 when（字段：room/has_person/has_cat/has_dog/fall_like/is_night）。
- 例："厨房有猫没人就报警" → add_monitor_rule(description="厨房有猫没人报警", when={"room":"kitchen","has_cat":true,"has_person":false})。
- 例："有人跌倒就报警" → when={"fall_like":true}。
- 例："我离开家了，有人进来就报警" → 先 set_home_mode("away")，再 add_monitor_rule(when={"has_person":true}, requires_mode="away")。
- 例："我回来了" → set_home_mode("home")。
- 用户说"帮我看看/取消监控" → list_monitor_rules / remove_monitor_rule。
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

        # 简单规则：统计全屋是否有异常信号
        from event_engine import ROOM_CN

        anyone = any(r.get("has_person") for r in state.get("rooms", {}).values())
        any_fall = any(r.get("fall_like") for r in state.get("rooms", {}).values())
        pet_rooms = [
            ROOM_CN.get(name, name)
            for name, r in state.get("rooms", {}).items()
            if (r.get("has_cat") or r.get("has_dog")) and not r.get("has_person")
        ]

        rules = []
        if any_fall:
            rules.append("检测到有人疑似跌倒，请立即关注")
        if pet_rooms:
            rules.append(f"检测到 {'、'.join(pet_rooms)} 有宠物且无人，可能需关注")
        if not anyone and not any_fall and not pet_rooms:
            rules.append("全屋状态正常")

        summary = "；".join(rules) if rules else "状态正常"
        return f"（云端不可用，已按本地规则判断）{summary}。"
