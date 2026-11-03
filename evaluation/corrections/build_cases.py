#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建更正公告套件 cases.jsonl（人工核验的窄版真实错误语料）。

来源：巨潮资讯网（cninfo.com.cn）2023-2025 年 A 股定期报告更正公告，
检索+下载+pdftotext 后由 align_corrections.py 对齐出更正对，
再经人工逐档核验（对照原文抽查数值方向与列位）。

核验结论（2026-10-31，人工）：
  采纳 10 档（每档的抽样对已对照原文核实方向与列位）；
  弃用 3 档：丰光精密（182 对、多章节换行错列，机器对齐不可靠）/
           超讯通信（包裹行碎片）/ 硅烷科技（纯股东排名变动，无数值错误）。

错误分类：
  item      科目值更正（应收/存货/收入等绝对值）
  aggregate 合计类更正（合计/总计/资产负债率合计行）
  ratio     比率/增速更正（%、增长率、周转率、占比）
可判层：
  evidence_bound   原文表内自洽（或无法验证自洽），只能对照权威来源发现
  self_consistent  原文表内即可判矛盾（更正前合计 ≠ 更正前分项和）
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

import align_corrections as A

HERE = os.path.dirname(os.path.abspath(__file__))

# 人工核验：采纳的文档（txt 文件名 → 元数据）
ACCEPTED = {
    "430198_1223331648.txt": ("微创光电", "430198", "2022年年度报告（更正公告）",
                              "finalpage/2025-04-25/1223331648.PDF", "2025-04-25"),
    "830974_1221036030.txt": ("凯大催化", "830974", "2022年年度报告（更正公告）",
                              "finalpage/2024-08-28/1221036030.PDF", "2024-08-28"),
    "831039_1216809130.txt": ("国义招标", "831039", "2022年年度报告（更正公告）",
                              "finalpage/2024-06-27/1220484020.PDF", "2024-06-27"),
    "831305_1216861209.txt": ("海希通讯", "831305", "2023年年度报告（更正公告）",
                              "finalpage/2024-08-28/1216861209.PDF", "2024-08-28"),
    "832089_1219540094.txt": ("禾昌聚合", "832089", "2023年年度报告（更正公告）",
                              "finalpage/2024-06-27/1219540094.PDF", "2024-06-27"),
    "833455_1223558481.txt": ("汇隆活塞", "833455", "2024年年度报告（更正公告）",
                              "finalpage/2025-05-15/1223558481.PDF", "2025-05-15"),
    "833914_1217239300.txt": ("远航精密", "833914", "2023年年度报告（更正公告）",
                              "finalpage/2024-07-02/1217239300.PDF", "2024-07-02"),
    "835179_1224615810.txt": ("凯德石英", "835179", "2025年一季度报告（更正公告）",
                              "finalpage/2025-08-28/1224615810.PDF", "2025-08-28"),
    "839719_1220521611.txt": ("宁新新材", "839719", "2023年年度报告（更正公告）",
                              "finalpage/2024-07-02/1220521611.PDF", "2024-07-02"),
    "872953_1224613089.txt": ("国子软件", "872953", "2025年半年度报告（更正公告）",
                              "finalpage/2025-08-28/1224613089.PDF", "2025-08-28"),
}

_AGG_RE = re.compile(r"合计|总计|总资产|总收入|总成本|小计")
_RATIO_RE = re.compile(r"%|率|占比|比例|增长|增速|周转|流动比率|保障倍数")


def classify(label, unit):
    t = label or ""
    if _AGG_RE.search(t):
        return "aggregate"
    if (unit or "") in ("%",) or _RATIO_RE.search(t):
        return "ratio"
    return "item"


def fmt_date(ts_ms):
    import datetime
    return datetime.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")


def main():
    manifest = {x["txt"]: x for x in json.load(open("manifest_raw.json", encoding="utf-8"))}
    cases = []
    n = 0
    for fname, (name, code, title, url, date_hint) in sorted(ACCEPTED.items()):
        pairs = A.parse_file(os.path.join(HERE, "txt", fname))
        # 同一 (label, before, after) 在不同章节重复披露 → 只保留首见
        seen = set()
        uniq = []
        for p in pairs:
            key = (p["label"], p["before"], p["after"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        m = manifest.get(fname, {})
        for p in uniq:
            n += 1
            cases.append({
                "id": f"CR{n:03d}",
                "stock_code": code,
                "stock_name": name,
                "ann_title": title,
                "ann_url": "http://static.cninfo.com.cn/" + url,
                "ann_date": date_hint,
                "align_kind": p["kind"],
                "src_line": p["line"],
                "label": p["label"],
                "before": p["before"],
                "after": p["after"],
                "unit": p["unit"],
                "err_class": classify(p["label"], p["unit"]),
                "verified": True,
            })
    with open(os.path.join(HERE, "cases.jsonl"), "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    by_class = defaultdict(int)
    for c in cases:
        by_class[c["err_class"]] += 1
    print(f"cases.jsonl：{len(cases)} 对（{len(ACCEPTED)} 档公告）")
    print("错误分类：", dict(by_class))


if __name__ == "__main__":
    main()
