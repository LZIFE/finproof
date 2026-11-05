#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎优先管线 · 证据对装配与呈现层（v3.4 薄封装）。

核心对账已提升为引擎子命令 `prefilter_scan`（finproof_calc.py v2.20.0）：
token 精确匹配/公司小节锚定/全局去重/多值冲突弃权/单位上下文锚定/F 类
结构性缺陷——全部零 LLM。本脚本只做三件事：
  1. 证据对装配：evidence 目录逐文件跑 align_corrections 解析（PDF 特有），
     按文件名前缀归属公司；
  2. 调引擎 prefilter_scan 得例外清单；
  3. 呈现：终稿骨架（模型补 D/F）与摘要视图（模型复核输入 ~2KB）。

证据获取（检索+下载）用 fetch_announcements.py。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../../finproof-verifier/skills/finproof-verification/bin")))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "../corrections")))

import finproof_calc as fc  # noqa: E402
import align_corrections as A  # noqa: E402

COMPANY_BY_PREFIX = {
    "830974": "凯大催化", "835179": "凯德石英", "832089": "禾昌聚合",
    "430198": "微创光电", "831039": "国义招标", "872953": "国子软件",
    "833455": "汇隆活塞", "831305": "海希通讯", "839719": "宁新新材",
    "833914": "远航精密", "430510": "丰光精密",
}


def build_pairs(evidence_dir):
    """证据目录 → 证据对列表（align 解析，公司按文件名前缀归属）。"""
    pairs = []
    seen = set()
    for fname in sorted(os.listdir(evidence_dir)):
        if not fname.endswith(".txt"):
            continue
        code = fname.split("_")[0]
        company = COMPANY_BY_PREFIX.get(code, code)
        for p in A.parse_file(os.path.join(evidence_dir, fname)):
            key = (company, p["label"], p["before"], p["after"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"company": company, "code": code, "label": p["label"],
                          "before": p["before"], "after": p["after"], "unit": p["unit"] or "元"})
    return pairs


def render_draft(out, report, path, n_pairs):
    sem = ""
    m = re.search(r"(综合观察.*?)(\n（注：.*)?\Z", report, re.S)
    if m:
        sem = m.group(1)
    sample = out["violations"][::max(1, len(out["violations"]) // 5)][:5]
    draft = ["# 鉴融审计报告（管线终稿骨架——引擎预对账，模型复核语义与抽检）", "",
             f"> 管线对账：{n_pairs} 对证据 / 0 token；例外 {len(out['violations'])} 硬错 + "
             f"{len(out['tolerance'])} 容差内 + {len(out['abstains'])} 弃权 + {len(out['unclaimed'])} 未引用", "",
             "## A 类：数值硬错（S3 引用作废数据，须改数）", "",
             "| 公司 | 指标 | 报告值(行) | 更正后值 | 相对差 | 规则 |", "|---|---|---|---|---|---|"]
    for v in out["violations"]:
        draft.append(f"| {v['company']} | {v['label'][:16]} | {v['report_value']}（{v['report_line']}）"
                     f" | {v['corrected_value']} | {v.get('rel_diff_pct') or '—'}% | S3 |")
    draft += ["", "## B 类：容差内引用更新（须更新引用，不判数值错误）", "",
              "| 公司 | 指标 | 报告值 | 更正后值 |", "|---|---|---|---|"]
    for v in out["tolerance"]:
        draft.append(f"| {v['company']} | {v['label'][:16]} | {v['report_value']} | {v['corrected_value']} |")
    draft += ["", "## C 类：引擎弃权（附方向说明）", ""]
    for v in out["abstains"]:
        draft.append(f"- {v['company']} {v['label'][:14]}：{v['report_value']} → {v['corrected_value']}"
                     f"（{v.get('note') or v.get('reason', '')[:40]}）")
    draft += ["", "## D 类：定性断言（模型按规则库 Q1/Q2/Q3/S1 复核本段）", "", sem or "（未找到综合观察段）", "",
              "## E 类：抽检样本（模型对照证据原文抽验管线判定，≥5 条）", ""]
    for v in sample:
        draft.append(f"- 抽检：{v['company']} {v['label'][:14]} {v['report_value']} → {v['corrected_value']}"
                     f"（{v['report_line']}：{v['report_excerpt'][:40]}）")
    draft += ["", "## F 类：结构性缺陷（管线机械检测——模型复核补漏，不重复誊抄）", ""]
    draft += [f"- {x}" for x in out["structural"]] or ["- （无机械可检结构性缺陷）"]
    open(path, "w", encoding="utf-8").write("\n".join(draft))


def render_summary(out, report, path, n_pairs):
    sem = ""
    m = re.search(r"(综合观察.*?)(\n（注：.*)?\Z", report, re.S)
    if m:
        sem = m.group(1)
    sample = out["violations"][::max(1, len(out["violations"]) // 5)][:5]
    sv = ["# 管线摘要视图（模型复核输入——全文骨架另存，不进模型上下文）", "",
          f"对账：{n_pairs} 对 / 0 token；硬错 {len(out['violations'])}、容差内 {len(out['tolerance'])}、"
          f"弃权 {len(out['abstains'])}、未引用 {len(out['unclaimed'])}；A/B/C/F 明细见骨架与 JSON", "",
          "## F 类结构候选", *([f"- {x}" for x in out["structural"]] or ["- 无"]), "",
          "## D 类待判语义段（综合观察原文）", sem or "（无）", "",
          "## E 类抽检样本（含报告行摘录）", ""]
    for v in sample:
        sv.append(f"- {v['company']} {v['label'][:12]}：报告 {v['report_value']}（{v['report_line']}："
                  f"{v['report_excerpt'][:36]}）→ 更正后 {v['corrected_value']} | {v.get('rel_diff_pct') or '—'}%")
    open(path, "w", encoding="utf-8").write("\n".join(sv))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--out", default="/tmp/prefilter.json")
    ap.add_argument("--draft", default=None)
    ap.add_argument("--summary-view", default=None)
    ap.add_argument("--tol-pp", type=float, default=0.5)
    ap.add_argument("--tol-rel", type=float, default=0.001)
    args = ap.parse_args()

    report = open(args.report, encoding="utf-8").read()
    pairs = build_pairs(args.evidence_dir)
    out = fc.prefilter_scan(report, pairs, tol_pp=args.tol_pp, tol_rel=args.tol_rel)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["summary"], ensure_ascii=False))
    if args.draft:
        render_draft(out, report, args.draft, len(pairs))
        print(f"终稿骨架已写出 {args.draft}")
    if args.summary_view:
        render_summary(out, report, args.summary_view, len(pairs))
        print(f"摘要视图已写出 {args.summary_view}（{os.path.getsize(args.summary_view)} B）")


if __name__ == "__main__":
    main()
