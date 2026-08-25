"""Tool 统一注册表：供 Agent 循环按 function calling 名派发。

三类 Tool：
1. 端侧动作：capture_image / run_detection / make_decision（赛题要求的三个核心 Tool）
2. 监控规则：add_monitor_rule / list_monitor_rules / remove_monitor_rule（下指令持续监控）
"""
from tools import capture_image, make_decision, monitor_rules, run_detection, virtualhome_control

# function calling 的 tools 参数列表
TOOL_SPECS = [
    capture_image.TOOL_SPEC,
    run_detection.TOOL_SPEC,
    make_decision.TOOL_SPEC,
    virtualhome_control.TOOL_SPEC,
    *monitor_rules.RULE_SPECS,
]

# name -> run 函数
TOOL_DISPATCH = {
    "capture_image": capture_image.run,
    "run_detection": run_detection.run,
    "make_decision": make_decision.run,
    "control_virtualhome": virtualhome_control.run,
    "add_monitor_rule": monitor_rules.add_monitor_rule,
    "list_monitor_rules": monitor_rules.list_monitor_rules,
    "remove_monitor_rule": monitor_rules.remove_monitor_rule,
    "set_home_mode": monitor_rules.set_home_mode,
    "get_home_mode": monitor_rules.get_home_mode,
}
