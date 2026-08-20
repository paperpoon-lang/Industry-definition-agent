# 架构设计 — Agent 架构 v5.2（阶段二 A 组：基础设施加固 + 搜索补搜循环）

> 版本：v5.2 | 日期：2026-06-18 | 给 Trae 的开发 Spec
>
> v5.2 基于 v5.1 迭代，新增 Step 1 搜索补搜循环（用户需求）。
>
> **v5.0 变更摘要**（原始）：
> - **`quality_flags` 机制**：Pydantic 模型约束，跨步骤异常传递，Step 6 汇总到报告尾部
> - **Session Event Log → JSONL**：从 print 升级到 JSONL，append-only，支持查询接口，每个事件加 `trace_id`
> - **Token Audit → 持久化**：生成单次运行成本报表（JSON + Markdown），不改变 `StepOutput` 模型
> - **Checkpoint → 多版本 + 过期清理**：每次 save 创建新版本文件，自动保留 7 天，文件命名考虑 `request_id` 扩展性
> - **Output Safety（输出安全）**：时间戳使用 UTC + 时区标注，检测到已存在时追加版本号
> - **methodology/ → 简化拆分**：拆成 2-3 模块 + `_meta.yaml` 版本声明，拆分后验证正则切片不丢章节
> - **Step 5 `fixes_required` 设计笔记**：为阶段三 Evaluator-Optimizer 闭环预留接口（只留设计，不实现 Pydantic 模型）
>
> **v5.1 变更摘要**（整合两轮评议修正）：
> - **Checkpoint 清理改用文件内 `saved_at` 字段**（P0）：消除文件名字符串解析的碰撞风险
> - **`load_version` 的 `step_id` 改为必填**（P0）：避免 glob 返回随机匹配
> - **补充 v4→v5 增量集成指引**（P0）：明确实现方式是新增模块 + 修改导入/调用点，非重写
> - **`fromisoformat` 跨版本兼容**（P0）：Python 3.9 不支持 `Z` 后缀，用 `.replace("Z", "+00:00")`
> - **`load()` 处理 v4 遗留格式**（P0）：v4 checkpoint 是纯 ReportState，v5 是包装格式，需兼容
> - **损坏文件分层清理**（P1）：JSONDecodeError 直接删除，其他解析问题保留并记录
> - **quality_flags severity 默认映射表**（P1）：为每个 category 给出默认 severity
> - **`or_fallback` 拆分为字段级 category**（P1）：`or_fallback_result`（high）/ `or_fallback_reasoning`（medium）
> - **报告尾部统一**（P1）：Token 统计移出报告正文，CLI 保留成本摘要
> - **trace_id 由 Orchestrator 统一生成**（P1）：消除 SessionEventLog 和 TokenAudit 的隐式依赖
> - **fixes_required 补充 4 条循环规则**（P1）：循环计数、severity 阈值、合并规则、未收敛停止
> - **methodology 版本迁移简化策略**（P2）：不支持运行时切换，手动替换，`_meta.yaml` 与 fallback 一致性检查
> - **代码行数估计修正**（P2）：~1,100 行 → ~1,900 行（v4 实际 ~1,585 + v5 新增 ~340）
> - **验收标准补充测试构造方法**（P2）
> - **修正 `call_with_timeout` 的 B 组表述**（P1）：明确不属于 A 组
> - **OutputSafety 时区标注补充用途说明**（P3）：用途是可读性，非防碰撞
>
> **v5.2 变更摘要**（新增搜索补搜循环）：
> - **Step 1 搜索补搜循环**：首轮 3 个静态模板搜索 → FM 审查搜索结果 → 若有信息缺口则补搜，最多 2 轮，总共 ≤5 个 query。不改 search.py 接口，不改管线架构
> - **FM 审查标准**：基于方法论"信息优先级"章节，判断搜索结果是否覆盖关键维度，不自由判断
> - **quality_flags 新增 category**：`data_gaps_remaining`（补搜后仍有缺口，severity: medium）
> - **Step 1 timeout 调整**：120s → 180s（工程需要，非考核要求——阶段二退出条件无耗时考核）
>
> **v5 继承 v4 的设计立场**：质量组件不减（Independent Evaluator、Context Builder 四层、搜索并行压缩保持完整），基础设施从打桩升级到可用。
>
> **v5 不做的（明确推迟）**：
> - B 组（Persistent Memory SQLite；`call_with_timeout` 在阶段一收尾已完成，不属于阶段二 A 组工作范围）
> - C 组（Web UI、Sprint Contract——v3 已移除）
> - D 组（Model Router、Prompt Cache、API Server、Rate Limiter、Evaluator-Optimizer 闭环、Harness Ablation、Circuit Breaker 完整版、Cost Guard、Checkpoint 按请求隔离）
>
> **运行环境**：Python 3.9.6（阶段一收尾已确认，`from __future__ import annotations` 处理类型注解兼容性）

---

## 一、总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Orchestrator                                 │
│                      (frost_agent.py)                                │
│                                                                     │
│   生成 trace_id → 初始化 v5 组件（注入 trace_id）                      │
│   → 六步管线 → Step 5 结果判断                                        │
│   → 注入警告（若 fail）→ 输出报告（含 quality_flags 汇总）             │
│   → CLI 打印 Token 成本摘要 + 详细报表路径                             │
│                                                                     │
│   每步：Context Builder 四层组装 → LLM 调用（带超时）                  │
│        → 结果校验 → 记录 quality_flags（若有降级）→ 写 Checkpoint      │
│        → 写 Session Event Log（JSONL，带 trace_id）                   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     ▼                     ▼                      ▼
┌──────────┐         ┌──────────┐          ┌──────────┐
│  Step 1  │         │  Step 2  │   …      │  Step 6  │
│ 信息收集  │         │ 维度筛选  │          │   输出    │
│ (搜索并行)│         │          │          │+ 警告标记  │
│          │         │          │          │+ quality_ │
│          │         │          │          │  flags    │
└──────────┘         └──────────┘          └──────────┘
     │                     │                     │
     └─────────────────────┼─────────────────────┘
                           ▼
              ┌──────────────────────────┐
              │   Independent            │
              │   Evaluator              │
              │   (Step 5, 独立 LLM)      │
              └──────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         Harness 控制面                                │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ call_with_   │  │ SessionEvent │  │ CheckpointManager        │  │
│  │ timeout      │  │ Log (JSONL)  │  │ (多版本 + 过期清理)        │  │
│  │ (阶段一收尾,  │  │ + trace_id   │  │ + 文件内 saved_at         │  │
│  │  非 A 组)     │  │ (注入式)      │  │ + request_id 扩展性       │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ TokenAudit   │  │ OutputSafety │  │ quality_flags            │  │
│  │ (持久化报表)  │  │ (UTC时间戳+  │  │ (Pydantic 模型约束)       │  │
│  │ + CLI 摘要    │  │  版本号)      │  │ + severity 默认映射       │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      Environment 执行边界                              │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐                                  │
│  │ Credential   │  │ methodology/ │                                  │
│  │ Vault (.env) │  │ (拆分模块 +   │                                  │
│  │              │  │  _meta.yaml) │                                  │
│  └──────────────┘  └──────────────┘                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、v5 新增/升级组件（7 项）

### 2.1 `quality_flags` 机制（Pydantic 模型约束 + severity 默认映射）

**痛点**：v4 的 `or` fallback 防止了崩溃，但让降级信息"消失在状态对象的一个字段里"。例如 Step 1 搜索 3 个 query 只有 2 个成功，`or` fallback 让流程继续，但这个降级信息没有显式记录。

**v5 设计**：用 Pydantic 模型约束格式（v3.1 修正：v2.5 的字符串约定 `"{category}:{field}:{severity}"` 有格式漂移风险）。

**v5.1 修正**（评议 Q4）：`or_fallback` 拆分为字段级 category，避免 high 严重度泛滥。补充 severity 默认映射表。

