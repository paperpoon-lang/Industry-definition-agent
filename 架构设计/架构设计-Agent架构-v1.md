# 架构设计\-Agent架构\-v1

# 行业定义 Agent — 架构设计

> 阶段二交付物 \| 2026\-06\-04 \| 给 Trae 的开发 spec

---

## 一、总体架构：A2（结构化分步单 Agent \+ State 驱动）

```Plaintext
┌──────────────────────┐
                     │    Orchestrator       │
                     │  (frost_agent.py)     │
                     │                       │
                     │  控制步骤流转          │
                     │  管理 ReportState      │
                     │  按步注入方法论切片     │
                     └──────────┬────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                  ▼
        ┌──────────┐    ┌──────────┐      ┌──────────┐
        │  Step 1  │    │  Step 2  │  …   │  Step 6  │
        │ 信息收集  │    │ 维度筛选  │      │   输出    │
        │          │    │          │      │          │
        │ + 搜索   │    │ + 方法论 │      │ + 格式化  │
        │   API    │    │   切片   │      │          │
        └──────────┘    └──────────┘      └──────────┘
              │                 │                  │
              └─────────────────┼──────────────────┘
                                │
                                ▼
                    ┌──────────────────────┐
                    │    ReportState       │
                    │  (accumulated)       │
                    │                      │
                    │  industry_name       │
                    │  steps: [StepOutput] │
                    │  final_report        │
                    └──────────────────────┘
```

**原则**：同一个 LLM 实例贯穿始终，每一步显式记录 reasoning \+ confidence，Orchestrator 只负责流转和 state 管理，不做推理。

---

## 二、State Schema

### StepOutput

```Python
from pydantic import BaseModel
from typing import Any

class StepOutput(BaseModel):
    """每一步的输出结构，强制包含推理痕迹"""
    step_id: str                    # "1_info_collection", "2_dimension_screening", ...
    step_label: str                 # 人类可读的步骤名，如 "信息收集"
    reasoning: str                  # 元规则：该步的判断推理过程（必须填写）
    confidence: str                 # "high" | "medium" | "low" + 依据简述
    result: dict[str, Any]          # 该步的结构化产出（内容因步骤而异）
    abandoned: list[str] = []       # 放弃的选择 + 为什么放弃
    methodology_ref: str            # 引用了方法论文档的哪一节
```

### ReportState

```Python
class ReportState(BaseModel):
    """贯穿全流程的状态对象"""
    methodology_version: str        # "v2"
    industry_name: str              # 用户输入
    steps: list[StepOutput] = []    # 每一步的完整记录
    final_report: str | None = None # 最终报告 markdown
```

### 通用 LLM 调用格式

```Python
class StepContext(BaseModel):
    """传给 LLM 的上下文"""
    system_prompt: str              # 方法论文档（按步切片）
    task_prompt: str                # 当前步骤的具体任务描述
    previous_steps: list[StepOutput] # 前序步骤的完整记录
    current_step_id: str
```

---

## 三、Step Contracts（六步契约）

### Step 1：信息收集

|字段|值|
|---|---|
|**step\_id**|`1_info_collection`|
|**做什么**|搜索行业相关信息，建立基础知识面|
|**方法论切片**|3\.2 信息优先级（P0\-P3）\+ 6\.参考框架（GICS/NAICS 作参照）|
|**需要工具**|Tavily 搜索 API（3\-5 轮搜索）|
|**额外约束**|搜索 queries 必须覆盖：官方定义、政策/标准文件、产业链关键环节、与相邻行业的区分、行业结构性争议点|

**输入**：`industry_name`

**输出**（`result` 字段）：

```Python
{
    "summary": str,              # 行业概览（200-300字）
    "official_definitions": list, # 官方/权威定义（来源+原文）
    "key_regulations": list,     # 关键政策/标准文件（标题+来源+要点）
    "structural_factors": list,  # 结构性影响因素（技术/制度/需求）
    "adjacent_industries": list, # 相邻行业列表
    "data_gaps": list            # 搜索后仍不清晰的关键问题
}
```

**自检**：P0 级来源至少找到 1 个？搜索覆盖了边界类 query？有相邻行业信息？

