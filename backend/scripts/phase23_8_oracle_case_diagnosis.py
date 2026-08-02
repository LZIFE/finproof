#!/usr/bin/env python3
"""Phase 23.8 — Oracle Verification 逐案例诊断脚本。

针对全部 43 条 Development Claims 逐条输出 22 字段诊断，定位错误原因。

仅使用 Development Set（美的集团 demo + 五粮液 holdout）调试 Oracle Verification。
**严禁** 用于 Blind Holdout。不得修改 Gold Verdict 适配系统输出。

输出字段（每条主张）：
- claim_id / company / claim_text / claim_type / expected_verdict / predicted_verdict
- evidence_text / document_id / page / block_id
- extracted_claim_values / extracted_evidence_values
- claimed_metric / evidence_metric / claimed_period / evidence_period
- claimed_unit / evidence_unit / rule_id / calculated_value / confidence
- failure_category / failure_reason

failure_category 至少包括：
  NUMBER_EXTRACTION_ERROR / THOUSAND_SEPARATOR_ERROR / UNIT_CONVERSION_ERROR
  PERCENT_VS_PP_ERROR / SIGN_ERROR / PERIOD_MISMATCH / YTD_VS_QUARTER_ERROR
  METRIC_MISMATCH / SCOPE_MISMATCH / MULTIPLE_NUMBER_AMBIGUITY
  PARTIAL_BOUNDARY_ERROR / SEMANTIC_OVERREACH / EVIDENCE_INCOMPLETE
  VERDICT_MAPPING_ERROR / GOLD_ANNOTATION_SUSPECTED

用法:
    cd backend
    python scripts/phase23_8_oracle_case_diagnosis.py
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
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "oracle_diagnosis"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_gold(dataset: str) -> tuple[list[dict], dict[str, list[dict]], dict[str, dict]]:
    """加载 gold_claims / gold_evidence / gold_verifications。"""
    base = DATA_DIR / dataset / "annotations"
    claims = json.load(open(base / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(base / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    vrs = json.load(open(base / "gold_verifications.json", encoding="utf-8")).get("verifications", [])
    ev_by_claim: dict[str, list[dict]] = {}
    for ev in evs:
        ev_by_claim.setdefault(ev.get("claim_id", ""), []).append(ev)
    vr_by_claim = {v.get("claim_id", ""): v for v in vrs}
    return claims, ev_by_claim, vr_by_claim


# ---------------------------------------------------------------------------
# FinancialValue 结构化抽取（任务#3前置：数值解析重构）
# ---------------------------------------------------------------------------
def extract_financial_values(text: str, context_metric: str | None = None,
                              context_period: str | None = None,
                              context_unit: str | None = None) -> list[dict]:
    """从文本抽取所有 FinancialValue，每个包含 13 字段。

    Phase 23.8 重构：不再简单选第一个数字，而是抽取所有候选并标注 metric/period/unit/scale。
    """
    if not text:
        return []
    results: list[dict] = []
    normalized = unicodedata_normalize(text)

    # 数值+单位模式：亿元/万元/千元/元/百万/十亿/million/billion
    unit_pattern = re.compile(
        r"(-?\d[\d,]*\.?\d+)\s*"
        r"(亿元|万元|千元|元|百万|十亿|million|billion|MB|B)?"
        r"\s*(%)?",
        re.IGNORECASE | re.UNICODE,
    )
    # 括号负数：(1,081,776) 千元
    paren_neg = re.compile(r"\(([\d,]+\.?\d+)\)\s*(亿元|万元|千元|元|百万|十亿)?", re.UNICODE)

    found_ranges: list[tuple[int, int]] = []

    # 先匹配括号负数
    for m in paren_neg.finditer(normalized):
        raw = m.group(0)
        num_str = m.group(1).replace(",", "")
        unit = m.group(2) or context_unit or ""
        try:
            val = float(num_str)
        except ValueError:
            continue
        results.append(_make_fv(raw, val, unit, "", "negative_paren", m.span()))
        found_ranges.append(m.span())

    # 再匹配普通数值（跳过已匹配的括号区域）
    for m in unit_pattern.finditer(normalized):
        if any(_overlap(m.span(), r) for r in found_ranges):
            continue
        raw = m.group(0).strip()
        num_str = m.group(1).replace(",", "")
        unit = m.group(2) or context_unit or ""
        pct = m.group(3)
        try:
            val = float(num_str)
        except ValueError:
            continue
        pct_type = "percentage" if pct else ""
        results.append(_make_fv(raw, val, unit, pct_type, "plain", m.span()))

    return results


def _make_fv(raw: str, value: float, unit: str, pct_type: str,
             sign: str, span: tuple[int, int]) -> dict:
    """构建 13 字段 FinancialValue。"""
    scale, currency = _classify_unit(unit)
    return {
        "raw_text": raw,
        "normalized_value": round(value, 6),
        "scale": scale,           # "1e8"|"1e4"|"1e3"|"1"|"1e6"|"1e9"
        "currency": currency,     # "CNY"|"USD"|"" 
        "unit": unit,
        "percentage_type": pct_type,  # "percentage"|"basis_points"|""
        "sign": sign,             # "positive"|"negative_paren"|""
        "metric": "",             # 待上下文绑定
        "period": "",             # 待上下文绑定
        "source_span": [span[0], span[1]],
        "extraction_confidence": 0.85 if unit else 0.5,
    }


def _classify_unit(unit: str) -> tuple[str, str]:
    """单位归一化为 scale + currency。"""
    u = (unit or "").strip().lower()
    scale_map = {
        "亿元": "1e8", "万元": "1e4", "千元": "1e3", "元": "1",
        "百万": "1e6", "十亿": "1e9", "million": "1e6", "billion": "1e9",
    }
    scale = scale_map.get(u, "")
    currency = "USD" if u in ("million", "billion") else ("CNY" if u in scale_map else "")
    return scale, currency


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])


def unicodedata_normalize(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", text or "")


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------
def classify_failure(claim: dict, pred: str, gold: str,
                     evidence_texts: list[str], claim_values: list[dict],
                     evidence_values: list[dict], vr_metadata: dict) -> tuple[str, str]:
    """返回 (failure_category, failure_reason)。

    优先判定数值类错误，再判定 Semantic 覆盖、Verdict 映射、Gold 可疑。
    """
    ct = claim.get("claim_type", "?")
    metric = claim.get("metric", "")
    period = claim.get("period", "")
    scope = claim.get("scope", "")
    unit = claim.get("unit", "")

    # 一致
    if pred == gold:
        return "OK", "预测与 Gold 一致"

    # Gold annotation suspected：evidence_text 与 gold_verdict 不一致
    if _gold_suspected(claim, gold, evidence_texts):
        return ("GOLD_ANNOTATION_SUSPECTED",
        f"Gold verdict={gold} 但 evidence_text 与 verdict 可能不一致（需人工确认）")

    # Verdict mapping：forecast 类应有 OPINION_OR_FORECAST 但系统未支持
    if ct == "forecast" and gold == "OPINION_OR_FORECAST":
        return ("VERDICT_MAPPING_ERROR",
        "forecast 类的 OPINION_OR_FORECAST verdict 未在系统实现，误判为 INSUFFICIENT_EVIDENCE")

    # Verdict mapping：scope 类 UNABLE_TO_DETERMINE 误判为 INSUFFICIENT
    if ct == "scope" and gold == "UNABLE_TO_DETERMINE" and pred == "INSUFFICIENT_EVIDENCE":
        return ("VERDICT_MAPPING_ERROR",
        "scope 类 UNABLE_TO_DETERMINE（无法判定口径）误判为 INSUFFICIENT_EVIDENCE（证据不足）")

    # Semantic overreach：REFUTED 被覆盖为 PARTIALLY_SUPPORTED（数值冲突被语义匹配掩盖）
    if gold == "REFUTED" and pred == "PARTIALLY_SUPPORTED":
        return ("SEMANTIC_OVERREACH",
        "Semantic Verifier 覆盖了确定性数值冲突，REFUTED 应优先于 PARTIAL")

    # Semantic overreach：REFUTED 被覆盖为 INSUFFICIENT（数值冲突被弃权掩盖）
    if gold == "REFUTED" and pred == "INSUFFICIENT_EVIDENCE" and ct in ("causality", "business_fact"):
        return ("SEMANTIC_OVERREACH",
        "Semantic Verifier 对 REFUTED 的因果/业务事实误判为证据不足，应识别冲突")

    # EVIDENCE_INCOMPLETE：SUPPORTED �误判为 INSUFFICIENT（有 Gold Evidence 但系统未识别）
    if gold == "SUPPORTED" and pred == "INSUFFICIENT_EVIDENCE":
        if not evidence_values:
            return ("EVIDENCE_INCOMPLETE",
            "Evidence 中无数值抽取结果，但 Gold 标注为 SUPPORTED（抽取器遗漏或单位未识别）")
        return ("EVIDENCE_INCOMPLETE",
        "有 Gold Evidence 但系统未匹配为 SUPPORTED（metric/period/scope 绑定不足）")

    # PARTIAL boundary：PARTIALLY_SUPPORTED 误判为 REFUTED
    if gold == "PARTIALLY_SUPPORTED" and pred == "REFUTED":
        return ("PARTIAL_BOUNDARY_ERROR",
        "主张含多个组成部分，部分得到支持但被整体判为 REFUTED（应判 PARTIAL）")

    # PARTIAL boundary：SUPPORTED 误判为 PARTIALLY_SUPPORTED
    if gold == "SUPPORTED" and pred == "PARTIALLY_SUPPORTED":
        return ("PARTIAL_BOUNDARY_ERROR",
        "完整匹配被降级为部分匹配（容差或边界过严）")

    # 数值类错误：假阳性支持（REFUTED → SUPPORTED）
    if gold == "REFUTED" and pred == "SUPPORTED":
        # 检查是否为多数字歧义
        if len(evidence_values) > 1:
            return ("MULTIPLE_NUMBER_AMBIGUITY",
            "Evidence 含多个数字，系统误选了接近主张的错误数字")
        # 检查是否为千分位
        for ev in evidence_values:
            if "," in ev.get("raw_text", ""):
                return ("THOUSAND_SEPARATOR_ERROR",
                "千分位分隔符导致数值抽取错误（如 456,451,731 误解析为 456.45）")
        # 检查是否为单位换算
        claim_unit = claim.get("unit", "")
        ev_unit = evidence_values[0].get("unit", "") if evidence_values else ""
        if claim_unit and ev_unit and claim_unit != ev_unit:
            return ("UNIT_CONVERSION_ERROR",
            f"单位换算错误：claim={claim_unit} evidence={ev_unit}")
        # 检查是否为百分比 vs 百分点
        if "增长" in claim.get("original_text", "") or "下降" in claim.get("original_text", ""):
            return ("PERCENT_VS_PP_ERROR",
            "百分比与百分点混淆，或同比基期错误")
        return ("NUMBER_EXTRACTION_ERROR",
        "数值抽取错误，假阳性支持（数值不匹配但判 SUPPORTED）")

    # 数值类错误：假阴性反驳（SUPPORTED → REFUTED）
    if gold == "SUPPORTED" and pred == "REFUTED":
        # 检查是否为千分位
        for ev in evidence_values:
            if "," in ev.get("raw_text", "") and ev.get("scale") != "1e3":
                return ("THOUSAND_SEPARATOR_ERROR",
                "千分位分隔符导致数值抽取错误，正确数值被误判为不匹配")
        # 检查是否为单位换算
        claim_unit = claim.get("unit", "")
        ev_unit = evidence_values[0].get("unit", "") if evidence_values else ""
        if claim_unit and ev_unit and claim_unit != ev_unit:
            return ("UNIT_CONVERSION_ERROR",
            f"单位换算错误：claim={claim_unit} evidence={ev_unit}（千元→亿元换算失败）")
        return ("NUMBER_EXTRACTION_ERROR",
        "数值抽取错误，假阴性反驳（数值匹配但判 REFUTED）")

    # Period mismatch
    if period and pred != gold:
        return ("PERIOD_MISMATCH",
        f"期间匹配错误：claim period={period}")

    # Metric mismatch
    if metric and pred != gold:
        return ("METRIC_MISMATCH",
        f"指标匹配错误：claim metric={metric}")

    # Scope mismatch
    if scope and pred != gold:
        return ("SCOPE_MISMATCH",
        f"口径匹配错误：claim scope={scope}")

    # 兜底
    return ("VERDICT_MAPPING_ERROR", f"verdict 映射错误：gold={gold} pred={pred}")


def _gold_suspected(claim: dict, gold: str, evidence_texts: list[str]) -> bool:
    """粗略检测 Gold annotation 可疑：evidence_text 明显与 verdict 不一致。

    **仅作 suspected 标记，不自动修改 Gold**。需人工确认。
    """
    # 简化：暂不标记任何 Gold 为 suspected（保守策略，避免误报）
    return False


# ---------------------------------------------------------------------------
# 主诊断函数
# ---------------------------------------------------------------------------
def diagnose_all() -> dict:
    _ensure_app_on_path()
    from app.services.verification.verification_service import verify_exact_value

    all_claims: list[dict] = []
    all_ev: dict[str, list[dict]] = {}
    all_vr: dict[str, dict] = {}
    for ds in ["demo", "holdout"]:
        claims, ev, vr = load_gold(ds)
        for c in claims:
            c["_dataset"] = ds
        all_claims.extend(claims)
        all_ev.update(ev)
        all_vr.update(vr)

    cases: list[dict] = []
    for claim in all_claims:
        cid = claim.get("claim_id")
        ev_blocks = all_ev.get(cid, [])
        evidence_texts = [e.get("evidence_text", "") for e in ev_blocks]
        gold_vr = all_vr.get(cid, {})
        gold = gold_vr.get("expected_verdict", "UNKNOWN")

        # Oracle：用 Gold Evidence Block 调 verify_exact_value
        try:
            vr = verify_exact_value(claim, evidence_texts)
            pred = vr.verification_status if vr else "UNKNOWN"
            rule_id = getattr(vr, "rule_id", None) or "unknown"
            calculated = getattr(vr, "calculated_value", None)
            confidence = float(vr.confidence) if vr and vr.confidence is not None else 0.0
        except Exception as e:
            pred = "ERROR"
            rule_id = "exception"
            calculated = f"EXC: {e}"
            confidence = 0.0

        # 抽取 claim 与 evidence 的结构化 FinancialValue
        claim_text = claim.get("original_text", "")
        claim_values = extract_financial_values(
            claim_text, claim.get("metric"), claim.get("period"), claim.get("unit")
        )
        evidence_values: list[dict] = []
        for et in evidence_texts:
            evidence_values.extend(
                extract_financial_values(et, claim.get("metric"), claim.get("period"), claim.get("unit"))
            )

        # 抽取 evidence 的 metric/period/unit（粗略，从 notes 字段）
        ev_metric = ""
        ev_period = claim.get("period", "")  # 默认与 claim 一致（Gold Evidence 已绑定）
        ev_unit = evidence_values[0].get("unit", "") if evidence_values else ""

        # 错误分类
        failure_cat, failure_reason = classify_failure(
            claim, pred, gold, evidence_texts, claim_values, evidence_values, gold_vr
        )

        # 取首个 evidence block 的 document/page/block_id
        first_ev = ev_blocks[0] if ev_blocks else {}
        document_id = first_ev.get("document_name", "")
        page = first_ev.get("page", None)
        block_id = first_ev.get("evidence_id", "")

        case = {
            "claim_id": cid,
            "company": claim.get("entity", ""),
            "claim_text": claim_text,
            "claim_type": claim.get("claim_type", ""),
            "expected_verdict": gold,
            "predicted_verdict": pred,
            "evidence_text": evidence_texts[0] if evidence_texts else "",
            "document_id": document_id,
            "page": page,
            "block_id": block_id,
            "extracted_claim_values": claim_values[:3],  # 前3个避免过长
            "extracted_evidence_values": evidence_values[:5],  # 前5个
            "claimed_metric": claim.get("metric", ""),
            "evidence_metric": ev_metric,
            "claimed_period": claim.get("period", ""),
            "evidence_period": ev_period,
            "claimed_unit": claim.get("unit", ""),
            "evidence_unit": ev_unit,
            "rule_id": rule_id,
            "calculated_value": calculated,
            "confidence": round(confidence, 3),
            "failure_category": failure_cat,
            "failure_reason": failure_reason,
        }
        cases.append(case)

    # 汇总
    failure_dist = Counter(c["failure_category"] for c in cases if c["failure_category"] != "OK")
    error_cases = [c for c in cases if c["failure_category"] != "OK"]

    result = {
        "phase": "23.8",
        "script": "phase23_8_oracle_case_diagnosis",
        "total_claims": len(cases),
        "correct_count": len(cases) - len(error_cases),
        "error_count": len(error_cases),
        "failure_distribution": dict(failure_dist),
        "cases": cases,
        "note": "Development Set ONLY (美的+宁德+五粮液); Blind Holdout BLOCKED; 不修改 Gold Verdict",
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_8_cases.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"total: {len(cases)}, correct: {len(cases) - len(error_cases)}, error: {len(error_cases)}")
    print(f"failure distribution: {dict(failure_dist)}")
    return result


def main() -> None:
    diagnose_all()


if __name__ == "__main__":
    main()