```python
# models.py — 新增 QualityFlag 模型

class QualityFlag(BaseModel):
    """跨步骤异常传递的标准化格式（v5 新增，v5.1 修正 category 拆分）。

    v3.1 修正：用 Pydantic 模型约束，而非 v2.5 的字符串约定。
    v5.1 修正：or_fallback 拆分为 or_fallback_result / or_fallback_reasoning，
              避免 high 严重度泛滥（or 兜底是高频行为）。
    """

    category: str = Field(
        ...,
        description=(
            "降级类别。预定义值："
            "'llm_empty_field'（LLM 返回空字段）、"
            "'search_partial_failure'（搜索部分失败）、"
            "'json_parse_fallback'（JSON 解析失败降级）、"
            "'or_fallback_result'（result 字段被占位符替代，v5.1 拆分）、"
            "'or_fallback_reasoning'（reasoning 字段被占位符替代，v5.1 拆分）、"
            "'timeout_retry'（超时后重试成功）。"
            "允许扩展，但新增类别需在文档中登记。"
        ),
    )
    field: str = Field(
        ...,
        description="受影响的字段名，如 'summary'、'2/3'（2 个成功 3 个失败）、'official_definitions'。",
    )
    severity: Literal["high", "medium", "low"] = Field(
        ...,
        description="严重程度。high=影响报告质量，medium=有降级但质量可接受，low=仅记录。",
    )
    detail: str = Field(
        default="",
        description="可选的详细说明，如 'Tavily API 限流，query 3 失败'。",
    )


class StepOutput(BaseModel):
    # ... v4 现有字段保持不变 ...
    quality_flags: list[QualityFlag] = Field(
        default_factory=list,
        description="v5 新增：该步骤产生的降级标记列表。空列表表示无降级。",
    )
```

**severity 默认映射表**（v5.1 新增，评议 Q4）：

| category | 默认 severity | 判定规则 |
|----------|--------------|----------|
| `llm_empty_field` | medium | 字段为空，但其他字段可能足够 |
| `search_partial_failure` | 按失败比例 | 1/3 失败→medium；2/3 失败→high；全部失败→high |
| `json_parse_fallback` | medium | 解析方式降级（正则提取 vs JSON 解析），数据完整性可能受损 |
| `or_fallback_result` | **high** | result 字段（核心数据）被占位符替代，属于数据污染 |
| `or_fallback_reasoning` | **medium** | reasoning 字段（元数据）被占位符替代，不影响报告正文 |
| `timeout_retry` | low | 超时后重试成功，无质量影响 |

**规则**：允许实现者根据上下文调整 severity，但必须在 `detail` 中说明理由。

**Step 6 汇总逻辑**（v5.1 修正：Token 统计移出报告正文，评议 Q3）：

```python
# frost_agent.py — Step 6 输出时汇总 quality_flags

def _build_quality_flags_summary(state: ReportState) -> str:
    """汇总所有步骤的 quality_flags 到报告尾部。

    v5.1 修正（评议 Q3）：报告尾部只保留自检警告 + quality_flags 汇总 + 方法论附注。
    Token 统计移到独立的 TokenAudit 报表，不在报告正文中显示。
    """
    all_flags = []
    for step in state.steps:
        all_flags.extend(step.quality_flags)

    if not all_flags:
        return ""

    lines = ["\n\n---\n\n## ⚠️ 降级记录（quality_flags）\n"]
    high_flags = [f for f in all_flags if f.severity == "high"]
    medium_flags = [f for f in all_flags if f.severity == "medium"]
    low_flags = [f for f in all_flags if f.severity == "low"]

    if high_flags:
        lines.append("### 高严重度（影响报告质量，建议人工复核）\n")
        for f in high_flags:
            lines.append(f"- [{f.category}] {f.field}: {f.detail}")
    if medium_flags:
        lines.append("\n### 中严重度（有降级但质量可接受）\n")
        for f in medium_flags:
            lines.append(f"- [{f.category}] {f.field}: {f.detail}")
    if low_flags:
        lines.append("\n### 低严重度（仅记录）\n")
        for f in low_flags:
            lines.append(f"- [{f.category}] {f.field}: {f.detail}")

    return "\n".join(lines)
```

**报告尾部结构**（v5.1 明确优先级，评议 Q3）：

```markdown
[报告正文]

---

## ⚠️ 自检未通过（如有，最高优先级）

以下维度未通过审查：C2, C4

---

## ⚠️ 降级记录（quality_flags，如有，次高优先级）

### 高严重度
- [or_fallback_result] summary: LLM 未返回摘要，已用占位符替代

---

## 方法论附注（R5 强制要求，最后）

本报告遵循行业定义方法论 v2...
```

**关键设计约束**：
- 写入 `StepOutput.quality_flags` 独立字段（不污染 `result`）
- Step 6 汇总到报告尾部，按严重度分组
- `category` 预定义值可扩展，但新增类别需在文档中登记
- Token 统计不在报告正文中显示，移到独立审计文件（v5.1）

---

### 2.2 Session Event Log → JSONL（带 trace_id，注入式）

**痛点**：v4 的 `SimpleLogger` 只 print 到 stdout，调试只能 grep 终端输出，无法跨会话查询。

**v5 设计**：升级到 JSONL 文件，append-only，支持查询接口，每个事件加 `trace_id`（借鉴业界分布式追踪）。

**v5.1 修正**（评议 Q5）：`trace_id` 由 Orchestrator 统一生成并注入，消除 SessionEventLog 和 TokenAudit 的隐式依赖。`__init__` 的目录创建增加降级处理。

```python
# harness/session_log.py (~80 行，v5 升级，v5.1 修正 trace_id 注入)

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class SessionEventLog:
    """v5 升级：JSONL 持久化日志，带 trace_id。

    v5.1 修正（评议 Q5）：
    - trace_id 从外部注入（由 Orchestrator 统一生成），不再自己生成
    - __init__ 的目录创建增加降级处理，磁盘满时不崩溃

    签名兼容 v4 的 SimpleLogger.log()，但内部实现完全替换。
    v3.1 关键约束：
    - 日志写入失败不应导致主流程崩溃，需 try/except 包裹并降级到 print
    - 每个事件加 trace_id 字段，串联同一次运行的所有日志
    """

    def __init__(self, industry_name: str, trace_id: str, log_dir: str = "logs"):
        """v5.1 修正：trace_id 从外部注入。

        Args:
            industry_name: 行业名
            trace_id: 由 Orchestrator 统一生成的 trace_id
            log_dir: 日志目录
        """
        self.industry = industry_name
        self.trace_id = trace_id  # v5.1：从外部注入
        self.log_dir = Path(log_dir)
        try:
            self.log_dir.mkdir(exist_ok=True)
            self.log_path = self.log_dir / f"{self.trace_id}.jsonl"
        except (IOError, OSError) as e:
            # v5.1 修正：目录创建失败也降级，不崩溃
            print(f"[日志目录创建失败，降级到 print-only 模式] {e}")
            self.log_path = None  # 标记为 print-only

    def log(self, event_type: str, data: dict):
        """签名兼容 v4 SimpleLogger.log()。

        v3.1 约束：日志写入失败降级到 print，不抛异常。
        """
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id,
            "industry": self.industry,
            "event_type": event_type,
            "data": data,
        }
        line = json.dumps(event, ensure_ascii=False)

        # v5.1：log_path 为 None 时只 print
        if self.log_path is None:
            print(line)
            return

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except (IOError, OSError) as e:
            # v3.1 约束：降级到 print，不抛异常
            print(f"[日志写入失败，降级到 print] {e}")
            print(line)

    def query(
        self,
        event_type: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> list[dict]:
        """v5 新增：按 event_type / step_id 过滤查询。"""
        results = []
        if self.log_path is None or not self.log_path.exists():
            return results
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                event = json.loads(line)
                if event_type and event.get("event_type") != event_type:
                    continue
                if step_id and event.get("data", {}).get("step_id") != step_id:
                    continue
                results.append(event)
        return results
```

**关键设计约束**：
- 签名兼容 `SimpleLogger.log(event_type, data)`，调用方无需改动
- `trace_id` 由 Orchestrator 统一生成并注入（v5.1 修正）
- append-only 写入，不覆盖
- 日志写入失败降级到 print，不抛异常（v3.1 约束）
- 目录创建失败也降级，不崩溃（v5.1 修正）
- 文件名含 `trace_id`，便于按运行查询

---

### 2.3 Token Audit → 持久化报表 + CLI 摘要

**痛点**：v4 只在 Step 6 print 一行总 Token 数，不持久化。阶段一收尾 P0-3 已增强 Step 6 打印明细表，但仍只在 stdout。

**v5 设计**：生成单次运行成本报表（JSON + Markdown），持久化到 `logs/` 目录。不改变 `StepOutput` 模型。

**v5.1 修正**（评议 Q3）：Token 统计从报告正文移除后，CLI 保留一行成本摘要 + 详细报表路径，避免用户需要打开文件才知道成本。

