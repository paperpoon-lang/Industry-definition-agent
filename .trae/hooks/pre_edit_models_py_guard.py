#!/usr/bin/env python3
"""PreToolUse hook：修改 models.py 前用 ask 模式让用户确认是否已调用 architecture-critic。

设计：permissionDecision=ask + additionalContext 注入行为指导
来源：Trae 官方文档 https://docs.trae.cn/ide_hook-configuration-reference（2026-06-26）

字段待验证声明（fact-checker 建议）：
- tool_input.file_path 字段路径基于 Trae 与 Claude Code Hook 兼容性约定
  （官方文档显式声明支持读取 Claude Code Hook 配置），未在 Trae 官方文档
  显式列出 Edit/Write 工具的 tool_input 内部字段，待 IDE 实测确认
- exit 0 + 无 stdout 输出 等同于 allow 的默认行为，官方文档未显式说明，
  从 schema 推断（permissionDecision 缺省时默认 allow），待 IDE 实测确认
"""
import sys
import json


def _emit_ask(reason: str, additional_context: str = "") -> None:
    """统一输出 ask 决策（含异常路径复用）。"""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


def main():
    # PreToolUse 的 stdin 含：session_id, cwd, hook_event_name, tool_use_id, tool_name, llm_tool_name, tool_input
    # 异常处理策略（architecture-critic P0 级问题修正）：
    # 崩溃时默认 ask（保守），而非静默放行——避免 Hook bug 导致 models.py 修改无防护执行
    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
    except Exception as e:
        # JSON 解析失败或字段缺失：保守 ask，而非 data={} 静默放行
        _emit_ask(
            f"[Hook 异常] stdin 解析失败：{e}。出于安全考虑，仍需确认是否已调用 architecture-critic。",
            "规则提醒：Hook 脚本解析 stdin 异常，无法判断目标文件。请人工确认本次修改是否涉及 models.py，若涉及则需先调 architecture-critic。"
        )
        return

    # 检测是否在修改 models.py
    if "models.py" in file_path and file_path.endswith("models.py"):
        # 官方推荐方式：返回 hookSpecificOutput JSON
        # permissionDecision=ask：弹出确认框，由用户决定是否执行
        # additionalContext：给模型注入行为指导（比纯打印文字更有力）
        _emit_ask(
            "[规则 10.2] 即将修改 models.py。请确认是否已调用 architecture-critic 审查设计。\n"
            "  - 若已调用 → 点击允许继续\n"
            "  - 若未调用 → 点击拒绝，先完成审查再修改",
            "规则提醒：修改 models.py 前必须调用 architecture-critic 审查字段变更对 State 传递的影响。"
            "这是规则 10.2 的强制要求。如果本次修改是紧急修复且无法先审查，请在 detail 中说明理由。"
            "请在下一步回复中告知用户此确认已触发，避免静默放行。"
        )
        # exit 0 正常退出（hookSpecificOutput 会被 Trae 解析）
        return

    # 非 models.py 文件，正常放行（不输出 = allow，基于 permissionDecision 缺省推断，待 IDE 实测确认）


if __name__ == "__main__":
    main()
