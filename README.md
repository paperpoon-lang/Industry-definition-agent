#  Industry-definition-agent — Demo (v4)

## 功能

输入行业名称，自动产出符合行业定义方法论的行业定义报告。六步流程：

1. **信息收集** — 并行搜索 + LLM 总结
2. **维度筛选** — 应用 H1-H4 原则选出核心维度
3. **结构决策** — 设计报告章节结构
4. **内容生成** — 撰写完整报告正文
5. **自检** — 独立 Evaluator 审查（C1-C5），失败时注入警告
6. **输出** — 组装报告 + Token 统计 + 写入文件

## 环境准备

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 `.env`

复制模板并填入你的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`，填入：

```env
LLM_API_KEY=sk-xxx          # 硅基流动 API Key
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Pro
TAVILY_API_KEY=tvly-dev-xxx # Tavily 搜索 API Key
```

## 使用

```bash
# 基本用法（真实 API）
python3 frost_agent.py "行业名称"

# Mock 模式（不调用 API，快速验证流程）
python3 frost_agent.py "行业名称" --mock

# 从上次中断的 Checkpoint 恢复
python3 frost_agent.py "行业名称" --resume
```

**示例**：

```bash
python3 frost_agent.py "低空经济物流"
python3 frost_agent.py "新能源汽车"
python3 frost_agent.py "人工智能医疗"
```

## 输出

报告保存在 `reports/{行业名}_行业定义报告.md`。

## 文件结构

```
demo/
├── frost_agent.py            # 主程序（Orchestrator + 六步 + CLI 入口）
├── models.py                 # Pydantic 数据模型
├── methodology_loader.py     # 方法论切片加载器
├── context_builder.py        # 四层上下文组装器
├── evaluator.py              # 独立 Evaluator（Step 5）
├── search.py                 # 并行搜索 + 截断压缩
├── requirements.txt          # 依赖声明
├── .env.example              # 环境变量模板
├── 方法论-v2.md              # 方法论文档
├── harness/
│   ├── circuit_breaker.py    # 打桩：call_with_retry
│   ├── session_log.py        # 打桩：SimpleLogger
│   └── checkpoint.py         # 打桩：save/load JSON
├── reports/                  # 生成的报告
├── checkpoints/               # 崩溃恢复点
└── test_results/             # 测试结果（JSON 报告 + 输出日志）
```

## 测试

项目内置 `frost-test-runner` 智能体，可批量测试多个行业并生成测试报告。在 Trae 中输入 `@frost-test-runner` 即可调用。