```python
# harness/token_audit.py (~60 行，v5 新增)

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from models import ReportState


# SiliconFlow DeepSeek-V4-Pro 定价（2026-06-18 实测确认，★★★★★ [可信]）
# 来源：https://siliconflow.cn/pricing
PRICING = {
    "input_per_million": 3.0,   # ¥ / 1M tokens
    "output_per_million": 6.0,  # ¥ / 1M tokens
}


class TokenAudit:
    """v5 新增：Token 持久化审计，生成单次运行成本报表。

    不改变 StepOutput 模型，只读取 token_usage 字段。
    v5.1：trace_id 从外部注入（由 Orchestrator 统一生成）。
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

    def generate_report(
        self,
        state: ReportState,
        trace_id: str,
        industry_name: str,
    ) -> dict:
        """生成成本报表，返回 dict 并持久化到 JSON + Markdown。"""
        steps_data = []
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

        report = {
            "trace_id": trace_id,
            "industry": industry_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pricing_source": "SiliconFlow DeepSeek-V4-Pro (2026-06-18)",
            "steps": steps_data,
            "summary": {
                "total_prompt_tokens": total_input,
                "total_completion_tokens": total_output,
                "total_tokens": total_tokens,
                "input_cost_cny": round(input_cost, 4),
                "output_cost_cny": round(output_cost, 4),
                "total_cost_cny": round(total_cost, 4),
                "total_cost_usd": round(total_cost / 7.2, 4),  # 汇率 1 USD ≈ 7.2 CNY
            },
        }

        # 持久化 JSON
        json_path = self.log_dir / f"{trace_id}_token_audit.json"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 持久化 Markdown（人类可读）
        md_path = self.log_dir / f"{trace_id}_token_audit.md"
        md_path.write_text(self._to_markdown(report), encoding="utf-8")

        return report

    def _to_markdown(self, report: dict) -> str:
        lines = [
            f"# Token 审计报表 — {report['industry']}",
            f"",
            f"- trace_id: `{report['trace_id']}`",
            f"- 时间: {report['timestamp']}",
            f"- 定价来源: {report['pricing_source']}",
            f"",
            f"## 步骤明细",
            f"",
            f"| 步骤 | prompt | completion | total |",
            f"|------|--------|------------|-------|",
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
            f"",
            f"## 汇总",
            f"",
            f"- 总 Token: {summary['total_tokens']}",
            f"- 输入成本: ¥{summary['input_cost_cny']}",
            f"- 输出成本: ¥{summary['output_cost_cny']}",
            f"- **总成本: ¥{summary['total_cost_cny']} (≈ ${summary['total_cost_usd']})**",
        ])
        return "\n".join(lines)
```

**CLI 摘要输出**（v5.1 新增，评议 Q3）：

```python
# frost_agent.py — Step 6 输出后，CLI 打印成本摘要
token_report = token_audit.generate_report(state, trace_id, industry_name)
print(f"  Token 审计: ¥{token_report['summary']['total_cost_cny']} (≈ ${token_report['summary']['total_cost_usd']})")
print(f"  详细报表: logs/{trace_id}_token_audit.md")
```

**关键设计约束**：
- 不改变 `StepOutput` 模型，只读取 `token_usage` 字段
- 定价来源明确标注（SiliconFlow 官网，2026-06-18 实测确认）
- 同时生成 JSON（机器可读）和 Markdown（人类可读）两种格式
- 文件名含 `trace_id`，与 Session Event Log 关联
- Token 统计不在报告正文中显示，CLI 保留成本摘要（v5.1）

---

### 2.4 Checkpoint → 多版本 + 过期清理（文件内 saved_at）

**痛点**：v4 的 `save_checkpoint()` 是覆盖写入，崩溃后只能恢复到最新版本，无法回滚到历史版本。阶段三 Evaluator-Optimizer 闭环需要"恢复到某一步的旧版本，重跑后续步骤"。

**v5 设计**：每次 save 创建新版本文件，自动保留 7 天，文件命名考虑 `request_id` 扩展性（阶段三并发场景）。

**v5.1 修正**（评议 Q1/Q2 + 二次评议）：
- 清理逻辑从文件名字符串解析改为文件内 `saved_at` 字段（消除碰撞风险）
- `load_version` 的 `step_id` 改为必填（避免随机匹配）
- `fromisoformat` 跨版本兼容（Python 3.9 不支持 `Z` 后缀）
- `load()` 处理 v4 遗留格式（纯 ReportState）和 v5 包装格式
- 损坏文件分层清理（JSONDecodeError 直接删除，其他解析问题保留并记录）

```python
# harness/checkpoint.py (~120 行，v5 升级，v5.1 修正清理逻辑)

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from models import ReportState


class CheckpointManager:
    """v5 升级：多版本 Checkpoint + 过期清理。

    v5.1 修正（评议 Q1 + 二次评议）：
    - 清理逻辑从文件名解析改为文件内 saved_at 字段
    - load_version 的 step_id 改为必填
    - load() 兼容 v4 遗留格式（纯 ReportState）和 v5 包装格式
    - 损坏文件分层清理

    签名兼容 v4 的 save_checkpoint() / try_resume()。
    v3.1 关键约束：
    - 清理逻辑需有单元测试（时间判断 bug 会导致磁盘占满）
    - 文件命名考虑 request_id 扩展性（阶段三并发场景）
    """

    def __init__(self, checkpoint_dir: str = "checkpoints", retention_days: int = 7):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.retention_days = retention_days

    def save(self, state: ReportState, step_id: str, request_id: Optional[str] = None):
        """保存当前 State 到新版本文件。

        签名兼容 v4 save_checkpoint(state, step_id)。
        request_id 为可选参数，阶段三并发场景使用。

        v5.1 修正：写入包装格式 {"saved_at": ..., "state": ...}，
        清理逻辑读取 saved_at 字段而非文件名解析。
        """
        # 文件命名：{industry}_{timestamp}_{step_id}[_{request_id}].json
        safe_name = state.industry_name.replace("/", "_").replace(" ", "_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        parts = [safe_name, timestamp, step_id]
        if request_id:
            parts.append(request_id)
        filename = "_".join(parts) + ".json"
        path = self.checkpoint_dir / filename

        # v5.1 修正：包装格式，saved_at 用于清理逻辑
        wrapper = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "state": json.loads(state.model_dump_json()),  # ReportState 的 JSON
        }
        path.write_text(
            json.dumps(wrapper, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 同时更新 latest 指针（兼容 v4 try_resume 的"读最新"语义）
        latest_path = self._latest_path(state.industry_name)
        latest_path.write_text(path.name, encoding="utf-8")

        # 顺手清理过期文件
        self._cleanup_expired()

    def load(self, industry_name: str) -> Optional[ReportState]:
        """尝试从最新 checkpoint 恢复。

        签名兼容 v4 try_resume(industry_name)。

        v5.1 修正（二次评议 Q1-B）：兼容 v4 遗留格式（纯 ReportState）
        和 v5 包装格式（{"saved_at": ..., "state": ...}）。
        """
        latest_path = self._latest_path(industry_name)
        if not latest_path.exists():
            return None
        filename = latest_path.read_text(encoding="utf-8").strip()
        path = self.checkpoint_dir / filename
        if not path.exists():
            return None
        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            # v5 包装格式：提取 state 字段
            if isinstance(data, dict) and "state" in data and "saved_at" in data:
                return ReportState.model_validate(data["state"])
            # v4 遗留格式：直接是 ReportState
            return ReportState.model_validate(data)
        except Exception:
            return None

    def load_version(
        self,
        industry_name: str,
        timestamp: str,
        step_id: str,  # v5.1 修正：从 Optional 改为必填（评议 Q2）
    ) -> Optional[ReportState]:
        """v5 新增：按时间戳 + step_id 加载历史版本（阶段三 Evaluator-Optimizer 闭环用）。

        v5.1 修正（评议 Q2）：step_id 改为必填，避免 glob 返回随机匹配。
        阶段三循环恢复时，FixItem.target_step 已指定步骤，调用方总是知道 step_id。

        Args:
            industry_name: 行业名
            timestamp: 版本时间戳，格式 YYYYMMDD_HHMMSS
            step_id: 必填，指定步骤
        """
        safe_name = industry_name.replace("/", "_").replace(" ", "_")
        pattern = f"{safe_name}_{timestamp}_{step_id}_*"
        matches = list(self.checkpoint_dir.glob(pattern + ".json"))
        if not matches:
            return None
        try:
            raw_text = matches[0].read_text(encoding="utf-8")
            data = json.loads(raw_text)
            # v5 包装格式
            if isinstance(data, dict) and "state" in data and "saved_at" in data:
                return ReportState.model_validate(data["state"])
            # v4 遗留格式
            return ReportState.model_validate(data)
        except Exception:
            return None

    def _latest_path(self, industry_name: str) -> Path:
        safe_name = industry_name.replace("/", "_").replace(" ", "_")
        return self.checkpoint_dir / f"{safe_name}_latest.txt"

    def _cleanup_expired(self):
        """v5.1 修正：清理过期 Checkpoint 文件，基于文件内 saved_at 字段。

        v5.0 的文件名字符串解析有碰撞风险（行业名含 YYYYMMDD_HHMMSS 时误判）。
        v5.1 改用文件内 saved_at 字段，完全不依赖文件名解析。

        v5.1 修正（二次评议 Q1-C）：损坏文件分层清理：
        - JSONDecodeError：直接删除（无恢复价值）
        - 其他解析问题：保留并记录（可能是未来版本格式）
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)

        for path in self.checkpoint_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))

                # v5 包装格式：读取 saved_at 字段
                if isinstance(data, dict) and "saved_at" in data:
                    # v5.1 修正（二次评议 Q1-A）：Python 3.9 不支持 Z 后缀
                    saved_at_str = data["saved_at"].replace("Z", "+00:00")
                    saved_at = datetime.fromisoformat(saved_at_str)
                    if saved_at < cutoff:
                        path.unlink(missing_ok=True)
                    continue

                # v4 遗留格式：无 saved_at 字段
                # 检查是否是有效的 ReportState（有 industry_name 字段）
                if isinstance(data, dict) and "industry_name" in data:
                    # v4 文件无法判断时间，保留不删（保守策略）
                    # v4 文件会在自然迭代中被 v5 文件替代
                    continue

                # 既不是 v5 包装格式，也不是 v4 ReportState：未知格式，保留并记录
                print(f"[Checkpoint 清理] 跳过未知格式文件: {path.name}")

            except json.JSONDecodeError:
                # v5.1 修正（二次评议 Q1-C）：损坏文件，直接删除（无恢复价值）
                path.unlink(missing_ok=True)
            except (KeyError, ValueError) as e:
                # v5.1 修正：其他解析问题，保留并记录（可能是未来版本格式）
                print(f"[Checkpoint 清理] 跳过无法解析的文件: {path.name} ({e})")
```

