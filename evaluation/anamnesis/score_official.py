#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 AnamnesisBench 官方口径给 run_bench.py 打分，便于与 ood_reference.json 对照。

官方口径（源自 results/ood_reference.json）：
  in_scope_gated  = 排除 13 种 v1 未覆盖的 novel kind 后的案例
  catch_rate      = 正确判为 violation 的 / 全部 violation
  false_flag_rate = 误判为 violation 的 clean / 全部 clean
  error_rate      = 弃权或无法解析 / 全部 in_scope
"""
import json, sys
from collections import defaultdict
import run_bench as rb

NOVEL_KINDS = {
    "axis_unit_mismatch", "cross_section_mismatch", "currency_mixing", "date_inconsistency",
    "double_counted_flow", "dual_axis_scale_inversion", "duplicate_row", "license_mismatch",
    "negative_value_in_pie", "pii_in_body", "retracted_citation", "stacked_bar_total_mismatch",
    "stale_disclaimer",
}


def official_score(path, label):
    cases = [json.loads(l) for l in open(path, encoding="utf-8")]
    scope = [c for c in cases if (c.get("kind") not in NOVEL_KINDS)]
    viol = [c for c in scope if c["label"] == "violation"]
    clean = [c for c in scope if c["label"] == "consistent"]
    caught = escaped = abst_v = 0
    false_flag = tn = abst_c = 0
    per = defaultdict(lambda: {"viol": 0, "clean": 0, "caught": 0, "ff": 0, "abst": 0})
    errs = []
    for c in scope:
        v, reason = rb.audit(c)
        k = c.get("kind")
        if c["label"] == "violation":
            per[k]["viol"] += 1
            if v == "violation":
                caught += 1; per[k]["caught"] += 1
            elif v == "abstain":
                abst_v += 1; per[k]["abst"] += 1
                errs.append((c["id"], k, "violation", v, reason))
            else:
                escaped += 1
                errs.append((c["id"], k, "violation", v, reason))
        else:
            per[k]["clean"] += 1
            if v == "violation":
                false_flag += 1; per[k]["ff"] += 1
                errs.append((c["id"], k, "consistent", v, reason))
            elif v == "abstain":
                abst_c += 1; per[k]["abst"] += 1
            else:
                tn += 1

    n = len(scope)
    catch = caught / len(viol) if viol else 0.0
    ff = false_flag / len(clean) if clean else 0.0
    err = (abst_v + abst_c) / n if n else 0.0
    print(f"\n{'='*62}\n{label}  ·  官方口径（in_scope_gated）\n{'='*62}")
    print(f"  范围内 {n} 例（排除 novel {len(cases)-n}）｜违规 {len(viol)} · 清洁 {len(clean)}")
    print(f"  catch_rate      {catch:.3f}   ({caught} 命中 / {len(viol)} 违规；逃逸 {escaped})")
    print(f"  false_flag_rate {ff:.3f}   ({false_flag} 误报 / {len(clean)} 清洁)")
    print(f"  error_rate      {err:.3f}   ({abst_v+abst_c} 弃权 / {n})")
    print(f"\n  按 kind：")
    for k in sorted(per):
        d = per[k]
        if d["viol"] == 0 and d["clean"] == 0:
            continue
        cr = f"{d['caught']}/{d['viol']}" if d["viol"] else "—"
        print(f"    {k:22} 违规捕获 {cr:8} 误报 {d['ff']}/{d['clean']} 弃权 {d['abst']}")
    if errs:
        print(f"\n  可改进 {len(errs)} 例：")
        for e in errs[:14]:
            print(f"    {e[0]} {e[1]:20} gold={e[2]:9} got={e[3]:9} {e[4][:52]}")
    return {"n": n, "violations": len(viol), "clean": len(clean), "caught": caught,
            "escaped": escaped, "false_flag": false_flag, "abstain": abst_v + abst_c,
            "catch_rate": catch, "false_flag_rate": ff, "error_rate": err}


if __name__ == "__main__":
    out = {}
    out["cases"] = official_score("cases.jsonl", "cases.jsonl（主集 392）") if len(sys.argv) < 2 else None
    if len(sys.argv) >= 2:
        out["ood"] = official_score(sys.argv[1], sys.argv[1])
    else:
        out["ood"] = official_score("ood.jsonl", "ood.jsonl（分布外 104）")
    json.dump(out, open("score_official.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
