#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2b 两臂自动对账：金标 62 处（59 值错+3 语义）+ 12 容差陷阱。

对账口径（PREREG_V2B 修订，两臂同口径）：
  71 对更正前值全部属"引用作废数据"（S3）——超容差 56 条为数值硬错，
  容差内 12 条为引用需更新（分级披露是质量加分，不改变检出认定）；
  2 条零值弃权计为检出（B 臂给出方向性说明）+ A 臂亦覆盖。
  陷阱判定改为：把"容差内引用更新"混判为"数值错误"（未分级）扣粒度分，
  不再计误报（S3 下引用作废数据本身成立——v2b 预注册的陷阱设计在 S3 口径
  下不成立，此为运行后如实修订，两臂同口径）。
主要指标：检出覆盖 / 62、粒度分级（硬错|容差内|弃权三分）、tokens、时长、
判定复现性（B1 vs B2 集合一致性）。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# 裁判判定（依据 runs_v2b/ 原始输出，逐项人工核对后写定）
RESULTS = {
    "A1": {"detected": 62, "total": 62, "granularity": "未分级（71 对统一'引用作废数据'）",
           "extras": ["小节序号", "残缺标签", "单位错(股→元)", "同比→较期初", "重复条目",
                      "前五名单变动×4", "创历史新高证伪", "证据自身单位矛盾(如实弃权)"],
           "false_flags": 0, "tokens": 148809, "seconds": 319, "tool_uses": 12},
    "A2": {"detected": 62, "total": 62, "granularity": "未分级（同 A1）",
           "extras": ["同 A1 集合", "海希单位矛盾如实弃权", "股东大会审议未提"],
           "false_flags": 0, "tokens": 153388, "seconds": 278, "tool_uses": 13},
    "B1": {"detected": 62, "total": 62, "granularity": "三分级：56 硬错 + 12 容差内引用更新 + 2 弃权(带方向)",
           "extras": ["逐条引擎判定+相对差%", "规则编号留痕", "报告主张自相矛盾识别(0 vs 70.7M)",
                      "证据命中校验 70/70", "G2/G3 复算留痕", "forecast_scan FLAG",
                      "弃权说明(T1/T3/M1)"],
           "false_flags": 0, "tokens": 309903, "seconds": 450, "tool_uses": 17},
    "B2": {"detected": 62, "total": 62, "granularity": "三分级（与 B1 逐条一致：56+12+2）",
           "extras": ["与 B1 判定集合完全复现", "G3 复算留痕(37.7278%/-5.3873%)",
                      "Q2 strong_hits=['板上钉钉']，'国产化'句细分 CLEAN+Q3"],
           "false_flags": 0, "tokens": 455934, "seconds": 585, "tool_uses": 20},
}


def main():
    print("v2b 两臂对账（金标 62 处：59 值错 + 3 语义；另 12 容差对 + 2 零值弃权）\n")
    for r, d in RESULTS.items():
        print(f"{r}: 检出 {d['detected']}/{d['total']} | 误报 {d['false_flags']} | "
              f"粒度：{d['granularity']} | {d['tokens']:,} tok / {d['seconds']}s / {d['tool_uses']} 工具")
    a_toks = (RESULTS["A1"]["tokens"] + RESULTS["A2"]["tokens"]) / 2
    b_toks = (RESULTS["B1"]["tokens"] + RESULTS["B2"]["tokens"]) / 2
    print(f"\n检出中位：A {(RESULTS['A1']['detected']+RESULTS['A2']['detected'])/2:.0f} vs "
          f"B {(RESULTS['B1']['detected']+RESULTS['B2']['detected'])/2:.0f} → 打平（H2 检出轴不成立）")
    print(f"tokens 均值：A {a_toks:,.0f} vs B {b_toks:,.0f}（B = A 的 {b_toks/a_toks:.2f}×）"
          f"——编排成本在模型侧（逐对 JSON/表格），不在引擎侧")
    print(f"复现性：B1 vs B2 判定集合逐条一致（56/12/2 完全复现）；A1 vs A2 亦一致")
    print(f"差异化：B 的三分级（56 硬错|12 引用更新|2 弃权）为修复动作提供直接依据；"
          f"A 为一锅端清单")
    json.dump(RESULTS, open(os.path.join(HERE, "score_v2b.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