**关键设计约束**：
- 签名兼容 v4 `save_checkpoint(state, step_id)` / `try_resume(industry_name)`
- 每次 save 创建新版本文件，不覆盖
- 清理逻辑基于文件内 `saved_at` 字段，不依赖文件名解析（v5.1 修正）
- `fromisoformat` 跨版本兼容（`.replace("Z", "+00:00")`，v5.1 修正）
- `load()` 兼容 v4 遗留格式和 v5 包装格式（v5.1 修正）
- 损坏文件分层清理：JSONDecodeError 直接删除，其他解析问题保留并记录（v5.1 修正）
- `load_version()` 的 `step_id` 必填（v5.1 修正）
- 文件命名考虑 `request_id` 扩展性（阶段三并发场景）
- 清理逻辑需有单元测试（v3.1 约束）

---

### 2.5 Output Safety（UTC 时间戳 + 版本号）

**痛点**：v4 的报告保存是覆盖写入。阶段一收尾 P1-2 已做临时修复（追加本地时间戳），但本地时间戳在不同时区运行时会碰撞。

**v5 设计**：时间戳使用 UTC + 时区标注，检测到已存在时追加版本号。

**v5.1 补充**（评议 P3-12）：时区标注的用途说明——价值在可读性（避免非技术用户误读 UTC 为本地时间），非防碰撞（碰撞由秒级精度 + 版本号解决）。

```python
# harness/output_safety.py (~50 行，v5 新增)

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class OutputSafety:
    """v5 新增：输出安全，防止报告覆盖写入。

    v3.1 关键约束：
    - 时间戳使用 UTC + 时区标注（避免不同时区运行时碰撞）
    - 检测到已存在时追加版本号

    v5.1 补充（评议 P3-12）：时区标注的用途是可读性——
    UTC 时间戳（如 20250618_143052）对非技术用户不直观，可能误读为本地时间。
    'UTC' 标注能避免误读，成本仅是文件名多 4 个字符。
    碰撞防护由秒级精度 + 版本号追加解决，不依赖时区标注。
    """

    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)

    def safe_save(self, content: str, industry_name: str) -> Path:
        """安全保存报告，返回最终文件路径。

        文件名格式：{industry}_{UTC时间戳}_{时区}_行业定义报告.md
        若已存在，追加版本号：..._v2.md、..._v3.md
        """
        safe_name = industry_name.replace("/", "_").replace(" ", "_")
        # UTC 时间戳 + 时区标注
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        tz_label = "UTC"

        base_filename = f"{safe_name}_{timestamp}_{tz_label}_行业定义报告"
        path = self.reports_dir / f"{base_filename}.md"

        # 检测已存在，追加版本号
        version = 2
        while path.exists():
            path = self.reports_dir / f"{base_filename}_v{version}.md"
            version += 1

        path.write_text(content, encoding="utf-8")
        return path
```

**关键设计约束**：
- 时间戳使用 UTC + 时区标注（v3.1 约束，避免不同时区碰撞）
- 时区标注用途是可读性，非防碰撞（v5.1 补充）
- 检测到已存在时追加版本号（`_v2.md`、`_v3.md`）
- 文件名格式：`{industry}_{UTC时间戳}_{时区}_行业定义报告.md`

---

### 2.6 methodology/ → 简化拆分 + 版本一致性检查

**痛点**：v4 的单文件 `方法论-v2.md` 调整时需要改代码（`SLICE_MAP` 关键词映射）。当前痛点是"方法论调整需要改代码"，不是"单文件太大"。

**v5 设计**：拆成 2-3 模块 + `_meta.yaml` 版本声明。保持正则切片逻辑，只把最可能独立变更的章节拆出。拆分后需验证正则切片不丢章节（v3.1 约束）。

**v5.1 补充**（评议 Q6）：版本迁移简化策略——不支持运行时版本切换，手动替换全部文件，`_meta.yaml` 与 fallback 版本一致性检查。

```
方法论/
├── _meta.yaml              # 版本声明 + 模块清单
├── hard_rules.md           # Hard Rules（R1-R5，最稳定）
├── heuristics.md           # Heuristics（H1-H4，可能调整）
├── self_check.md           # 自检清单（C1-C5，可能调整）
└── methodology_full.md     # 完整方法论文档（保留，作为 fallback）
```

```yaml
# methodology/_meta.yaml
# v5.1 补充：version 字段仅用于追溯，不参与运行时逻辑
# 版本迁移策略：不支持运行时切换，手动替换全部文件
# fallback 文件应始终保持为最新完整版本
version: "v2"
modules:
  - name: hard_rules
    file: hard_rules.md
    keywords: ["Hard Rules", "R1", "R2", "R3", "R4", "R5"]
  - name: heuristics
    file: heuristics.md
    keywords: ["维度筛选原则", "Heuristics", "H1", "H2", "H3", "H4"]
  - name: self_check
    file: self_check.md
    keywords: ["自检清单", "C1", "C2", "C3", "C4", "C5"]
fallback: methodology_full.md
```

