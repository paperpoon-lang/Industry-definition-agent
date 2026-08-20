#!/usr/bin/env python3
"""验证 critic 两个主张：gap_type 占比迁移 + Step5 自检 pass 率。"""
import json
from collections import Counter

S2 = {'0b8a65db2d43': '钙钛矿', '69673a7735cd': '垂直农业', 'fef3576de7a0': '脑机接口',
      '4d43509b8bbe': '培养肉', 'ac7fa4d1b09c': '固态电池'}
S3 = {'4c73eac12936': '钙钛矿', '76262c14955c': '垂直农业', 'c50a2a84b625': '脑机接口',
      '9f5562941e9e': '培养肉', 'ffa35be3dd7b': '固态电池'}


def dist(TR, label):
    c = Counter()
    for t in TR:
        with open(f"logs/{t}.jsonl") as f:
            for line in f:
                d = json.loads(line)
                if d.get("event_type") == "search_gap_record" and "justification_history" in d.get("data", {}):
                    c.update(d["data"].get("gap_types", []))
                    break
    tot = sum(c.values())
    print(label, dict(c), "共", tot, {k: f"{v/tot:.0%}" for k, v in c.items()})


dist(S2, "MAX=3终轮gap_types:")
dist(S3, "MAX=5终轮gap_types:")

print()
print("--- Step5 自检结果 ---")
for t in list(S2) + list(S3):
    r = "无step5完成事件"
    with open(f"logs/{t}.jsonl") as f:
        for line in f:
            d = json.loads(line)
            if d.get("event_type") == "step_complete" and d.get("data", {}).get("step_id", "").startswith("5_self"):
                r = json.dumps(d.get("data", {}), ensure_ascii=False)[:130]
                break
    print(t[:8], r)
