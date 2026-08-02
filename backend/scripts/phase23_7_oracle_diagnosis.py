#!/usr/bin/env python3
"""Phase 23.7 — Oracle Verification 开发集诊断脚本。

仅使用 Development Set（美的集团 demo + 五粮液 holdout）调试 Oracle Verification。
**严禁** 用于 Blind Holdout（Blind Holdout BLOCKED，不存在全新公司财报）。

输出：
- confusion matrix
- 每种 claim_type 的 precision/recall/F1
- 每种 verdict 的 precision/recall/F1
- 所有错误案例（claim_id / rule_id / calculated_value / claimed_value / metric / period / unit / evidence block / 错误原因分类）
- 总体 Accuracy / Macro-F1
- Oracle 指标对照（Accuracy ≥0.85 / Macro-F1 ≥0.80 / 数值类F1 ≥0.90 / 期间类F1 ≥0.80 / INSUFFICIENT_EVIDENCE F1 ≥0.80）

用法:
    cd backend
    python scripts/phase23_7_oracle_diagnosis.py            # 跑全部 Development Set
    python scripts/phase23_7_oracle_diagnosis.py --dataset demo      # 仅 demo 集
    python scripts/phase23_7_oracle_diagnosis.py --dataset holdout   # 仅 holdout 集
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "oracle_diagnosis"


def _ensure_app_on_path() -> None:
    import sys
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_gold_evidence_blocks(dataset: str) -> dict:
    """读取 gold_evidence.json，返回 claim_id -> [evidence_text, ...]。"""
    p = DATA_DIR / dataset / "annotations" / "gold_evidence.json"
    if not p.exists():
        return {}
    d = json.load(open(p, encoding="utf-8"))
    by_claim: dict[str, list[str]] = {}
    for ev in d.get("evidence", []):
        cid = ev.get("claim_id")
        txt = ev.get("evidence_text") or ev.get("text") or ""
        if cid and txt:
            by_claim.setdefault(cid, []).append(txt)
    return by_claim


def load_gold_verdicts(dataset: str) -> dict:
    """读取 gold_verifications.json，返回 claim_id -> expected_verdict。

    **仅用于评测计算**，系统推理路径不得读取此文件。
    """
    p = DATA_DIR / dataset / "annotations" / "gold_verifications.json"
    if not p.exists():
        return {}
    d = json.load(open(p, encoding="utf-8"))
    by_claim: dict[str, str] = {}
    for v in d.get("verifications", []):
        by_claim[v.get("claim_id")] = v.get("expected_verdict", "UNKNOWN")
    return by_claim


def load_gold_claims(dataset: str) -> list[dict]:
    p = DATA_DIR / dataset / "annotations" / "gold_claims.json"
    if not p.exists():
        return []
    d = json.load(open(p, encoding="utf-8"))
    return d.get("claims", [])


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
    """返回每个 verdict 类别的 precision/recall/F1/support。"""
    labels = set(preds) | set(golds)
    out = {}
    for lbl in labels:
        tp = sum(1 for p, g in zip(preds, golds) if p == lbl and g == lbl)
        fp = sum(1 for p, g in zip(preds, golds) if p == lbl and g != lbl)
        fn = sum(1 for p, g in zip(preds, golds) if p != lbl and g == lbl)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        out[lbl] = {
            "precision": round(prec, 3),
            "recall": round(rec, 3),
            "f1": round(f1, 3),
            "support_gold": sum(1 for g in golds if g == lbl),
            "support_pred": sum(1 for p in preds if p == lbl),
        }
    return out


def confusion_matrix(preds: list[str], golds: list[str]) -> dict:
    """返回嵌套 dict: gold_verdict -> pred_verdict -> count。"""
    labels = sorted(set(preds) | set(golds))
    cm = {g: {p: 0 for p in labels} for g in labels}
    for p, g in zip(preds, golds):
        cm[g][p] += 1
    return cm


def classify_error(claim: dict, pred: str, gold: str, evidence_texts: list[str]) -> str:
    """错误原因分类（用于诊断 Oracle Verification 规则缺陷）。"""
    if gold == "SUPPORTED" and pred == "REFUTED":
        return "假阳性反驳：正确主张被误判为反驳"
    if gold == "SUPPORTED" and pred == "INSUFFICIENT_EVIDENCE":
        return "缺Evidence时错误弃权：有Gold Evidence但系统未识别为SUPPORTED"
    if gold == "SUPPORTED" and pred == "PARTIAL":
        return "SUPPORTED与PARTIAL边界混淆：完整匹配被降级为部分匹配"
    if gold == "REFUTED" and pred == "SUPPORTED":
        return "假阳性支持：错误主张被误判为支持（数值容差过大？）"
    if gold == "REFUTED" and pred == "INSUFFICIENT_EVIDENCE":
        return "REFUTED与INSUFFICIENT混淆：数值不匹配但系统判证据不足"
    if gold == "REFUTED" and pred == "PARTIAL":
        return "REFUTED与PARTIAL混淆：数值错误被降级为部分匹配"
    if gold == "PARTIAL" and pred == "SUPPORTED":
        return "PARTIAL误升SUPPORTED：部分匹配被升级为完整支持"
    if gold == "PARTIAL" and pred == "REFUTED":
        return "PARTIAL误升REFUTED：部分匹配被升级为完全反驳"
    if gold == "INSUFFICIENT_EVIDENCE" and pred == "SUPPORTED":
        return "缺Evidence时错误支持：无Gold Evidence但系统判SUPPORTED（严重泄漏）"
    if gold == "INSUFFICIENT_EVIDENCE" and pred == "REFUTED":
        return "缺Evidence时错误反驳：无Gold Evidence但系统判REFUTED"
    if gold == "INSUFFICIENT_EVIDENCE" and pred == "PARTIAL":
        return "缺Evidence时错误部分支持"
    if pred == "UNKNOWN" or pred == "UNABLE_TO_DETERMINE":
        return "规则未命中过度弃权：无法判定"
    # 兜底
    return f"其他映射错误：gold={gold} pred={pred}"


def run_oracle_diagnosis(datasets: list[str]) -> dict:
    """对指定数据集跑 Oracle Verification 诊断。"""
    _ensure_app_on_path()
    from app.services.verification.verification_service import verify_exact_value

    all_claims: list[dict] = []
    all_gold_ev: dict[str, list[str]] = {}
    all_gold_v: dict[str, str] = {}
    for ds in datasets:
        claims = load_gold_claims(ds)
        gold_ev = load_gold_evidence_blocks(ds)
        gold_v = load_gold_verdicts(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_gold_ev.update(gold_ev)
        all_gold_v.update(gold_v)

    preds: list[str] = []
    golds: list[str] = []
    per_claim_results: list[dict] = []
    error_cases: list[dict] = []

    for claim in all_claims:
        cid = claim.get("claim_id")
        # Oracle：使用 Gold Evidence Block 作为输入（非 claim 文本）
        ev_blocks = all_gold_ev.get(cid, [])
        try:
            vr = verify_exact_value(claim, ev_blocks)
            pred = vr.verification_status if vr else "UNKNOWN"
            rule_id = getattr(vr, "rule_id", None) or (vr.metadata.get("rule_id") if hasattr(vr, "metadata") and vr.metadata else None)
            calculated_value = getattr(vr, "calculated_value", None) or (vr.metadata.get("calculated_value") if hasattr(vr, "metadata") and vr.metadata else None)
        except Exception as e:
            pred = "ERROR"
            rule_id = None
            calculated_value = f"EXC: {e}"
        gold = all_gold_v.get(cid, "UNKNOWN")

        preds.append(pred)
        golds.append(gold)

        claimed_value = claim.get("value")
        metric = claim.get("metric")
        period = claim.get("period")
        unit = claim.get("unit")
        claim_type = claim.get("claim_type", "?")
        entity = claim.get("entity") or claim.get("company", "?")
        evidence_preview = (ev_blocks[0][:120] if ev_blocks else "(无Gold Evidence)")

        per_claim_results.append({
            "claim_id": cid,
            "dataset": claim.get("_dataset"),
            "entity": entity,
            "claim_type": claim_type,
            "metric": metric,
            "period": period,
            "unit": unit,
            "claimed_value": claimed_value,
            "gold_evidence_count": len(ev_blocks),
            "gold_verdict": gold,
            "pred_verdict": pred,
            "rule_id": rule_id,
            "calculated_value": calculated_value,
            "evidence_block_preview": evidence_preview,
            "match": pred == gold,
        })

        if pred != gold:
            error_cases.append({
                "claim_id": cid,
                "dataset": claim.get("_dataset"),
                "entity": entity,
                "claim_type": claim_type,
                "metric": metric,
                "period": period,
                "unit": unit,
                "claimed_value": claimed_value,
                "gold_evidence_count": len(ev_blocks),
                "gold_verdict": gold,
                "pred_verdict": pred,
                "rule_id": rule_id,
                "calculated_value": calculated_value,
                "evidence_block_preview": evidence_preview,
                "error_category": classify_error(claim, pred, gold, ev_blocks),
            })

    # 总体指标
    acc = sum(1 for p, g in zip(preds, golds) if p == g) / len(preds) if preds else 0
    mf1 = macro_f1(preds, golds)
    verdict_f1 = per_class_f1(preds, golds)
    cm = confusion_matrix(preds, golds)

    # per claim_type F1
    claim_types = sorted(set(c.get("claim_type", "?") for c in all_claims))
    per_type_f1: dict[str, dict] = {}
    for ct in claim_types:
        idx = [i for i, c in enumerate(all_claims) if c.get("claim_type", "?") == ct]
        if not idx:
            continue
        ct_preds = [preds[i] for i in idx]
        ct_golds = [golds[i] for i in idx]
        ct_acc = sum(1 for p, g in zip(ct_preds, ct_golds) if p == g) / len(ct_preds)
        per_type_f1[ct] = {
            "support": len(idx),
            "accuracy": round(ct_acc, 3),
            "macro_f1": round(macro_f1(ct_preds, ct_golds), 3),
            "verdict_distribution_gold": dict(Counter(ct_golds)),
            "verdict_distribution_pred": dict(Counter(ct_preds)),
        }

    # 错误原因分类汇总
    error_categories = Counter(e["error_category"] for e in error_cases)

    # 目标对照
    numeric_types = {"raw_number", "calculated_financial_metric"}
    period_types = {"calculated_financial_metric"}  # 期间类（含同比/环比）
    numeric_f1 = macro_f1(
        [preds[i] for i, c in enumerate(all_claims) if c.get("claim_type") in numeric_types],
        [golds[i] for i, c in enumerate(all_claims) if c.get("claim_type") in numeric_types],
    ) if any(c.get("claim_type") in numeric_types for c in all_claims) else 0.0
    insuff_f1 = verdict_f1.get("INSUFFICIENT_EVIDENCE", {}).get("f1", 0.0)

    targets = {
        "Oracle Accuracy >= 0.85": f"{acc:.3f} ({'PASS' if acc >= 0.85 else 'FAIL'})",
        "Oracle Macro-F1 >= 0.80": f"{mf1:.3f} ({'PASS' if mf1 >= 0.80 else 'FAIL'})",
        "数值类 F1 >= 0.90": f"{numeric_f1:.3f} ({'PASS' if numeric_f1 >= 0.90 else 'FAIL'})",
        "INSUFFICIENT_EVIDENCE F1 >= 0.80": f"{insuff_f1:.3f} ({'PASS' if insuff_f1 >= 0.80 else 'FAIL'})",
    }

    result = {
        "phase": "23.7",
        "script": "phase23_7_oracle_diagnosis",
        "definition": "Oracle = verify_exact_value(claim, Gold_Evidence_Block) — 仅使用Gold Evidence Block，非claim文本",
        "datasets_used": datasets,
        "data_split": "Development Set ONLY (Blind Holdout BLOCKED)",
        "total_claims": len(all_claims),
        "accuracy": round(acc, 3),
        "macro_f1": round(mf1, 3),
        "verdict_distribution_gold": dict(Counter(golds)),
        "verdict_distribution_pred": dict(Counter(preds)),
        "confusion_matrix": cm,
        "per_verdict_f1": verdict_f1,
        "per_claim_type_f1": per_type_f1,
        "numeric_f1": round(numeric_f1, 3),
        "insufficient_evidence_f1": round(insuff_f1, 3),
        "error_count": len(error_cases),
        "error_categories": dict(error_categories),
        "targets": targets,
        "all_errors": error_cases,
        "per_claim_results": per_claim_results,
        "note": "仅Development Set调试; Blind Holdout BLOCKED因仓库无全新公司财报",
    }

    # 保存
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_7_oracle_diagnosis.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 23.7 Oracle Verification diagnosis")
    parser.add_argument("--dataset", type=str, default="all", choices=["all", "demo", "holdout"],
                        help="数据集选择: all/demo/holdout")
    args = parser.parse_args()
    datasets = ["demo", "holdout"] if args.dataset == "all" else [args.dataset]
    run_oracle_diagnosis(datasets)


if __name__ == "__main__":
    main()
