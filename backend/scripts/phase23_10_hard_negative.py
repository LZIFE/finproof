#!/usr/bin/env python3
"""Phase 23.10 — Hard Negative Mining。

对 Development Gold 标注的候选正负样本，将 Top10 中错误候选（Hard Negative）分类：
- SAME_COMPANY_WRONG_METRIC：同公司、错误指标
- SAME_METRIC_WRONG_PERIOD：同指标、错误期间
- SAME_PERIOD_WRONG_UNIT：同期间、错误单位
- VALUE_CLOSE_WRONG_SCOPE：数值接近但口径错误
- NARRATIVE_MENTIONS_METRIC：叙述段提及指标但未给事实
- HEADER_ONLY_NO_DATA：表头块没有具体数据
- NEIGHBOR_TABLE_WRONG_METRIC：相邻表格但属于另一指标
- ANNUAL_AS_QUARTERLY：年度数据冒充季度数据
- CONSOLIDATED_AS_PARENT：合并净利润冒充归母净利润

仅使用 Development Gold 标注（demo + holdout）用于分类与调参；
禁止：claim_id 特征 / page number 记忆 / block_id 记忆 / company 固定权重 / Gold 移到第一位。

产物：backend/artifacts/retrieval/phase23_10_hard_negatives.json

用法:
    cd backend
    python scripts/phase23_10_hard_negative.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS = BACKEND_DIR / "artifacts" / "retrieval"


def classify_hard_negative(claim: dict, cand: dict) -> str:
    """对单个非 Gold 候选分类为 Hard Negative 类型。"""
    text = cand.get("text") or cand.get("enriched_text") or ""
    metric = str(claim.get("metric") or "").lower()
    period = str(claim.get("period") or "").upper()
    unit = str(claim.get("unit") or "")
    scope = str(claim.get("scope") or "").lower()
    metric_score = cand.get("metric_score") or 0
    value_score = cand.get("value_score") or 0
    period_score = cand.get("period_score") or 0
    # 指标行/表特征（来自 reranker 输出 scores 或 enriched 文本）
    table_region = cand.get("table_region") or ("表格：" in text or "指标：" in text)
    row_header = cand.get("row_header") or ""
    has_data = bool(re.search(r"\d", text))

    # 1) 表头块没有具体数据
    if table_region and not has_data:
        return "HEADER_ONLY_NO_DATA"
    # 2) 叙述段提及指标但未给事实（metric 命中但无数值，非表块）
    if metric_score > 0 and value_score == 0 and not table_region:
        return "NARRATIVE_MENTIONS_METRIC"
    # 3) 年度数据冒充季度数据（claim 季度但候选文本含"年度/年"）
    if re.search(r"Q[1-4]", period) and ("年度" in text or re.search(r"20\d{2}年", text) and "季度" not in text):
        return "ANNUAL_AS_QUARTERLY"
    # 4) 合并净利润冒充归母净利润
    if "归母" in str(claim.get("original_text") or "") and "归母" not in text and "净利润" in text:
        return "CONSOLIDATED_AS_PARENT"
    # 5) 同期间、错误单位
    if unit and value_score > 0 and period_score > 0:
        unit_hit = unit in text or (unit == "%" and "%" in text)
        if not unit_hit:
            return "SAME_PERIOD_WRONG_UNIT"
    # 6) 数值接近但口径错误
    if value_score > 0 and "归母" in text and "合并" not in scope and scope not in ("", "consolidated"):
        return "VALUE_CLOSE_WRONG_SCOPE"
    # 7) 同公司、错误指标（metric 未命中但有数字）
    if metric_score == 0 and value_score > 0:
        return "SAME_COMPANY_WRONG_METRIC"
    # 8) 同指标、错误期间
    if metric_score > 0 and period_score == 0:
        return "SAME_METRIC_WRONG_PERIOD"
    # 9) 相邻表格但属于另一指标
    if table_region and metric_score == 0:
        return "NEIGHBOR_TABLE_WRONG_METRIC"
    return "OTHER"


def run_hard_negative() -> dict:
    src = ARTIFACTS / "phase23_10_candidates.json"
    if not src.exists():
        raise FileNotFoundError(f"{src} 不存在，先运行 phase23_10_reranker_eval.py")

    data = json.load(open(src, encoding="utf-8"))
    claims_src = {}
    for ds in ["demo", "holdout"]:
        for c in json.load(open(BACKEND_DIR.parent / "data" / ds / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", []):
            claims_src[c["claim_id"]] = c

    classified: list[dict] = []
    for p in data.get("per_claim_top10", []):
        cid = p.get("claim_id")
        claim = claims_src.get(cid, {})
        for c in p.get("top10", []):
            if c.get("gold_block_hit") or c.get("gold_page_hit"):
                continue  # 正样本跳过
            htype = classify_hard_negative(claim, c)
            classified.append({
                "claim_id": cid, "rank": c.get("rank"),
                "block_id": c.get("block_id"), "page": c.get("page"),
                "final_score": c.get("final_score"),
                "metric": claim.get("metric", ""), "period": claim.get("period", ""),
                "hard_negative_type": htype,
                "text": (c.get("text") or "")[:80],
            })

    counts = Counter(x["hard_negative_type"] for x in classified)
    result = {
        "phase": "23.10",
        "script": "phase23_10_hard_negative",
        "note": "仅 Development Gold 标注用于分类；禁止 claim_id/page/block_id 记忆特征",
        "hard_negative_count": len(classified),
        "hard_negative_by_type": dict(counts),
        "hard_negatives": classified,
        "purpose": "Hard Negative 用于 Stage B 权重调参（任务九公司留一），不作为运行时特征",
    }
    out = ARTIFACTS / "phase23_10_hard_negatives.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"hard_negatives: {len(classified)}")
    print(f"by_type: {dict(counts)}")
    return result


if __name__ == "__main__":
    run_hard_negative()
