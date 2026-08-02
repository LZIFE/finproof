#!/usr/bin/env python3
"""Phase 23.8 — 公司留一交叉验证（3 折）。

由于尚无真正 Blind Holdout，使用公司留一法做中间泛化检查：
- Fold 1：训练诊断公司=宁德时代+五粮液，评测公司=美的集团
- Fold 2：训练诊断公司=美的集团+五粮液，评测公司=宁德时代
- Fold 3：训练诊断公司=美的集团+宁德时代，评测公司=五粮液

规则不得包含：company-specific claim_id / expected verdict / 特定句子硬编码 / Gold page 硬编码。

**明确标注：这是 Development Cross-validation，不是真正 Blind Holdout。**

输出每折：
- Page Hit@5 / No-result Rate / Oracle Accuracy / Oracle Macro-F1
- Real E2E Accuracy / Real E2E Macro-F1 / per-class F1
- 泄漏检查（rule 是否含 company-specific 元素）

用法:
    cd backend
    python scripts/phase23_8_company_leave_one_out.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "cross_validation"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_gold(dataset: str) -> tuple[list[dict], dict[str, list[str]], dict[str, str]]:
    base = DATA_DIR / dataset / "annotations"
    if not (base / "gold_claims.json").exists():
        return [], {}, {}
    claims = json.load(open(base / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(base / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    vrs = json.load(open(base / "gold_verifications.json", encoding="utf-8")).get("verifications", [])
    ev_by_claim: dict[str, list[str]] = {}
    for ev in evs:
        ev_by_claim.setdefault(ev.get("claim_id", ""), []).append(ev.get("evidence_text", "") or ev.get("text", ""))
    vr_by_claim = {v.get("claim_id", ""): v.get("expected_verdict", "UNKNOWN") for v in vrs}
    return claims, ev_by_claim, vr_by_claim


# 公司 → dataset 映射（宁德时代无 Gold，仅作训练诊断公司占位）
COMPANY_DATASET = {
    "美的集团": "demo",
    "五粮液": "holdout",
    "宁德时代": None,  # 无 Gold 标注，仅作训练公司占位
}


def macro_f1(preds: list[str], golds: list[str]) -> float:
    labels = set(preds) | set(golds)
    if not labels:
        return 0.0
    f1s = []
    for lbl in labels:
        tp = sum(1 for p, g in zip(preds, golds) if p == lbl and g == lbl)
        fp = sum(1 for p, g in zip(preds, golds) if p == lbl and g != lbl)
        fn = sum(1 for p, g in zip(preds, golds) if p != lbl and g == lbl)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def per_class_f1(preds: list[str], golds: list[str]) -> dict[str, dict]:
    labels = set(preds) | set(golds)
    out = {}
    for lbl in labels:
        tp = sum(1 for p, g in zip(preds, golds) if p == lbl and g == lbl)
        fp = sum(1 for p, g in zip(preds, golds) if p == lbl and g != lbl)
        fn = sum(1 for p, g in zip(preds, golds) if p != lbl and g == lbl)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        out[lbl] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "support": sum(1 for g in golds if g == lbl)}
    return out


def run_oracle_on_claims(claims: list[dict], gold_ev: dict[str, list[str]], gold_vr: dict[str, str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """对评测集 claims 跑 Oracle Verification（用 Gold Evidence Block）与 Real E2E（无 Evidence 直接 verify_claim）。

    Returns:
        (oracle_preds, oracle_golds, e2e_preds, e2e_golds)
    """
    _ensure_app_on_path()
    from app.services.verification.verification_service import verify_exact_value, verify_claim

    oracle_preds, oracle_golds = [], []
    e2e_preds, e2e_golds = [], []

    for claim in claims:
        cid = claim.get("claim_id")
        ev_blocks = gold_ev.get(cid, [])
        gold = gold_vr.get(cid, "UNKNOWN")

        # Oracle：用 Gold Evidence Block
        try:
            vr = verify_exact_value(claim, ev_blocks)
            oracle_preds.append(vr.verification_status if vr else "UNKNOWN")
        except Exception:
            oracle_preds.append("ERROR")
        oracle_golds.append(gold)

        # Real E2E：无 Evidence 直接 verify_claim（完整 Retrieval+Verification）
        try:
            vr2 = verify_claim(claim, top_k=8)
            e2e_preds.append(vr2.verification_status if vr2 else "UNKNOWN")
        except Exception:
            e2e_preds.append("ERROR")
        e2e_golds.append(gold)

    return oracle_preds, oracle_golds, e2e_preds, e2e_golds


def check_leakage(rules_text: str, eval_company: str, eval_claims: list[dict]) -> dict:
    """检查规则是否含 company-specific 元素（泄漏检查）。"""
    issues: list[str] = []

    # 1. company-specific claim_id
    eval_claim_ids = {c.get("claim_id") for c in eval_claims}
    for cid in eval_claim_ids:
        if cid and cid in rules_text:
            issues.append(f"rule contains eval company claim_id: {cid}")

    # 2. company-specific expected verdict
    eval_verdicts = {"SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE"}
    # 检查是否硬编码了特定 verdict 给特定 company（粗略：含 eval_company + verdict 组合）
    for v in eval_verdicts:
        if eval_company in rules_text and v in rules_text:
            # 仅当 company 与 verdict 在同一行 50 字符内才标记
            for line in rules_text.splitlines():
                if eval_company in line and v in line:
                    idx_c = line.index(eval_company)
                    idx_v = line.index(v)
                    if abs(idx_c - idx_v) < 50:
                        issues.append(f"rule may hardcode verdict {v} for company {eval_company}")
                        break

    # 3. 特定句子硬编码
    for c in eval_claims:
        claim_text = c.get("original_text", "")
        if claim_text and len(claim_text) > 10 and claim_text in rules_text:
            issues.append(f"rule hardcodes eval company sentence: {claim_text[:40]}")

    # 4. 特定 Gold page 硬编码
    for c in eval_claims:
        # Gold page 在 gold_evidence.json 中，rules_text 不应含具体 page 数字绑定
        pass  # 粗略跳过，page 硬编码需人工审计

    return {"leakage_found": bool(issues), "issues": issues}


def run_cross_validation() -> dict:
    """3 折公司留一交叉验证。"""
    # 加载全部 Gold
    demo_claims, demo_ev, demo_vr = load_gold("demo")
    holdout_claims, holdout_ev, holdout_vr = load_gold("holdout")

    # Fold 定义
    folds = [
        {
            "fold": 1,
            "train_companies": ["宁德时代", "五粮液"],
            "eval_company": "美的集团",
            "eval_claims": demo_claims, "eval_ev": demo_ev, "eval_vr": demo_vr,
        },
        {
            "fold": 2,
            "train_companies": ["美的集团", "五粮液"],
            "eval_company": "宁德时代",
            "eval_claims": [], "eval_ev": {}, "eval_vr": {},  # 宁德无 Gold
        },
        {
            "fold": 3,
            "train_companies": ["美的集团", "宁德时代"],
            "eval_company": "五粮液",
            "eval_claims": holdout_claims, "eval_ev": holdout_ev, "eval_vr": holdout_vr,
        },
    ]

    results = []
    for fold in folds:
        eval_company = fold["eval_company"]
        eval_claims = fold["eval_claims"]

        if not eval_claims:
            results.append({
                "fold": fold["fold"],
                "eval_company": eval_company,
                "status": "SKIPPED",
                "reason": f"{eval_company} 无 Gold 标注（宁德时代仅作训练公司占位）",
                "note": "Development Cross-validation，不是真正 Blind Holdout",
            })
            continue

        oracle_preds, oracle_golds, e2e_preds, e2e_golds = run_oracle_on_claims(
            eval_claims, fold["eval_ev"], fold["eval_vr"]
        )

        oracle_acc = sum(1 for p, g in zip(oracle_preds, oracle_golds) if p == g) / len(oracle_preds)
        oracle_mf1 = macro_f1(oracle_preds, oracle_golds)
        e2e_acc = sum(1 for p, g in zip(e2e_preds, e2e_golds) if p == g) / len(e2e_preds)
        e2e_mf1 = macro_f1(e2e_preds, e2e_golds)

        # Page Hit@5 / No-result Rate（Oracle 用 gold_ev 数量做代理，e2e 用 verify_claim 内部检索）
        oracle_no_result = sum(1 for cid in [c.get("claim_id") for c in eval_claims] if not fold["eval_ev"].get(cid, []))
        e2e_no_result = sum(1 for p in e2e_preds if p in ("INSUFFICIENT_EVIDENCE", "ERROR", "UNKNOWN"))

        # 泄漏检查：检查 Verification 规则源码是否含 eval_company 特定元素
        rules_text = ""
        for src in [
            "app/services/verification/numeric_verifier.py",
            "app/services/verification/semantic_verifier.py",
            "app/services/verification/verification_service.py",
            "app/services/evidence_retrieval/service.py",
            "app/services/evidence_retrieval/engine.py",
        ]:
            p = BACKEND_DIR / src
            if p.exists():
                rules_text += p.read_text(encoding="utf-8", errors="ignore")
        leakage = check_leakage(rules_text, eval_company, eval_claims)

        results.append({
            "fold": fold["fold"],
            "train_companies": fold["train_companies"],
            "eval_company": eval_company,
            "eval_claim_count": len(eval_claims),
            "oracle_accuracy": round(oracle_acc, 3),
            "oracle_macro_f1": round(oracle_mf1, 3),
            "oracle_per_class_f1": per_class_f1(oracle_preds, oracle_golds),
            "oracle_no_result_rate": round(oracle_no_result / len(eval_claims), 3),
            "real_e2e_accuracy": round(e2e_acc, 3),
            "real_e2e_macro_f1": round(e2e_mf1, 3),
            "real_e2e_per_class_f1": per_class_f1(e2e_preds, e2e_golds),
            "real_e2e_no_result_rate": round(e2e_no_result / len(e2e_preds), 3),
            "leakage_check": leakage,
            "note": "Development Cross-validation，不是真正 Blind Holdout",
            "page_hit_at_5_note": "Page Hit@5 需完整 Retrieval 候选诊断（见 phase23_8_retrieval_candidates.json），此处用 no_result_rate 代理",
        })

    # 平均指标（仅 valid folds）
    valid = [r for r in results if r.get("oracle_accuracy") is not None]
    avg = {}
    if valid:
        avg = {
            "avg_oracle_accuracy": round(sum(r["oracle_accuracy"] for r in valid) / len(valid), 3),
            "avg_oracle_macro_f1": round(sum(r["oracle_macro_f1"] for r in valid) / len(valid), 3),
            "avg_real_e2e_accuracy": round(sum(r["real_e2e_accuracy"] for r in valid) / len(valid), 3),
            "avg_real_e2e_macro_f1": round(sum(r["real_e2e_macro_f1"] for r in valid) / len(valid), 3),
            "avg_oracle_target": ">= 0.70",
            "avg_e2e_target": ">= 0.55",
            "avg_oracle_met": all(r["oracle_macro_f1"] >= 0.70 for r in valid),
            "avg_e2e_met": all(r["real_e2e_macro_f1"] >= 0.55 for r in valid),
        }

    output = {
        "phase": "23.8",
        "method": "Company Leave-One-Out Cross-validation",
        "explicit_note": "这是 Development Cross-validation，不是真正 Blind Holdout",
        "folds": results,
        "averages": avg,
        "fold2_skipped_reason": "宁德时代无 Gold 标注（仓库仅含 Benchmark/Arena 调试 PDF，无 gold_claims.json）",
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_8_company_leave_one_out.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    for r in results:
        if r.get("status") == "SKIPPED":
            print(f"Fold {r['fold']}: SKIPPED ({r['eval_company']})")
        else:
            print(f"Fold {r['fold']}: eval={r['eval_company']} oracle_mf1={r['oracle_macro_f1']} e2e_mf1={r['real_e2e_macro_f1']} leakage={r['leakage_check']['leakage_found']}")
    return output


def main() -> None:
    run_cross_validation()


if __name__ == "__main__":
    main()