```python
# methodology_loader.py (~130 行，v5 升级，v5.1 补充版本一致性检查)

from __future__ import annotations

import re
import yaml
from pathlib import Path
from typing import Optional


class MethodologyLoader:
    """v5 升级：支持拆分模块加载 + 版本声明。

    v5.1 补充（评议 Q6）：
    - 版本迁移简化策略：不支持运行时切换，手动替换全部文件
    - _meta.yaml 与 fallback 版本一致性检查

    v3.1 关键约束：拆分后需验证正则切片不丢章节
    （模块间正则边界不一致会导致加载丢内容）。
    """

    def __init__(self, methodology_dir: str = "方法论"):
        self.dir = Path(methodology_dir)
        self._meta: Optional[dict] = None
        self._module_cache: dict[str, str] = {}
        self._full_cache: Optional[str] = None

    def _load_meta(self) -> dict:
        """加载 _meta.yaml。"""
        if self._meta is None:
            meta_path = self.dir / "_meta.yaml"
            if meta_path.exists():
                self._meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                # v5.1 补充（评议 Q6）：_meta.yaml 与 fallback 版本一致性检查
                self._check_fallback_version_consistency()
            else:
                # 兼容 v4：无 _meta.yaml 时回退到单文件模式
                self._meta = {"version": "v2", "fallback": "方法论-v2.md", "modules": []}
        return self._meta

    def _check_fallback_version_consistency(self):
        """v5.1 新增（评议 Q6）：检查 fallback 文件版本与 _meta.yaml 是否一致。

        捕捉手动替换时"忘了更新 fallback 文件"的人为错误。
        """
        meta_version = self._meta.get("version", "")
        fallback_file = self._meta.get("fallback", "")
        fallback_path = self.dir / fallback_file
        if not fallback_path.exists():
            return
        fallback_content = fallback_path.read_text(encoding="utf-8")
        # 在 fallback 文件前 500 字符中查找版本声明（如 "v2", "v2.1"）
        # 这只是启发式检查，不强制要求 fallback 文件包含版本声明
        if meta_version and meta_version not in fallback_content[:500]:
            print(
                f"[警告] _meta.yaml 版本({meta_version})与 fallback 文件({fallback_file})不一致，"
                f"请检查手动替换时是否遗漏了 fallback 文件的更新"
            )

    def load_methodology(self) -> str:
        """加载完整方法论文档（fallback 文件）。"""
        if self._full_cache is None:
            meta = self._load_meta()
            fallback_file = meta.get("fallback", "方法论-v2.md")
            path = self.dir / fallback_file
            if not path.exists():
                # 兼容 v4：尝试从上级目录加载
                path = self.dir.parent / fallback_file
            self._full_cache = path.read_text(encoding="utf-8")
        return self._full_cache

    def load_slice(self, step_id: str) -> str:
        """按 step_id 返回相关的方法论章节。

        v4 的 SLICE_MAP 关键词映射保留，但优先从拆分模块加载。
        v3.1 约束：拆分后需验证正则切片不丢章节。
        """
        # v4 的 SLICE_MAP（保留兼容）
        SLICE_MAP = {
            "1_info_collection":       ["信息优先级", "参考框架", "Hard Rules"],
            "2_dimension_screening":   ["维度筛选原则", "Heuristics", "自检清单"],
            "3_structure_decision":    ["报告结构", "范围约束"],
            "4_content_generation":    ["Hard Rules", "推理展示", "范围约束"],
            "5_self_check":            ["自检清单"],
        }
        keywords = SLICE_MAP.get(step_id, [])

        # v5 新增：优先从拆分模块加载
        meta = self._load_meta()
        matched_modules = []
        for module in meta.get("modules", []):
            module_keywords = module.get("keywords", [])
            if any(kw in keywords for kw in module_keywords):
                module_content = self._load_module(module["file"])
                if module_content:
                    matched_modules.append(module_content)

        if matched_modules:
            # 验证：合并后的内容应包含所有关键词
            merged = "\n\n".join(matched_modules)
            self._verify_slice_completeness(step_id, keywords, merged)
            return merged

        # 回退到 v4 的正则切片逻辑
        return self._legacy_regex_slice(step_id, keywords)

    def _load_module(self, filename: str) -> Optional[str]:
        """加载单个模块文件（带缓存）。"""
        if filename not in self._module_cache:
            path = self.dir / filename
            if path.exists():
                self._module_cache[filename] = path.read_text(encoding="utf-8")
            else:
                self._module_cache[filename] = None
        return self._module_cache[filename]

    def _verify_slice_completeness(self, step_id: str, keywords: list[str], content: str):
        """v3.1 约束：验证正则切片不丢章节。

        如果关键词在完整方法论中存在但在切片中缺失，打印警告。
        """
        full = self.load_methodology()
        for kw in keywords:
            if kw in full and kw not in content:
                print(f"[警告] Step {step_id} 的方法论切片丢失关键词: {kw}")

    def _legacy_regex_slice(self, step_id: str, keywords: list[str]) -> str:
        """v4 兼容：正则切片逻辑。"""
        full = self.load_methodology()
        if not keywords:
            return full
        sections = re.split(r'(?=^## )', full, flags=re.MULTILINE)
        matched = [s for s in sections if any(kw in s for kw in keywords)]
        if not matched or sum(len(s) for s in matched) < 100:
            print(f"[警告] Step {step_id} 的方法论切片为空或过短，回退到全量方法论")
            return full
        return "\n\n".join(matched)
```

**关键设计约束**：
- 保持 v4 的正则切片逻辑作为 fallback
- 优先从拆分模块加载，模块由 `_meta.yaml` 声明
- 拆分后需验证正则切片不丢章节（v3.1 约束，`_verify_slice_completeness` 方法）
- 兼容 v4：无 `_meta.yaml` 时回退到单文件模式
- 版本迁移简化策略：不支持运行时切换，手动替换全部文件（v5.1 补充）
- `fallback` 文件始终保持为最新完整版本（v5.1 补充）
- `_meta.yaml` 与 fallback 版本一致性检查（v5.1 补充）

---

### 2.7 Step 1 搜索补搜循环（Search Supplement Loop）

**痛点**：v4 的 Step 1 用 3 个静态模板搜索，无法根据搜索结果质量动态补充。某些行业的关键信息维度可能未被静态模板覆盖，导致信息收集不完整，影响后续报告质量。

**v5.2 设计**：在 Step 1 内部加入 FM（Field Manager）审查-补搜循环。首轮用 3 个静态模板搜索 → FM 审查搜索结果 → 若有信息缺口且 FM 能生成具体补搜关键词 → 触发补搜，最多 2 轮，总共 ≤5 个 query。**不改 search.py 接口，不改管线架构**。

**关键约束**：
- 循环封装在 Step 1 内部，对外仍然是"Step 1 产出信息收集结果"
- Step 2-6 的逻辑完全不受影响
- search.py 的 `search_with_fallback()` 接口不变，补搜只是额外调用

**流程图**：

```
Step 1 内部：
  首轮：3 个静态模板搜索（v4 逻辑不变）
    ↓
  FM 审查（基于方法论"信息优先级"）
    ↓
  data_gaps 为空？──是──→ 进入 LLM 总结（v4 逻辑不变）
    ↓ 否
  第 1 轮补搜（FM 生成的 1-2 个 query）
    ↓
  FM 再审查
    ↓
  data_gaps 为空？──是──→ 进入 LLM 总结
    ↓ 否
  第 2 轮补搜（FM 生成的 1-2 个 query）
    ↓
  FM 再审查
    ↓
  data_gaps 为空？──是──→ 进入 LLM 总结
    ↓ 否
  记录 quality_flag（data_gaps_remaining, medium）
    ↓
  进入 LLM 总结（用已有信息，不阻塞流程）
```

**FM 审查标准**（v5.2 新增）：

FM 审查基于方法论的"信息优先级"章节，不自由判断。FM 审查的对象是**搜索结果**（Tavily 返回的网页内容），不是 LLM 的输出，不存在同源偏差问题。

```python
# frost_agent.py — Step 1 内部的 FM 审查 prompt（v5.2 新增）

FM_REVIEW_PROMPT = """你是行业定义信息完整性审查员。你的任务是判断当前搜索结果是否覆盖了行业定义所需的关键信息维度。

## 行业
{industry_name}

## 信息优先级（来自方法论）
{methodology_info_priority}

## 当前搜索结果摘要
{search_results_summary}

## 你的任务
1. 对照"信息优先级"，判断当前搜索结果是否有明显缺失的维度
2. 如果有缺失，列出具体缺失的维度（data_gaps）
3. 为每个缺失维度生成 1 个补搜关键词（suggested_queries）

## 输出格式（JSON）
{{
  "data_gaps": ["缺失维度1", "缺失维度2"],
  "suggested_queries": ["补搜关键词1", "补搜关键词2"]
}}

## 约束
- data_gaps 必须具体（如"缺少技术路线对比"而非"信息不够"）
- suggested_queries 必须与行业定义相关，不偏离范畴
- 每轮最多 2 个补搜关键词
- 如果搜索结果已覆盖所有关键维度，返回空列表
- 你审查的是搜索引擎返回的外部数据，不是 LLM 输出
"""
```

**实现骨架**：

