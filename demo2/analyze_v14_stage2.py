#!/usr/bin/env python3
"""B1-2 v1.4 阶段二（赋权模式）对照分析。

三个观测项：
1. 理由门控行为：stop_reason / valid_history / 轮数 / 成本
2. query 新颖性（workbuddy 建议①）：每轮补搜 query 与历史 query 的 bigram-Jaccard 相似度
   + new_direction 跨轮重复检测（承诺效应是否防止同义改写）
3. gap_type 门控对照（workbuddy 建议②）：若按确定性规则"本轮全部缺口为非Tavily可闭合
   类型 → 停"，各行业会停在哪一轮，与实际对比
"""
import json
import os
import subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))

TRACES = {  # 阶段二（赋权模式）5行业 trace（钙钛矿用重跑后的完整 trace）
    "0b8a65db2d43": "钙钛矿",
    "69673a7735cd": "室内垂直农业",
    "fef3576de7a0": "脑机接口",
    "4d43509b8bbe": "细胞培养肉",
    "ac7fa4d1b09c": "固态电池",
}

# gap_type 可闭合性口径（对照分析用，不影响生产）
# not_found=换方向可能搜到(可闭合)；snippet_too_shallow=需全文(Tavily给不了)；
# source_tier=需官方/付费源(Tavily基本给不了)
NON_TAVILY_TYPES = {"snippet_too_shallow", "source_tier"}
STRICT_TYPES = {"not_found", "snippet_too_shallow", "source_tier"}  # workbuddy 宽口径


def bigrams(s):
    s = "".join(s.split()).lower()
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def jaccard(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def load_record(tid):
    with open(f"logs/{tid}.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if d.get("event_type") == "search_gap_record" and "justification_history" in d.get("data", {}):
                return d
    return None


def load_round_queries(tid):
    """从 supplement_search_done 事件提取每轮实际执行的补搜 query。"""
    rounds = []
    with open(f"logs/{tid}.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if d.get("event_type") == "supplement_search_done":
                rounds.append(d["data"].get("queries", []))
    return rounds


def get_cost(tid):
    path = f"logs/{tid}_token_audit.md"
    if not os.path.exists(path):
        return "?"
    for l in open(path):
        if "总成本" in l:
            return l.strip().split("：")[-1].strip()
    return "?"


print("=" * 70)
print("观测项1：理由门控行为（赋权模式 shadow=False）")
print("=" * 70)
all_rounds_queries = {}
for tid, name in TRACES.items():
    rec = load_record(tid)
    data = rec["data"]
    print(f"{name}: stop={data['stop_reason']} rounds={data['supplement_rounds']} "
          f"valid={data['justification_valid_history']} total_queries={len(data.get('queries_used', []))} "
          f"cost={get_cost(tid)}")

print()
print("=" * 70)
print("观测项2：query 新颖性 + new_direction 承诺效应")
print("=" * 70)
for tid, name in TRACES.items():
    rec = load_record(tid)
    data = rec["data"]
    sq_by_round = load_round_queries(tid)
    static_queries = list(data.get("queries_used", [])[:3])  # 首轮3个静态 query
    jh = data.get("justification_history", [])
    print(f"\n--- {name} ---")
    history = list(static_queries)
    for r, queries in enumerate(sq_by_round, 1):
        for q in queries:
            sims = [(jaccard(q, h), h) for h in history]
            max_sim, most_like = max(sims, key=lambda x: x[0]) if sims else (0.0, "-")
            flag = " ⚠️高相似" if max_sim >= 0.6 else ""
            print(f"  R{r} q: {q[:44]:<46} maxSim={max_sim:.2f}{flag}")
            if max_sim >= 0.6:
                print(f"        ≈ {most_like[:44]}")
            history.append(q)
    # new_direction 跨轮重复（R3 vs R2 / R2 vs R1）
    dirs = []
    for j in jh:
        if isinstance(j, list):
            ds = [it.get("new_direction", "") for it in j if isinstance(it, dict)]
            dirs.append(" | ".join(ds))
        else:
            dirs.append("")
    for i in range(1, len(dirs)):
        sim = jaccard(dirs[i], dirs[i-1]) if dirs[i] and dirs[i-1] else 0.0
        mark = " ⚠️方向声明跨轮重复" if sim >= 0.55 else ""
        print(f"  dir 相似度 R{i}→R{i+1}: {sim:.2f}{mark}")

print()
print("=" * 70)
print("观测项3：gap_type 门控对照（若按确定性规则止损）")
print("=" * 70)
for tid, name in TRACES.items():
    rec = load_record(tid)
    rgt = rec["data"].get("round_gap_types", [])
    print(f"\n--- {name} ---")
    stopped_strict = stopped_wide = None
    for r, types in enumerate(rgt, 1):
        all_strict = types and all(t in NON_TAVILY_TYPES for t in types)
        all_wide = types and all(t in STRICT_TYPES for t in types)
        tag = ""
        if all_strict and stopped_strict is None:
            stopped_strict = r
            tag += " ←严格口径此处停"
        if all_wide and stopped_wide is None:
            stopped_wide = r
            tag += " ←宽口径此处停"
        print(f"  R{r} types={types}{tag}")
    actual = rec["data"]["supplement_rounds"]
    s1 = f"严格口径停于R{stopped_strict}" if stopped_strict else "严格口径全程不停"
    s2 = f"宽口径停于R{stopped_wide}" if stopped_wide else "宽口径全程不停"
    print(f"  对照：{s1}；{s2}；实际跑满 R{actual}")
