"""v5.2 新增：TokenAudit — Token 持久化审计，生成单次运行成本报表。

v4 只在 Step 6 print 一行总 Token 数，不持久化。
v5 生成单次运行成本报表（JSON + Markdown），持久化到 logs/ 目录。
不改变 StepOutput 模型，只读取 token_usage 字段。

v5.1 修正（评议 Q3）：Token 统计从报告正文移除后，CLI 保留一行成本摘要 +
详细报表路径，避免用户需要打开文件才知道成本。

v5.2 P2-14：汇率从环境变量读取（os.getenv("USD_TO_CNY", "7.2")）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# DeepSeek-V4-Pro 定价（2026-08-20 更新来源为 DeepSeek 官方，★★★★★ [可信]）
# 来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing
PRICING = {
    "input_per_million": 3.0,   # ¥ / 1M tokens
    "output_per_million": 6.0,  # ¥ / 1M tokens
}


class TokenAudit:
    """v5 新增：Token 持久化审计，生成单次运行成本报表。

    不改变 StepOutput 模型，只读取 token_usage 字段。
    v5.1：trace_id 从外部注入（由 Orchestrator 统一生成）。
    v5.2 P2-14：汇率从环境变量读取。
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True, parents=True)

    def generate_report(
        self,
        state: Any,  # ReportState，避免循环导入用 Any
        trace_id: str,
        industry_name: str,
    ) -> dict[str, Any]:
        """生成成本报表，返回 dict 并持久化到 JSON + Markdown。

        Args:
            state: ReportState 对象
            trace_id: 由 Orchestrator 统一生成的 trace_id
            industry_name: 行业名

        Returns:
            报表 dict，含 summary 字段（total_cost_cny 等）
        """
        steps_data: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        total_tokens = 0

        for step in state.steps:
            if step.token_usage:
                pt = step.token_usage.get("prompt_tokens", 0)
                ct = step.token_usage.get("completion_tokens", 0)
                tt = step.token_usage.get("total_tokens", 0)
                total_input += pt
                total_output += ct
                total_tokens += tt
                steps_data.append({
                    "step_id": step.step_id,
                    "step_label": step.step_label,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "total_tokens": tt,
                })
            else:
                steps_data.append({
                    "step_id": step.step_id,
                    "step_label": step.step_label,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                })

        input_cost = total_input * PRICING["input_per_million"] / 1_000_000
        output_cost = total_output * PRICING["output_per_million"] / 1_000_000
        total_cost = input_cost + output_cost

        # v5.2 P2-14：汇率从环境变量读取
        usd_to_cny = float(os.getenv("USD_TO_CNY", "7.2"))

        report: dict[str, Any] = {
            "trace_id": trace_id,
            "industry": industry_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pricing_source": "DeepSeek-V4-Pro official (DeepSeek api-docs)",
            "steps": steps_data,
            "summary": {
                "total_prompt_tokens": total_input,
                "total_completion_tokens": total_output,
                "total_tokens": total_tokens,
                "input_cost_cny": round(input_cost, 4),
                "output_cost_cny": round(output_cost, 4),
                "total_cost_cny": round(total_cost, 4),
                "total_cost_usd": round(total_cost / usd_to_cny, 4),
            },
        }

        # 持久化 JSON
        json_path = self.log_dir / f"{trace_id}_token_audit.json"
        try:
            json_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (IOError, OSError) as e:
            print(f"[TokenAudit] JSON 报表写入失败: {e}")

        # 持久化 Markdown（人类可读）
        md_path = self.log_dir / f"{trace_id}_token_audit.md"
        try:
            md_path.write_text(self._to_markdown(report), encoding="utf-8")
        except (IOError, OSError) as e:
            print(f"[TokenAudit] Markdown 报表写入失败: {e}")

        return report

    def _to_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            f"# Token 审计报表 — {report['industry']}",
            "",
            f"- trace_id: `{report['trace_id']}`",
            f"- 时间: {report['timestamp']}",
            f"- 定价来源: {report['pricing_source']}",
            "",
            "## 步骤明细",
            "",
            "| 步骤 | prompt | completion | total |",
            "|------|--------|------------|-------|",
        ]
        for s in report["steps"]:
            if s["total_tokens"] is not None:
                lines.append(
                    f"| {s['step_label']} | {s['prompt_tokens']} | "
                    f"{s['completion_tokens']} | {s['total_tokens']} |"
                )
            else:
                lines.append(f"| {s['step_label']} | N/A | N/A | N/A |")

        summary = report["summary"]
        lines.extend([
            "",
            "## 汇总",
            "",
            f"- 总 Token: {summary['total_tokens']}",
            f"- 输入成本: ¥{summary['input_cost_cny']}",
            f"- 输出成本: ¥{summary['output_cost_cny']}",
            f"- **总成本: ¥{summary['total_cost_cny']} (≈ ${summary['total_cost_usd']})**",
        ])
        return "\n".join(lines)