```python
# frost_agent.py — Step 1 内部的搜索补搜循环（v5.2 新增，~60 行）

from __future__ import annotations

import json
from models import QualityFlag, StepOutput
from search import search_with_fallback
from methodology_loader import MethodologyLoader


async def step1_search_with_supplement(
    industry_name: str,
    methodology_loader: MethodologyLoader,
    llm_call,  # 复用 Step 1 的 LLM 调用函数
) -> tuple[list[dict], list[QualityFlag]]:
    """Step 1 搜索 + FM 审查补搜循环。

    不改 search.py 接口，循环封装在此函数内部。
    返回搜索结果列表 + quality_flags 列表。

    v5.2 新增。
    """
    MAX_SUPPLEMENT_ROUNDS = 2
    MAX_TOTAL_QUERIES = 5

    # 1. 首轮：3 个静态模板搜索（v4 逻辑不变）
    static_queries = _generate_static_queries(industry_name)  # v4 现有逻辑
    all_results = []
    for query in static_queries:
        results = await search_with_fallback(query)
        all_results.extend(results)

    queries_used = len(static_queries)
    quality_flags: list[QualityFlag] = []

    # 2. 加载方法论"信息优先级"章节
    methodology_slice = methodology_loader.load_slice("1_info_collection")
    info_priority = _extract_info_priority(methodology_slice)  # 提取信息优先级部分

    # 3. FM 审查 + 补搜循环
    for round_num in range(MAX_SUPPLEMENT_ROUNDS):
        if queries_used >= MAX_TOTAL_QUERIES:
            break

        # FM 审查
        search_summary = _summarize_search_results(all_results)
        fm_response = await llm_call(
            prompt=FM_REVIEW_PROMPT.format(
                industry_name=industry_name,
                methodology_info_priority=info_priority,
                search_results_summary=search_summary,
            ),
            max_tokens=2000,  # FM 审查用较小 max_tokens
        )

        try:
            fm_result = json.loads(fm_response)
        except json.JSONDecodeError:
            # FM 返回格式错误，不补搜，记录 flag
            quality_flags.append(QualityFlag(
                category="json_parse_fallback",
                field="fm_review",
                severity="medium",
                detail=f"FM 审查第 {round_num + 1} 轮返回非 JSON，跳过补搜",
            ))
            break

        data_gaps = fm_result.get("data_gaps", [])
        suggested_queries = fm_result.get("suggested_queries", [])

        # data_gaps 为空，不需要补搜
        if not data_gaps:
            break

        # 补搜（每轮最多 2 个 query，不超过总数限制）
        remaining_budget = MAX_TOTAL_QUERIES - queries_used
        queries_to_search = suggested_queries[:min(2, remaining_budget)]

        for query in queries_to_search:
            results = await search_with_fallback(query)
            all_results.extend(results)
            queries_used += 1

    # 4. 最后一轮审查：如果仍有缺口，记录 quality_flag
    if queries_used > len(static_queries):
        # 做过补搜，再审查一次
        search_summary = _summarize_search_results(all_results)
        fm_response = await llm_call(
            prompt=FM_REVIEW_PROMPT.format(
                industry_name=industry_name,
                methodology_info_priority=info_priority,
                search_results_summary=search_summary,
            ),
            max_tokens=2000,
        )
        try:
            fm_result = json.loads(fm_response)
            if fm_result.get("data_gaps"):
                quality_flags.append(QualityFlag(
                    category="data_gaps_remaining",
                    field="; ".join(fm_result["data_gaps"]),
                    severity="medium",
                    detail=f"补搜 {queries_used - len(static_queries)} 个 query 后仍有缺口",
                ))
        except json.JSONDecodeError:
            pass  # 已有 json_parse_fallback 记录

    return all_results, quality_flags
```

**quality_flags 新增 category**（v5.2）：

| category | 默认 severity | 判定规则 |
|----------|--------------|----------|
| `data_gaps_remaining` | medium | 补搜后仍有信息缺口，质量可接受但不完整 |

**Step 1 timeout 调整**：

```python
# models.py — STEP_BUDGETS 调整（v5.2）

STEP_BUDGETS = {
    "1_info_collection": StepBudget(
        timeout_seconds=180,  # v5.2: 120 → 180（搜索补搜循环需要额外时间）
        max_tokens=100000,
    ),
    # ... 其他步骤不变 ...
}
```

**延迟分析**：
- 首轮搜索 2-4s + FM 审查 ~15s/轮 × 最多 3 轮 = 最坏额外 ~45s
- Step 1 timeout 从 120s → 180s，覆盖最坏情况
- **阶段二退出条件无耗时考核**，timeout 调整是工程需要（不超时），非考核要求

**成本分析**：
- FM 审查用 `max_tokens=2000`，每次约 $0.002（按阶段一实测定价）
- 最坏情况 3 次 FM 审查 = $0.006 额外
- 多数情况不触发补搜（静态模板已覆盖），平均额外成本 < $0.001/次
- 总成本仍远低于 $0.10 闸门

**FM 模型**：
- 阶段二用 DeepSeek-V4-Pro（与 Step 1 同模型）
- FM 审查的是搜索结果（外部数据），不是 LLM 输出，不存在同源偏差
- 阶段三 Model Router 引入后，可评估用更便宜的模型做 FM 审查

**关键设计约束**：
- 循环封装在 Step 1 内部，不改管线架构
- search.py 的 `search_with_fallback()` 接口不变
- FM 审查基于方法论"信息优先级"，不自由判断
- FM 审查对象是搜索结果（外部数据），不是 LLM 输出
- 最多 2 轮补搜，总共 ≤5 个 query
- 补搜后仍有缺口记录 `data_gaps_remaining`（medium），不阻塞流程
- FM 返回格式错误时记录 `json_parse_fallback`，不补搜
- Step 1 timeout 从 120s → 180s（工程需要，非考核要求）

---

## 三、Step 5 `fixes_required` 设计笔记（阶段三接口预留）

**v5 只留设计笔记，不实现 Pydantic 模型**。当前 `evaluator.py` 的 `fixes_required` 保持为 `list[str]`。阶段三可基于此设计升级。

**v5.1 补充**（评议 Q7）：4 条循环规则。

```python
# 阶段三可基于此设计升级（v5 不实现，只记录设计）：
#
# class FixItem(BaseModel):
#     dimension: str           # 如 "C4", "llm_empty_field"
#     problem: str             # 问题描述
#     target_step: str | None  # 建议重跑的步骤（如 "1_info_collection"），None 表示不指定
#     severity: str            # "high" / "medium" / "low"
#
# 阶段三 Evaluator-Optimizer 闭环会读取 FixItem.target_step，
# 结合 CheckpointManager.load_version(industry, timestamp, step_id) 恢复到该步骤的旧版本，重跑后续步骤。
#
# v5.1 补充（评议 Q7）：4 条循环规则
#
# 规则 1（循环计数）：按重跑次数计数（每轮重跑所有 target_step 不为 None 的 FixItem），最多 3 轮。
# 规则 2（severity 阈值）：只有 severity="high" 或 "medium" 的 FixItem 触发自动修正，
#                          severity="low" 只记录不触发。
# 规则 3（合并规则）：同一 target_step 的多个 FixItem 合并后只重跑一次该 step。
# 规则 4（未收敛停止）：重跑后新的 FixItem 列表与上一轮完全相同（未收敛），停止循环，
#                      注入警告"自动修正未收敛，建议人工介入"。
```

**这不是"提前做循环"，而是"阶段二设计数据结构时，让阶段三不需要返工阶段二的数据结构"。**

---

## 四、v4 继承组件（保持不变）

以下 v4 组件在 v5 中保持不变，不重复描述：

| 组件 | v4 状态 | v5 状态 | 说明 |
|------|---------|---------|------|
| **Context Builder（四层）** | 完整实现 | 保持不变 | 静态身份 + 方法论切片 + 任务指令 + 前序摘要 |
| **搜索并行 + 结果压缩** | 完整实现 | 保持不变 | Tavily 并行搜索 + 结果截断 |
| **Independent Evaluator** | 完整实现 | 保持不变 | Step 5 独立 LLM 审查，C1-C5 |
| **`call_with_timeout`** | 阶段一收尾已完成 | 保持不变 | 带超时的重试封装（非熔断器）。**不属于阶段二 A 组工作范围**（v5.1 修正表述） |
| **StepBudget** | 完整实现 | 保持不变 | 各步资源约束，v5 强制执行 timeout |
| **SprintContract** | 类定义保留，不实例化 | 保持不变 | v3 已移除 Sprint Contract，但类定义保留兼容 |

---

## 五、Orchestrator 逻辑（v5.1）

**v5.1 修正**（评议 Q5）：`trace_id` 由 Orchestrator 统一生成并注入各组件。CLI 保留 Token 成本摘要（评议 Q3）。

