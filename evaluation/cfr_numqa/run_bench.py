#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CFR-NumQA 跑分：用 1,016 道中文 A 股年报题验证鉴融的确定性计算链路。

数据集：CFR-NumQA（吉林师范大学，CC BY 4.0）103 份 A 股年报、1,016 题
题目自带金标准操作数（meta.value / meta.values / meta.unit），所以能纯机械评分。

三类题：
  extraction     540 道  给数值+单位，验证抽取与单位换算
  yoy_compare    386 道  给两期数值，验证同比计算
  cross_company   90 道  给两家公司数值，验证比较方向

边界：本脚本验证的是「算得对不对」，不是「能不能从年报里找对数字」——
后者需要模型做检索，本脚本只用题目给定的金标准操作数。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.normpath(os.path.join(HERE, "../../finproof-verifier/skills/finproof-verification/bin"))
sys.path.insert(0, BIN)
import finproof_calc as fc  # noqa: E402


def check_extraction(cs):
    ok, bad = 0, []
    for c in cs:
        m = c["meta"]
        v, u = m.get("value"), m.get("unit")
        vals = fc.extract_financial_values(c["answer"])
        got = vals[0]["value_in_yuan"] if vals else None
        exp = float(fc.convert_to_yuan(v, u)) if (v is not None and u) else None
        if got is not None and exp is not None and abs(got - exp) <= max(1.0, abs(exp) * 1e-9):
            ok += 1
        else:
            bad.append((c["id"], c["answer"], got, exp))
    return ok, bad


def check_yoy(cs):
    ok, bad = 0, []
    for c in cs:
        vals = c["meta"].get("values") or []
        if len(vals) < 2:
            continue
        calc, _ = fc.yoy(vals[1], vals[0])
        m = re.match(r"^\s*([+-]?[\d.]+)\s*%", c["answer"])
        if m and abs(calc - float(m.group(1))) <= 0.01:
            ok += 1
        else:
            bad.append((c["id"], c["answer"], round(calc, 4), vals))
    return ok, bad


def check_cross(cs):
    ok, bad = 0, []
    for c in cs:
        m = c["meta"]
        comps, vals = m.get("companies") or [], m.get("values_yuan") or []
        if len(comps) < 2 or len(vals) < 2:
            continue
        expect = comps[0] if vals[0] > vals[1] else comps[1]
        if c["answer"].strip() == expect:
            ok += 1
        else:
            bad.append((c["id"], c["answer"], expect, vals))
    return ok, bad


def main():
    path = os.path.join(HERE, "qa_seed.jsonl")
    cases = [json.loads(l) for l in open(path, encoding="utf-8")]
    groups = {
        "extraction": (check_extraction, [c for c in cases if c["type"] == "extraction"]),
        "yoy_compare": (check_yoy, [c for c in cases if c["type"] == "yoy_compare"]),
        "cross_company": (check_cross, [c for c in cases if c["type"] == "cross_company"]),
    }
    total_ok = total = 0
    print(f"\nCFR-NumQA · {len(cases)} 题（中文 A 股年报）")
    print("=" * 56)
    for name, (fn, cs) in groups.items():
        ok, bad = fn(cs)
        total_ok += ok
        total += len(cs)
        print(f"  {name:16} {ok}/{len(cs)} = {ok/len(cs)*100:5.1f}%")
        for b in bad[:3]:
            print(f"     ✗ {b}")
    print("=" * 56)
    print(f"  合计 {total_ok}/{total} = {total_ok/total*100:.2f}%")
    json.dump({"total": total, "correct": total_ok, "accuracy": total_ok / total},
              open(os.path.join(HERE, "score.json"), "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