---

### Step 2：维度筛选

|字段|值|
|---|---|
|**step\_id**|`2_dimension_screening`|
|**做什么**|基于 Step 1 的信息，应用方法论 H1\-H4 筛选出值得写的维度|
|**方法论切片**|3\.1 维度筛选原则（H1\-H4）\+ 5\.自检清单 C1\-C3|
|**不需要工具**|纯推理|

**输入**：`Step 1 output` \+ `StepOutput(s) from previous`

**输出**（`result` 字段）：

```Python
{
    "selected_dimensions": [
        {
            "name": str,             # 维度名，如 "空域管制对增长的结构性约束"
            "category": str,         # 供给侧 / 需求侧 / 成本侧 / 技术侧 / 制度侧
            "rationale": str,        # 为什么选（引用方法论文档具体条款）
            "business_impact": str   # 传导至哪个经营结果（增长/盈利/竞争/壁垒）
        }
    ],
    "abandoned_dimensions": [
        {
            "name": str,
            "reason": str            # 为什么放弃（数据不可得 / 不适用 / 与保留维度交叉）
        }
    ]
}
```

**自检**：选中的维度是否覆盖 ≥2 个独立侧（供/需/成本/技术/制度）？每个维度有明确的经营结果传导？放弃的维度有记录？

---

### Step 3：结构决策

|字段|值|
|---|---|
|**step\_id**|`3_structure_decision`|
|**做什么**|基于 Step 2 选出的维度，设计报告的具体结构|
|**方法论切片**|3\.4 报告结构启发式 \+ 3\.3 范围约束|
|**不需要工具**|纯推理|

**输入**：`Step 2 output` \+ 前序全部

**输出**（`result` 字段）：

```Python
{
    "sections": [
        {
            "order": int,            # 出现顺序
            "title": str,            # 章节标题
            "purpose": str,          # 这章回答什么问题
            "selected_dimensions": list[str],  # 引用了 Step 2 的哪些维度
            "key_data_required": list[str]     # 这章需要什么类型的数据支撑
        }
    ],
    "structure_rationale": str       # 为什么这样组织（引用方法论）
}
```

**自检**：每一章都对应 Step 2 的至少一个维度？没有竞争格局/市场规模/投资建议类章节？

---

### Step 4：内容生成

|字段|值|
|---|---|
|**step\_id**|`4_content_generation`|
|**做什么**|按 Step 3 的结构逐章撰写报告正文|
|**方法论切片**|全部（R1\-R5 \+ 第四章推理展示要求）|
|**不需要工具**|纯生成|

**输入**：`Step 1, 2, 3 output` \+ 方法论文档全文

**输出**（`result` 字段）：

```Python
{
    "sections_content": [
        {
            "title": str,
            "content": str,          # markdown 正文
            "sources": list[str],    # 引用的数据来源
            "reasoning_visible": bool # 是否包含"判断推理"段落
        }
    ]
}
```

**自检**：每个判断是否有"为什么"？数据来源是否标注？行业定义和维基百科的区分度够吗？

---

### Step 5：自检

|字段|值|
|---|---|
|**step\_id**|`5_self_check`|
|**做什么**|对完整报告执行 C1\-C5 自检清单|
|**方法论切片**|5\.自检清单（C1\-C5）|
|**不需要工具**|纯推理|

**输入**：完整报告草稿（Step 4 output）

**输出**（`result` 字段）：

```Python
{
    "checks": [
        {
            "check_id": str,         # "C1", "C2", ...
            "check_label": str,      # "区分度测试"
            "result": str,           # "pass" | "fail"
            "evidence": str          # 通过/失败的依据
        }
    ],
    "overall": str,                  # "pass" | "fail_with_fixes"
    "fixes_required": list[str]      # 如果不通过，需要修改什么
}
```

**自检通过条件**：C1\-C5 全部 pass。

---

### Step 6：输出

|字段|值|
|---|---|
|**step\_id**|`6_output`|
|**做什么**|将 Step 4 的内容 \+ Step 5 的自检结果 \+ 方法论附注，组装为最终报告|
|**不需要工具**|纯格式化|

**输入**：`Step 4, 5 output` \+ 全部 state