```python
# frost_agent.py 骨架（v5.1，修改现有 ~771 行，非重写）

from __future__ import annotations

import asyncio
import os
import sys
import uuid  # v5.1 新增：Orchestrator 统一生成 trace_id
from models import ReportState, StepOutput, STEP_BUDGETS
from context_builder import ContextBuilder
from evaluator import evaluate
from methodology_loader import MethodologyLoader
from harness.circuit_breaker import call_with_timeout
from harness.session_log import SessionEventLog
from harness.checkpoint import CheckpointManager
from harness.token_audit import TokenAudit
from harness.output_safety import OutputSafety
from search import search_with_fallback

# v5 新增：STEP4_MAX_TOKENS 环境变量（阶段一收尾 P0-1 成果）
STEP4_MAX_TOKENS = int(os.getenv("STEP4_MAX_TOKENS", "10000"))


async def run(industry_name: str) -> str:
    # v5.1 修正（评议 Q5）：Orchestrator 统一生成 trace_id
    trace_id = uuid.uuid4().hex[:12]

    # 1. 初始化 v5 组件（注入 trace_id）
    logger = SessionEventLog(industry_name, trace_id=trace_id)  # v5.1：注入 trace_id
    checkpoint_mgr = CheckpointManager()     # v5：多版本
    token_audit = TokenAudit()               # v5：持久化报表
    output_safety = OutputSafety()           # v5：UTC 时间戳
    methodology_loader = MethodologyLoader() # v5：拆分模块

    logger.log("start", {"industry": industry_name, "trace_id": trace_id})

    # 2. 尝试恢复（签名兼容 v4）
    state = checkpoint_mgr.load(industry_name) or ReportState(industry_name=industry_name)

    # 3. 执行未完成的步骤
    steps = [
        ("1_info_collection",      step1_info_collection),
        ("2_dimension_screening",  step2_dimension_screening),
        ("3_structure_decision",   step3_structure_decision),
        ("4_content_generation",   step4_content_generation),
        ("5_self_check",           step5_self_check),
    ]

    completed = {s.step_id for s in state.steps}
    for step_id, step_fn in steps:
        if step_id in completed:
            logger.log("skip", {"step_id": step_id, "reason": "already completed"})
            continue

        logger.log("step_start", {"step_id": step_id})
        try:
            result = await call_with_timeout(
                lambda: step_fn(state),
                timeout_seconds=STEP_BUDGETS[step_id].timeout_seconds,
            )
            state.steps.append(result)
            # v5：多版本 Checkpoint
            checkpoint_mgr.save(state, step_id)
            logger.log("step_complete", {
                "step_id": step_id,
                "confidence": result.confidence,
                "quality_flags_count": len(result.quality_flags),  # v5 新增
            })
        except Exception as e:
            # v5：记录 quality_flag 并决定是否继续
            logger.log("step_error", {"step_id": step_id, "error": str(e)})
            # ... 错误处理逻辑 ...

    # 4. Step 5 结果判断（v4 继承）
    step5 = next((s for s in state.steps if s.step_id == "5_self_check"), None)
    if step5 and step5.result.get("overall") != "pass":
        # ... v4 的警告注入逻辑 ...

    # 5. 输出（v5 升级）
    final_report = step6_output(state)
    # v5：安全保存（UTC 时间戳 + 版本号）
    report_path = output_safety.safe_save(final_report, industry_name)
    logger.log("complete", {
        "report_length": len(final_report),
        "report_path": str(report_path),
    })

    # 6. v5 新增：Token 审计持久化 + CLI 摘要（v5.1 修正：用注入的 trace_id）
    token_report = token_audit.generate_report(state, trace_id, industry_name)
    # v5.1 新增（评议 Q3）：CLI 保留成本摘要
    print(f"  Token 审计: ¥{token_report['summary']['total_cost_cny']} (≈ ${token_report['summary']['total_cost_usd']})")
    print(f"  详细报表: logs/{trace_id}_token_audit.md")

    return final_report
```

---

## 六、v4 → v5 增量集成指引（v5.1 新增，评议 P0-3；v5.2 补充搜索补搜循环）

**实现方式**：新增 5 个模块文件 + 修改现有 Orchestrator 的导入和调用点，**不重写 frost_agent.py**。

| 文件 | 操作 | 改动范围 |
|------|------|---------|
| `harness/session_log.py` | **重写**（从 SimpleLogger 升级到 SessionEventLog） | ~80 行，签名兼容 |
| `harness/checkpoint.py` | **重写**（从 save/try_resume 升级到 CheckpointManager） | ~120 行，签名兼容 |
| `harness/token_audit.py` | **新增** | ~60 行 |
| `harness/output_safety.py` | **新增** | ~50 行 |
| `methodology_loader.py` | **修改**（增加拆分模块加载逻辑，保留 v4 正则切片 fallback） | ~130 行（v4 ~80 行 + 新增 ~50 行） |
| `models.py` | **修改**（新增 `QualityFlag` 模型，`StepOutput` 增加 `quality_flags` 字段，`STEP_BUDGETS` Step 1 timeout 120→180） | +~30 行 |
| `frost_agent.py` | **修改**（导入新组件、替换调用点、Step 6 汇总 quality_flags、移除 Token 统计到 TokenAudit、Orchestrator 生成 trace_id、**v5.2：Step 1 集成搜索补搜循环**） | 修改 ~50 行 + v5.2 新增 ~60 行，不重写 |
| `方法论/` 目录 | **新增**（拆分模块 + `_meta.yaml` + fallback） | 新增 5 个文件 |

**关键约束**：
- `frost_agent.py` 的六步逻辑（Step 1-5）**保持不变**，只修改导入和调用点
- **v5.2 例外**：Step 1 内部新增搜索补搜循环，但封装在 `step1_search_with_supplement()` 函数中，不改 Step 1 对外接口
- v4 的 Mock LLM 逻辑**保留**，用于单元测试
- 签名兼容的组件（SessionEventLog、CheckpointManager）替换时调用方无需改动

---

## 七、文件清单与规模

```
行业定义agent/
├── frost_agent.py              # ~880 行  Orchestrator + 六步 + v5 组件集成 + v5.2 搜索补搜循环（v4 ~771 + v5 修改 ~50 + v5.2 ~60）
├── models.py                   # ~220 行  Schema + QualityFlag（v5 新增）+ Budget（v4 ~186 + v5 ~30）
├── methodology_loader.py       # ~130 行  v5 升级：拆分模块 + _meta.yaml + 版本一致性检查
├── context_builder.py          # ~90 行   保持不变
├── evaluator.py                # ~60 行   保持不变
├── search.py                   # ~80 行   保持不变（v5.2 不改接口）
├── requirements.txt            # ~12 行   v5 新增 pyyaml
│
├── harness/                    # v5 升级
│   ├── __init__.py
│   ├── circuit_breaker.py      # ~40 行   阶段一收尾已完成（非 A 组）
│   ├── session_log.py          # ~80 行   v5 升级：JSONL + trace_id（注入式）
│   ├── checkpoint.py           # ~120 行  v5 升级：多版本 + 文件内 saved_at + v4 兼容
│   ├── token_audit.py          # ~60 行   v5 新增
│   └── output_safety.py        # ~50 行   v5 新增
│
├── 方法论/                      # v5 新增：拆分模块
│   ├── _meta.yaml              # 版本声明 + 模块清单
│   ├── hard_rules.md           # Hard Rules（R1-R5）
│   ├── heuristics.md           # Heuristics（H1-H4）
│   ├── self_check.md           # 自检清单（C1-C5）
│   └── methodology_full.md     # 完整方法论（fallback）
│
├── checkpoints/                # 自动生成（v5：多版本）
├── logs/                       # 自动生成（v5：JSONL + token_audit）
└── reports/                    # 自动生成（v5：UTC 时间戳）
```

**v5.2 总计：~1,960 行 Python**（v4 实际 ~1,585 行 + v5.1 新增/修改 ~340 行 + v5.2 搜索补搜循环 ~60 行）。

> **v5.1 修正**（评议 P3-11）：v5.0 估计 ~1,100 行是错误的（那是 v4 核心逻辑 ~760 + v5 新增 ~340）。
> 实际 v4 已有 ~1,585 行（含 Mock ~350 行、实现细节 ~200 行、注释/空行），v5 新增/修改 ~340 行后，总量接近 ~1,900 行。
> **v5.2 补充**：搜索补搜循环新增 ~60 行，总量 ~1,960 行。

---

## 八、验收标准

