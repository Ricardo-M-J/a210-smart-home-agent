"""Core function-calling loop for the smart-home agent."""

from __future__ import annotations

import json
import threading
import time

import requests

import config
from memory import Memory
from tools import TOOL_DISPATCH, TOOL_SPECS

MAX_MESSAGES = 20

SYSTEM_PROMPT = """你是部署在 A210 边缘开发板上的智能家居视觉 Agent。

当前项目已接入 VirtualHome。房间只有四个：
- living_room（客厅）
- bedroom（卧室）
- kitchen（厨房）
- bathroom（卫生间）

旧名称 bedroom1/bedroom2 只作为兼容输入，判断时都等同于 bedroom。

每个房间可能包含这些状态字段：
- person_count / cat_count / dog_count / pet_count：人、猫、狗、宠物数量
- unknown_person_count / known_resident_count：陌生人、已知住户数量
- has_person：有人
- has_cat：有猫
- has_dog：有狗
- fall_like：疑似跌倒/躺倒
- hazard_detected：烟雾、火灾等危险
- hazard_type：危险类型，例如 fire_smoke
- health_event：健康/可穿戴事件
- unknown_person：陌生人

你的工作：
1. 即时问答：涉及当前状态、安全、人、宠物、跌倒、烟雾、健康事件、陌生人的问题，必须先调用 run_detection。
2. 设备控制：用户要求打开/关闭灯光，或播放/停止/暂停音乐时，调用 control_virtualhome。
3. 持续监控：用户说“如果发生 X 就提醒/报警”时，把自然语言解析成 add_monitor_rule 的 when 条件。
4. 决策落地：判断需要动作时调用 make_decision。VirtualHome 后端会把动作写回反馈 JSONL。

可用工具：
- capture_image：获取当前虚拟/真实摄像头帧信息。
- run_detection：返回当前四房间结构化状态。
- control_virtualhome：控制 VirtualHome 房间灯光/全屋音乐；音乐统一使用 all_rooms，不按房间拆分。
- make_decision：写入决策并向环境反馈动作。
- add_monitor_rule/list_monitor_rules/remove_monitor_rule：管理监控规则。
- set_home_mode/get_home_mode：管理在家/离家模式。

回答要求：
- 用中文，先给结论再给依据。
- 语气自然一点，像日常家居助手；不要主动展开接口、工具、JSON 等实现细节。
- 不凭空编造摄像头内容。
- 检测结果不可用时，如实说明。
- 用户登记规则时，房间名只能使用 living_room/bedroom/kitchen/bathroom。
"""

ROOM_PATTERNS = (
    ("living_room", ("living_room", "living room", "客厅", "起居室")),
    ("bedroom", ("bedroom", "卧室", "房间", "睡房")),
    ("kitchen", ("kitchen", "厨房", "厨")),
    ("bathroom", ("bathroom", "卫生间", "洗手间", "浴室")),
    ("all_rooms", ("all_rooms", "全屋", "全部房间", "所有房间", "每个房间", "所有")),
)