**输出**：`final_report`（Markdown 字符串）

**报告模板**：

```Markdown
# {行业名称}行业定义报告

> 行业定义分析 | 方法论文档 v{version} | 分析日期

{Step 4 生成的章节内容}

---

## 方法论附注

### 报告结构选择理由
{引用 Step 3 的 structure_rationale}

### 维度取舍记录
{引用 Step 2 的 selected + abandoned}

### 维度名称：置信度+依据
{引用 Step 4 中每个判断的置信度}

### 自检结果
{引用 Step 5}
```

---

## 四、Orchestrator 逻辑

```Python
# frost_agent.py — 伪代码骨架

from pydantic import BaseModel
from typing import Any
import json

# ─── 配置 ───
METHODOLOGY_PATH = "方法论-v2.md"
LLM_MODEL = "deepseek-v4-pro"
SEARCH_TOOL = "tavily"  # 或搜索 API

# ─── State Schema（见第二章）───
class StepOutput(BaseModel): ...
class ReportState(BaseModel): ...

# ─── 方法论加载 ───
def load_methodology() -> str: ...
def slice_methodology(step_id: str, methodology: str) -> str: ...

# ─── 搜索工具 ───
def search(query: str) -> list[dict]: ...

# ─── LLM 调用 ───
def call_llm(system_prompt: str, user_prompt: str) -> dict: ...

# ─── 步骤函数 ───
def step1_info_collection(state: ReportState, methodology: str) -> StepOutput: ...
def step2_dimension_screening(state: ReportState, methodology: str) -> StepOutput: ...
def step3_structure_decision(state: ReportState, methodology: str) -> StepOutput: ...
def step4_content_generation(state: ReportState, methodology: str) -> StepOutput: ...
def step5_self_check(state: ReportState, methodology: str) -> StepOutput: ...
def step6_output(state: ReportState) -> str: ...

# ─── 主流程 ───
STEPS = [
    ("1_info_collection",      step1_info_collection),
    ("2_dimension_screening",  step2_dimension_screening),
    ("3_structure_decision",   step3_structure_decision),
    ("4_content_generation",   step4_content_generation),
    ("5_self_check",           step5_self_check),
]

def run(industry_name: str) -> str:
    methodology = load_methodology()
    state = ReportState(
        methodology_version="v2",
        industry_name=industry_name,
    )
    
    for step_id, step_fn in STEPS:
        result = step_fn(state, methodology)
        state.steps.append(result)
        
        # 如果某步 confidence = "low"，打印警告但继续
        if result.confidence.startswith("low"):
            print(f"⚠️  {result.step_label} 置信度低: {result.confidence}")
    
    # Step 6: 组装最终报告
    final_report = step6_output(state)
    state.final_report = final_report
    
    return final_report


if __name__ == "__main__":
    import sys
    industry = sys.argv[1] if len(sys.argv) > 1 else "低空经济"
    report = run(industry)
    print(report)
```

---

## 五、给 Trae 的开发 brief

### 需要实现

|文件|内容|
|---|---|
|`frost_agent.py`|主流程（Orchestrator \+ 六步逻辑 \+ CLI 入口）|
|`models.py`|State Schema（StepOutput, ReportState, StepContext）|
|`methodology_loader.py`|加载 \+ 按步切片方法论文档|
|`requirements.txt`|pydantic, openai（或 deepseek sdk）, tavily\-python|

### 关键约束

1. **每一步的输出必须包含 ****`reasoning`**** 字段**——不能只有结论

2. **Confidence 必须标注**——高/中/低 \+ 一句依据

3. **Step 5 不通过 → 不允许直接输出**，打印警告并标记 `fixes_required`

4. **搜索必须至少 3 轮**，覆盖：行业定义 \+ 政策标准 \+ 边界争议

5. **方法论文档作为外部文件加载**，不硬编码在 prompt 里——方便后续改方法论不改代码

### 验收标准

- `python frost_agent.py "低空经济物流"` 能稳定产出报告

- 输出的方法论附注里能看到完整的维度取舍推理

- Step 5 自检能全部 pass

- 报告中不含竞争排名、市场份额、投资建议

