#!/usr/bin/env python3
"""B1-2 v1.4 阶段一影子实测数据提取。"""
import json
import subprocess
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

v14 = []
for t in subprocess.run("ls -t logs/*.jsonl", shell=True, capture_output=True, text=True).stdout.split():
    with open(t) as f:
        for line in f:
            d = json.loads(line)
            if d.get("event_type") == "search_gap_record" and "justification_history" in d.get("data", {}):
                v14.append((t, d))
                break
    if len(v14) >= 5:
        break

for t, rec in v14:
    tid = os.path.basename(t).replace(".jsonl", "")
    data = rec["data"]
    cost = ""
    audit = "logs/{}_token_audit.md".format(tid)
    if os.path.exists(audit):
        for l in open(audit):
            if "总成本" in l:
                cost = l.strip()
                break
    industry = rec.get("industry", "?")
    jh = data.get("justification_history", [])
    jv = data.get("justification_valid_history", [])
    print("=== {} ({})".format(industry, tid))
    print("  stop_reason: {} | shadow: {} | rounds: {} | {}".format(
        data["stop_reason"], data.get("shadow_mode"), data["supplement_rounds"], cost))
    print("  valid_history: {}".format(jv))
    print("  round_gap_types: {}".format(data.get("round_gap_types")))
    for i, j in enumerate(jh):
        if isinstance(j, list) and j:
            for item in j[:2]:
                if isinstance(item, dict):
                    print("    R{}: gap={} dir={} reach={}".format(
                        i + 1, item.get("target_gap_index"),
                        str(item.get("new_direction"))[:60],
                        str(item.get("reachability"))[:50]))
        else:
            print("    R{}: 理由缺失/无效格式".format(i + 1))
