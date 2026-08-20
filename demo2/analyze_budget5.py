#!/usr/bin/env python3
"""MAX=5 预算放开实验：方向声明跨轮相似度 + 残留缺口分析。"""
import json

TRACES = {
    "4c73eac12936": "钙钛矿",
    "76262c14955c": "垂直农业",
    "c50a2a84b625": "脑机接口",
    "9f5562941e9e": "培养肉",
    "ffa35be3dd7b": "固态电池",
}


def bigrams(s):
    s = "".join(s.split()).lower()
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def jac(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / len(A | B) if A and B else 0.0


for tid, name in TRACES.items():
    with open(f"logs/{tid}.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if d.get("event_type") == "search_gap_record" and "justification_history" in d.get("data", {}):
                dd = d["data"]
                jh = dd["justification_history"]
                dirs = []
                for j in jh:
                    if isinstance(j, list):
                        dirs.append(" | ".join(it.get("new_direction", "") for it in j if isinstance(it, dict)))
                    else:
                        dirs.append("")
                print(f"--- {name} ---")
                prev = None
                for i, dr in enumerate(dirs, 1):
                    if prev is not None:
                        s = jac(dr, prev)
                        mark = " ⚠️措辞变体" if s >= 0.5 else ""
                        print(f"  R{i-1}→R{i} dir相似度: {s:.2f}{mark}")
                    prev = dr
                rg = dd.get("remaining_gaps", [])
                print(f"  残留缺口数: {len(rg)}")
                for g in rg[:2]:
                    print(f"    · {str(g)[:70]}")
                break