| 标准 | 验证方式 | 测试构造方法（v5.1 补充） |
|------|---------|------------------------|
| `quality_flags` 在 Step 1-5 产生降级时正确记录 | Mock 测试：模拟搜索部分失败，检查 StepOutput.quality_flags | 通过 monkeypatch `search_with_fallback`，使其返回 2/3 成功结果 |
| Step 6 报告尾部有 quality_flags 汇总（按严重度分组） | 检查报告文件 | 跑一次有降级的运行，检查报告尾部 |
| 报告正文不含 Token 统计（v5.1） | 检查报告文件 | grep "Token" 报告文件，应为空 |
| CLI 输出含 Token 成本摘要（v5.1） | 检查终端输出 | 跑一次运行，检查终端有"Token 审计: ¥X"行 |
| Session Event Log 写入 JSONL 文件（含 trace_id） | 检查 `logs/{trace_id}.jsonl` | 跑一次运行，检查文件存在且每行含 trace_id |
| Session Event Log 写入失败时降级到 print（不崩溃） | Mock 测试：模拟 IOError | monkeypatch `open` 抛 IOError，检查不崩溃且有 print 输出 |
| Session Event Log 目录创建失败时降级（v5.1） | Mock 测试：模拟目录创建失败 | monkeypatch `Path.mkdir` 抛 OSError，检查不崩溃 |
| Token Audit 生成 JSON + Markdown 报表 | 检查 `logs/{trace_id}_token_audit.json` 和 `.md` | 跑一次运行，检查两个文件存在 |
| Checkpoint 每次 save 创建新版本文件 | 跑同一行业两次，检查 `checkpoints/` 有两个版本文件 | 跑两次 `python frost_agent.py "低空经济物流"` |
| Checkpoint 过期清理基于 saved_at 字段（v5.1） | 单元测试：创建含 saved_at 的 8 天前文件，跑 save 后检查被清理 | 构造 `{"saved_at": "8天前的ISO时间", "state": {...}}` 的 JSON 文件 |
| Checkpoint v4 遗留格式可加载（v5.1） | 单元测试：构造 v4 格式（纯 ReportState JSON）文件，load() 能恢复 | 写入纯 `ReportState.model_dump_json()` 格式文件 |
| Checkpoint 损坏文件被清理（v5.1） | 单元测试：构造 JSONDecodeError 文件，跑 save 后检查被删除 | 写入非法 JSON 内容到 `.json` 文件 |
| Checkpoint `load_version()` step_id 必填（v5.1） | 单元测试：不传 step_id 应 TypeError | 调用 `load_version(industry, timestamp)` 不传 step_id |
| Output Safety 文件名含 UTC 时间戳 + 时区标注 | 检查报告文件名 | 跑一次运行，检查文件名含 `_UTC_` |
| Output Safety 检测已存在时追加版本号 | 跑同一行业同一秒两次，检查第二个文件名含 `_v2` | mock `datetime.now` 返回固定时间，跑两次 |
| methodology 拆分后正则切片不丢章节 | 单元测试：对比拆分前后切片内容 | 对每个 step_id，对比 `_legacy_regex_slice` 和模块加载结果 |
| methodology 无 `_meta.yaml` 时回退到单文件模式 | 兼容性测试 | 临时移走 `_meta.yaml`，检查 load_slice 仍工作 |
| methodology `_meta.yaml` 与 fallback 版本一致性检查（v5.1） | 单元测试：构造版本不一致场景 | `_meta.yaml` 写 v2，fallback 文件不含 v2，检查有警告 |
| **搜索补搜循环：首轮 3 个静态 query 正常执行（v5.2）** | Mock 测试：FM 返回 data_gaps 为空 | monkeypatch FM 审查返回 `{"data_gaps": [], "suggested_queries": []}`，检查不触发补搜 |
| **搜索补搜循环：FM 判断有缺口时触发补搜（v5.2）** | Mock 测试：FM 返回 data_gaps 非空 | monkeypatch FM 返回 `{"data_gaps": ["缺少技术路线"], "suggested_queries": ["XX技术路线"]}`，检查补搜被调用 |
| **搜索补搜循环：最多 2 轮补搜，总共 ≤5 个 query（v5.2）** | Mock 测试：FM 每轮都返回 data_gaps 非空 | monkeypatch FM 每轮返回非空 data_gaps，检查最多补搜 2 个 query，总共 ≤5 |
| **搜索补搜循环：补搜后仍有缺口记录 quality_flag（v5.2）** | Mock 测试：补搜后 FM 仍返回 data_gaps | 检查 StepOutput.quality_flags 含 `data_gaps_remaining`（medium） |
| **搜索补搜循环：FM 返回非 JSON 时不崩溃（v5.2）** | Mock 测试：FM 返回非 JSON 字符串 | monkeypatch FM 返回 "not json"，检查不崩溃且记录 `json_parse_fallback` |
| **Step 1 timeout 调整为 180s（v5.2）** | 检查 `STEP_BUDGETS["1_info_collection"].timeout_seconds` | 读取 models.py，确认值为 180 |
| `python frost_agent.py "低空经济物流"` 端到端跑通 | 真实 API 运行 | — |
| 报告质量不下降（Step 5 自检 pass） | 真实 API 运行，检查 Step 5 结果 | — |

---

## 九、版本变更

| 版本 | 核心变化 | 日期 |
|------|----------|------|
| v1 | A2 架构：六步流程 + State 驱动 | 2026-06-04 |
| v2 | 引入 Harness/Environment 分层（9 个组件） | 2026-06-04 |
| v3 | Demo MVP 范围裁剪：完整做 6 项、打桩 5 项、不做 3 项 | 2026-06-05 |
| v4 | 管线修复：Context Builder 四层、Step 5 失败警告注入、SLICE_MAP 修正、成本/延迟估算 | 2026-06-05 |
| v5.0 | 阶段二 A 组：quality_flags + JSONL 日志 + Token 持久化 + Checkpoint 多版本 + Output Safety + methodology 拆分 | 2026-06-18 |
| v5.1 | 整合两轮同行评议 18 项修正：Checkpoint 文件内 saved_at + load_version step_id 必填 + v4 兼容 + or_fallback 拆分 + trace_id 注入式 + 报告尾部统一 + fixes_required 4 条规则 + 增量集成指引 + 代码行数修正 | 2026-06-18 |
| **v5.2** | **新增 Step 1 搜索补搜循环：FM 审查搜索结果 + 最多 2 轮补搜 + data_gaps_remaining quality_flag + Step 1 timeout 120→180s** | **2026-06-18** |

---

## 十、参考来源

| 借鉴点 | 来源 | 可信度 | 在 v5 中的体现 |
|--------|------|--------|---------------|
| Independent Evaluator | Anthropic Three-Agent Harness (2026-03) | ★★★★★ [可信] | v4 继承，v5 不变 |
| Context Builder 四层 | Claude Code 18 层 System Prompt (arXiv:2604.14228v1) | ★★★★★ [可信] | v4 继承，v5 不变 |
| Session Event Log | Anthropic Managed Agents (2026-05) | ★★★★★ [可信] | v5 升级：JSONL + trace_id |
| `call_with_timeout` | Claude Code 错误处理 | ★★★★☆ [可信] | 阶段一收尾已完成，v5 继承 |
| **分布式追踪 trace_id** | 业界 Agent 系统通用实践 | ★★★★☆ [可信] | v5 新增：SessionEventLog 加 trace_id（v5.1 改为注入式） |
| **quality_flags 跨步骤异常传递** | 阶段一 fix-LLM空字段 开发日志 | ★★★★★ [可信] | v5 新增：Pydantic 模型约束 |
| **Pydantic 模型约束（替代字符串约定）** | v3.1 路线图修正 | ★★★★★ [可信] | v5 新增：QualityFlag 模型 |
| **Checkpoint 多版本 + 过期清理** | v3.1 路线图 | ★★★★★ [可信] | v5 新增：CheckpointManager（v5.1 改用文件内 saved_at） |
| **Output Safety UTC 时间戳** | v3.1 路线图修正 | ★★★★★ [可信] | v5 新增：OutputSafety |
| **methodology 拆分 + _meta.yaml** | v3.1 路线图 | ★★★★★ [可信] | v5 新增：MethodologyLoader |
| **Token Audit 持久化** | 阶段一收尾 P0-3 实测 | ★★★★★ [可信] | v5 新增：TokenAudit |
| **SiliconFlow DeepSeek-V4-Pro 定价** | [SiliconFlow 官网](https://siliconflow.cn/pricing)（2026-06-18 访问） | ★★★★★ [可信] | v5 TokenAudit 定价依据 |
| **Checkpoint 文件内 saved_at（替代文件名解析）** | 同行评议 Q1（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：清理逻辑改用文件内元数据 |
| **load_version step_id 必填** | 同行评议 Q2（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：step_id 从 Optional 改为必填 |
| **or_fallback 字段级拆分** | 同行评议 Q4 + 二次评议（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：拆分为 or_fallback_result / or_fallback_reasoning |
| **trace_id 注入式** | 同行评议 Q5（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：Orchestrator 统一生成并注入 |
| **Python 3.9 fromisoformat 兼容** | 同行评议二次评议 Q1-A（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：.replace("Z", "+00:00") |
| **v4 遗留 checkpoint 兼容** | 同行评议二次评议 Q1-B（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：load() 兼容两种格式 |
| **损坏文件分层清理** | 同行评议二次评议 Q1-C（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 修正：JSONDecodeError 直接删除 |
| **fixes_required 4 条循环规则** | 同行评议 Q7（Kimi，2026-06-18） | ★★★★★ [可信] | v5.1 补充：循环计数 + severity 阈值 + 合并 + 未收敛停止 |
| **搜索补搜循环设计** | 用户需求（2026-06-18） | ★★★★★ [可信] | v5.2 新增：Step 1 内部 FM 审查 + 补搜循环 |

---

*文档版本：v5.2 | 日期：2026-06-18*
*变更：基于 v5.1 迭代，新增 Step 1 搜索补搜循环——FM 审查搜索结果 + 最多 2 轮补搜 + data_gaps_remaining quality_flag + Step 1 timeout 120→180s*
*目标：~1,960 行 Python，基础设施从打桩升级到可用 + 搜索质量动态补充，为阶段三循环预留接口*