class Agent:
    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None):
        self.model = model or config.DASHSCOPE_MODEL
        self.base_url = base_url or config.DASHSCOPE_BASE_URL
        self.api_key = api_key or config.DASHSCOPE_API_KEY
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.memory = Memory()
        self._lock = threading.Lock()

    def _request_chat(self, messages: list[dict], tools: list[dict] | None = None, timeout: float = 60) -> dict:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is empty")
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]

    def _chat(self, tools: list[dict] | None) -> dict:
        return self._request_chat(self.messages, tools=tools, timeout=60)

    def cloud_status(self) -> dict:
        """Probe the configured OpenAI-compatible cloud endpoint without exposing the API key."""
        status = {
            "configured": bool(self.api_key),
            "base_url": self.base_url,
            "model": self.model,
            "ok": False,
        }
        if not self.api_key:
            status["detail"] = "DASHSCOPE_API_KEY 未配置"
            return status

        started = time.time()
        try:
            message = self._request_chat(
                [{"role": "user", "content": "Reply exactly OK."}],
                tools=None,
                timeout=20,
            )
            content = (message.get("content") or "").strip()
            status.update(
                {
                    "ok": True,
                    "latency_ms": int((time.time() - started) * 1000),
                    "response_has_content": bool(content),
                    "response_preview": content[:40],
                    "response_fields": sorted(message.keys()),
                }
            )
        except requests.HTTPError as exc:
            body = ""
            if exc.response is not None:
                body = (exc.response.text or "")[:600]
                status["http_status"] = exc.response.status_code
            status.update({"detail": self._sanitize_cloud_error(f"{exc}; {body}")})
        except Exception as exc:
            status.update({"detail": self._sanitize_cloud_error(str(exc))})
        return status

    def ask(self, question: str, max_steps: int = 6) -> str:
        with self._lock:
            local_answer = self._try_local_virtualhome_control(question)
            if local_answer:
                self.memory.log_conversation("user", question)
                self.memory.log_conversation("assistant", local_answer)
                return local_answer
            answer, _ = self._process(question, max_steps)
            return answer

    def on_event(self, event: dict) -> str:
        prompt = (
            f"后台检测到可疑事件：{event.get('summary')}。"
            f"规则说明：{event.get('rule_description') or '无'}。"
            "请调用 run_detection 获取当前检测结果，结合房间、时间和姿态/安全信号判断是否需要提醒或告警；"
            "若确实异常，请调用 make_decision。最后用一句中文报告。"
        )
        with self._lock:
            answer, degraded = self._process(prompt, 6)
            if degraded:
                import runtime

                runtime.push_alert("warning", event.get("summary"), "云端不可用，已按规则保守告警。")
                answer = f"云端不可用，已按规则保守告警：{event.get('summary')}。"
            return answer

    def on_virtualhome_abnormal(self, event: dict) -> str:
        prompt = self._virtualhome_notice_prompt(event)
        with self._lock:
            self.messages.append({"role": "user", "content": prompt})
            self.memory.log_conversation("virtualhome_event", event.get("summary") or prompt)
            try:
                message = self._chat(None)
                answer = (message.get("content") or "").strip()
                if not answer:
                    raise RuntimeError("模型未返回内容")
                self.messages.append(message)
            except Exception:
                answer = self._fallback_virtualhome_abnormal(event)
                self.messages.append({"role": "assistant", "content": answer})

            answer = " ".join(answer.split())
            self.memory.log_conversation("assistant", answer)
            self._trim()
            return answer

    @staticmethod
    def _virtualhome_notice_prompt(event: dict) -> str:
        if event.get("primary_type") == "health_event":
            return (
                "VirtualHome 健康助手检测到情绪或生理状态异常。请根据事件里的 event/payload "
                "判断更像焦虑、紧张、心率升高还是其他状态，并只输出一段中文建议。"
                "建议要像情绪健康助手：具体、温和、可执行；可以包含呼吸、音乐、坐下休息、补水等步骤；"
                "不要说“某人去看看吧”，不要只说报警，不要输出 JSON，不要解释接口。"
                f"\n健康事件：{json.dumps(event, ensure_ascii=False)}"
            )
        return (
            "VirtualHome 实时场景出现异常。请只输出一句中文主动提醒，语气自然、简短一点，像日常家居助手；"
            "提醒里带上房间、检测到的活物数量或异常类型，以及一个直接建议。"
            "不要调用工具，不要输出 JSON，不要描述普通同步过程。"
            f"\n异常事件：{json.dumps(event, ensure_ascii=False)}"
        )

    def _process(self, question: str, max_steps: int) -> tuple[str, bool]:
        self.messages.append({"role": "user", "content": question})
        self.memory.log_conversation("user", question)

        degraded = False
        try:
            answer = self._run_loop(max_steps)
        except Exception as exc:
            print(f"[cloud-llm] request failed: {self._sanitize_cloud_error(str(exc))}", flush=True)
            degraded = True
            answer = self._fallback(question, exc)

        self.memory.log_conversation("assistant", answer)
        self._trim()
        return answer, degraded

    def _trim(self) -> None:
        system = [message for message in self.messages if message["role"] == "system"]
        rest = [message for message in self.messages if message["role"] != "system"]
        if len(rest) > MAX_MESSAGES:
            rest = rest[-MAX_MESSAGES:]
        self.messages = system + rest

    def _run_loop(self, max_steps: int) -> str:
        for _ in range(max_steps):
            message = self._chat(TOOL_SPECS)
            self.messages.append(message)

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                return message.get("content") or "模型未返回内容。"

            for tool_call in tool_calls:
                call_id = tool_call["id"]
                name = tool_call["function"]["name"]
                args = json.loads(tool_call["function"].get("arguments") or "{}")
                result = self._dispatch(name, args)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)}
                )

        return "超过最大工具调用轮次，未能完成。"

    @staticmethod
    def _dispatch(name: str, args: dict) -> dict:
        fn = TOOL_DISPATCH.get(name)
        if fn is None:
            return {"status": "error", "detail": f"未知工具: {name}"}
        try:
            return fn(**args)
        except TypeError as exc:
            return {"status": "error", "detail": f"工具参数错误: {exc}"}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    def _try_local_virtualhome_control(self, question: str) -> str | None:
        intent = self._parse_control_intent(question)
        if not intent:
            return None
        result = self._dispatch("control_virtualhome", intent)
        if result.get("status") != "ok":
            return f"我想执行这个控制，但失败了：{result.get('detail') or result}"
        return result.get("message") or "已把控制指令发送给 VirtualHome。"

    @staticmethod
    def _parse_control_intent(text: str) -> dict | None:
        raw = (text or "").strip()
        if not raw:
            return None
        normalized = raw.lower().replace(" ", "")

        room = None
        for room_name, aliases in ROOM_PATTERNS:
            if any(alias.lower().replace(" ", "") in normalized for alias in aliases):
                room = room_name
                break
        wants_light = any(token in normalized for token in ("灯", "灯光", "light"))
        music_command_like = any(token in normalized for token in ("播放", "放歌", "来首", "听歌", "play"))
        wants_music = any(token in normalized for token in ("音乐", "音箱", "喇叭", "歌曲", "曲目", "歌", "speaker", "music", "song"))
        wants_music = wants_music or (music_command_like and not wants_light)
        if room is None and not wants_music:
            return None

        if wants_light:
            if room is None:
                return None
            device = "light"
            if any(token in normalized for token in ("打开", "开启", "开灯", "亮灯", "turnon", "on")):
                command = "on"
            elif any(token in normalized for token in ("关闭", "关掉", "关灯", "灭灯", "turnoff", "off")):
                command = "off"
            else:
                return None
        elif wants_music:
            room = "all_rooms"
            device = "speaker"
            if any(token in normalized for token in ("播放", "开始", "打开", "放歌", "play", "on")):
                command = "play"
            elif any(token in normalized for token in ("暂停", "pause")):
                command = "pause"
            elif any(token in normalized for token in ("停止", "关闭", "关掉", "stop", "off")):
                command = "stop"
            else:
                return None
        else:
            return None

        return {
            "room": room,
            "device": device,
            "command": command,
            "value": "",
            "source_text": raw,
        }

    def _fallback(self, question: str, error: Exception) -> str:
        from event_engine import ROOM_CN
        from tools.reader import read_home_state

        state = read_home_state()
        if "error" in state:
            return "云端不可用，且当前无法获取检测数据，请稍后重试。"

        rooms = state.get("rooms", {})
        any_fall = any(room.get("fall_like") for room in rooms.values())
        any_hazard = any(room.get("hazard_detected") for room in rooms.values())
        any_health = any(room.get("health_event") for room in rooms.values())
        home_mode = Memory().get_home_mode()
        any_unknown = home_mode == "away" and any(room.get("unknown_person") for room in rooms.values())
        pet_rooms = [
            ROOM_CN.get(name, name)
            for name, room in rooms.items()
            if (room.get("has_cat") or room.get("has_dog")) and not room.get("has_person")
        ]

        rules: list[str] = []
        if any_hazard:
            rules.append("检测到烟雾/火灾等危险信号，请立即关注")
        if any_unknown:
            rules.append("离家/安防场景中检测到陌生人，请立即确认")
        if any_health:
            rules.append("检测到健康事件，建议启动健康辅助或联系家人")
        if any_fall:
            rules.append("检测到有人疑似跌倒，请立即关注")
        if pet_rooms:
            rules.append(f"检测到 {'、'.join(pet_rooms)} 有宠物且无人，可能需要关注")
        if not rules:
            rules.append("当前四房间状态未发现明显异常")

        summary = "；".join(rules)
        return f"云端不可用，已按本地规则判断：{summary}。"

    @staticmethod
    def _sanitize_cloud_error(message: str) -> str:
        api_key = config.DASHSCOPE_API_KEY
        text = str(message or "")
        if api_key:
            text = text.replace(api_key, "[redacted]")
        return " ".join(text.split())

    @staticmethod
    def _fallback_virtualhome_abnormal(event: dict) -> str:
        room = str(event.get("room_label") or event.get("room") or "当前房间")
        kind = str(event.get("primary_type") or "")
        signals = event.get("signals") if isinstance(event.get("signals"), dict) else {}
        person_count = Agent._safe_count(signals.get("person_count"))
        cat_count = Agent._safe_count(signals.get("cat_count"))
        dog_count = Agent._safe_count(signals.get("dog_count"))
        unknown_count = Agent._safe_count(signals.get("unknown_person_count"))
        hazard_type = signals.get("hazard_type") or "危险信号"
        external = event.get("external_result") if isinstance(event.get("external_result"), dict) else {}
        payload = external.get("payload") if isinstance(external.get("payload"), dict) else {}

        if kind == "hazard":
            return f"{room}有{hazard_type}信号，先别靠近，我建议马上确认并准备报警。"
        if kind == "unknown_person":
            return f"离家模式看到{unknown_count or person_count or 1}名陌生人，先看一下门锁和监控。"
        if kind == "health_event":
            heart_rate = Agent._safe_count(payload.get("heart_rate"))
            anxiety_score = payload.get("anxiety_score")
            detail = f"心率约{heart_rate}次/分钟" if heart_rate else "状态有些紧张"
            if anxiety_score not in (None, ""):
                detail += f"，焦虑评分{anxiety_score}"
            return f"{room}检测到{detail}。先坐下，跟着 4-7-8 呼吸做三轮，再播放舒缓音乐；如果胸闷或不适持续，就及时联系医生。"
        if kind == "fall_like":
            return f"{room}有人像是跌倒了，最好马上过去看一下。"
        if kind == "pet_unattended":
            pet_text = []
            if cat_count:
                pet_text.append(f"{cat_count}只猫")
            if dog_count:
                pet_text.append(f"{dog_count}只狗")
            pets = "、".join(pet_text) or "宠物"
            return f"{room}现在没人，但有{pets}在里面，我会先提醒你留意一下。"
        return str(event.get("summary") or "检测到 VirtualHome 异常，请及时确认。")

    @staticmethod
    def _safe_count(value: object) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError):
            return 0
