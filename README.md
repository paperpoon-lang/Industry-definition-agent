# Industry-definition-agent — 行业定义报告自动生成 Agent

> **v5.2.0**（首个正式 Release）· 技术 Demo · GitHub: [paperpoon-lang/Industry-definition-agent](https://github.com/paperpoon-lang/Industry-definition-agent)

输入一个行业名称，自动产出符合行业定义方法论的行业定义报告。核心是六步流程 Agent + 补搜迭代（B1-2 v1.4）与全链路审计 harness。

![CI](https://github.com/paperpoon-lang/Industry-definition-agent/actions/workflows/tests.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Release](https://img.shields.io/github/v/release/paperpoon-lang/Industry-definition-agent)

## 快速开始（3 步）

1. 克隆仓库：

```bash
git clone https://github.com/paperpoon-lang/Industry-definition-agent.git
cd Industry-definition-agent
```

2. 安装依赖并配置 `.env`：

```bash
pip install -r demo2/requirements.txt
cp demo2/.env.example demo2/.env   # 填入 DeepSeek + Tavily 的 API Key
```

3. 运行一个行业示例：

```bash
python3 demo2/frost_agent.py "钙钛矿"
```

报告输出到 `demo2/reports/`。完整过程日志（jsonl + 成本审计）写入 `demo2/logs/`。

## 六步流程

1. **信息收集** — 并行搜索（Tavily）+ LLM 总结，内置 B1-2 补搜循环
2. **维度筛选** — 应用 H1-H4 原则选出核心维度
3. **结构决策** — 设计报告章节结构
4. **内容生成** — 撰写完整报告正文
5. **自检** — 独立 Evaluator 审查（C1-C5），失败时注入警告
6. **输出** — 组装报告 + Token/成本统计 + 写入文件

## WebUI

```bash
pip install -r webui/requirements-ui.txt
streamlit run webui/app.py
```

## 目录结构

```
Industry-definition-agent/
├── demo2/                 # 主交付：v5.2 完整实现
│   ├── frost_agent.py     # 主程序（Orchestrator + 六步 + CLI）
│   ├── models.py          # Pydantic 数据模型
│   ├── search.py          # 并行搜索 + 补搜循环
│   ├── methodology_loader.py
│   ├── harness/           # SessionEventLog / Checkpoint / TokenAudit / OutputSafety
│   ├── 方法论/            # 方法论切片（H1-H4、自检清单等，运行时加载）
│   ├── tests/             # 51 项测试（全 mock，无 API key）
│   └── requirements.txt
├── webui/                 # Streamlit WebUI（25 项纯函数测试）
├── CHANGELOG.md
├── LICENSE                # MIT
└── .github/workflows/     # CI：demo2 + webui 测试
```

## 已知边界

- **约 84% 的残留缺口属结构性不可达**（★★★★☆ 定性，单人分类）：Tavily 提供的是片段级而非全文级信息，官方全文/一手文件/公开渠道难被索引时，多轮补搜只能把缺口定位到精确坐标、无法直接补全。
- **阶段三方向**：接入非碎片化搜索源（官方标准平台 / SEC / 学术库）以改变缺口结构。

## 实测数据（2026-08，★★★★★ 一手实测）

> **成本口径说明**：以下成本为 LLM 端点迁移前的**硅基流动（SiliconFlow）时期**（2026-06 定价）实测，DeepSeek 官方端点迁移后成本未复测。随仓库附带的 15 个 trace 即这些实测运行数据，其审计报表含当时端点价目烙印。

- 15 个实验 trace（三阶段：影子 MAX=3 / 赋权 MAX=3 / 赋权 MAX=5）
- 成本约 ¥0.21–0.26 / 行业（当时端点，TokenAudit 实测）
- Step 5 自检 pass 10/10
- 测试基线：demo2 51 + webui 25 全绿

## 测试

```bash
cd demo2 && python3 -m pytest tests/ -q   # 51 passed
cd webui && python3 -m pytest tests/ -q   # 25 passed
```

全部 mock 化，无需 API key，可在 CI 中无密钥运行。

## 许可证

本项目使用 [MIT License](LICENSE)。