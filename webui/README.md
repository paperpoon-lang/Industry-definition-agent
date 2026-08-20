# 行业定义 Agent Web UI

行业定义 Agent v5.2 的浏览器界面：输入行业名 → 实时查看六步执行过程
（含 FM 审查/补搜原因级别的子事件卡片）→ 页面内阅读/下载报告。

仅真实 API 模式（界面无 Mock 选项）。demo2 后端代码零改动。

## 安装（一次性）

```bash
cd /Users/paper/trae_project/行业定义agent/webui
uv venv .venv-ui --python 3.12
uv pip install -r ../demo2/requirements.txt -r requirements-ui.txt
```

## 启动

```bash
cd /Users/paper/trae_project/行业定义agent/webui
source .venv-ui/bin/activate
streamlit run app.py
```

浏览器自动打开 `http://localhost:8501`。

## 使用

1. 输入行业名称 → 点「开始生成」
2. 双层时间线实时展示：顶部六步徽章 + 每步内子事件卡片
   （🧠 FM 审查发现缺口及原因 / ⚡ 补搜轮次 / 📊 搜索终态 / 💰 成本）
3. 完成后报告渲染在页面下方，可下载 .md
4. 侧边栏可回看历史报告（demo2/reports/）

## 注意事项

- **关闭页面不会停止任务**：子进程会继续跑完（真实 API 会继续产生费用）。
  停止请用页面上的「停止」按钮。
- 僵尸子进程清理：`pkill -f frost_agent.py`
- 同一时刻只允许一个任务运行（进程级全局锁）；停止后可用 CLI 恢复：
  `cd ../demo2 && python frost_agent.py "行业名" --resume`
- 产物（报告/日志/checkpoint）全部落在 `demo2/` 对应目录，webui/ 不产生数据文件

## 开发验证（不花钱跑通 UI）

UI 无 Mock 控件，但子进程继承环境变量，启动前注入即可：

```bash
MOCK_LLM=true MOCK_SEARCH=true streamlit run app.py   # 全 Mock，2-5 秒跑完
MOCK_LLM=true streamlit run app.py                    # 半 Mock：真实搜索+FM 审查，LLM 预设
```

单测：`.venv-ui/bin/python -m pytest tests/ -q`
