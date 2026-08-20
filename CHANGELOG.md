# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 的极简约定，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 注：`v5.2.0` 是首个正式 GitHub Release。在此之前项目于本仓库内迭代演进（六步流程 v1→v5.2、补搜机制 B1-2 v1.0→v1.4 等），完整历史见 `git log` 与 `开发日志/`、`架构设计/`。

## [5.2.0] - 2026-08-20

### Added

- **六步流程完整实现**（`demo2/`）：信息收集 → 维度筛选（H1-H4）→ 结构决策 → 内容生成 → 自检（C1-C5）→ 输出
- **harness 四组件**：SessionEventLog / CheckpointManager / TokenAudit / OutputSafety，全链路审计与崩溃恢复
- **B1-2 补搜迭代 v1.4（终版封存）**：前瞻继续论证范式，MAX=3 影子/赋权双模式，15 trace 三阶段实测（结束条件：MAX 放开至 >=4 或引入非碎片化搜索源）
- **Streamlit WebUI**（`webui/`）：六步流程可视化 + jsonl 时间线
- **测试基线**：demo2 51 项 + webui 25 项，全部 mock 化，无需 API key

### 变更说明

- LLM 端点默认值由硅基流动（SiliconFlow）改为 **DeepSeek 官方**（`https://api.deepseek.com/v1`），与 `.env.example` 对齐；代码常量与教学文档同步更新
- 补搜预算 MAX=3，影子/赋权双模式（请求数 <=10）
- 附带的历史 trace（15 个三阶段实测）为端点迁移前运行数据，其审计报表含旧端点价目烙印，属当时实况

> **已知边界**：仓库不再声明"品牌字样零残留"——代码与教学文档已清，但保留的历史 trace 数据（报告编号 F&S 缩写、审计报表 SiliconFlow 价目）为旧运行实况，保留用于审计背书。

### Fixed

- LLM 思考模式 content 空值导致的 Pydantic 校验失败
- Step 5 自检失败从"中断"改为"注入警告"继续
- 搜索全失败时终止循环（防死循环）
- 报告超长根因修正

[5.2.0]: https://github.com/paperpoon-lang/Industry-definition-agent/releases/tag/v5.2.0