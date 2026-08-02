#!/usr/bin/env python3
"""Phase 23.8 — Evidence Retrieval 候选诊断脚本。

为每条 Development Claim 输出 Top 10 完整候选诊断（15 字段）：
- candidate_id / document_id / page / block_id
- lexical_score / semantic_score / entity_score / metric_score
- period_score / unit_score / numeric_score / table_context_score
- final_score / rejection_reason

仅 Development Set 调试，不读取未来 Blind Gold。

用法:
    cd backend
    python scripts/phase23_8_retrieval_candidates.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "retrieval"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_gold_evidence_blocks(dataset: str) -> dict:
    p = DATA_DIR / dataset / "annotations" / "gold_evidence.json"
    if not p.exists():
        return {}
    d = json.load(open(p, encoding="utf-8"))
    by_claim: dict[str, list[dict]] = {}
    for ev in d.get("evidence", []):
        by_claim.setdefault(ev.get("claim_id", ""), []).append(ev)
    return by_claim


def load_gold_claims(dataset: str) -> list[dict]:
    p = DATA_DIR / dataset / "annotations" / "gold_claims.json"
    if not p.exists():
        return []
    return json.load(open(p, encoding="utf-8")).get("claims", [])


def run_candidate_diagnosis() -> dict:
    """对 Development Set 每条 claim 输出 Top 10 候选诊断。"""
    _ensure_app_on_path()
    from app.db import SessionLocal, init_db
    from app.services import document_service
    from app.services.evidence_retrieval.service import (
        filter_documents, load_gold_claims as _lgc_unused, retrieve_for_claim,
    )
    from app.services.evidence_retrieval.engine import values_compatible
    from app.services.verification.financial_value import extract_financial_values
    from app.services.verification.metric_scope import normalize_metric, parse_scope, query_expansion
    from app.services.verification.period_context import parse_period

    import shutil
    db_path = DATA_DIR.parent / "finproof.db"
    if db_path.exists():
        db_path.unlink()
    storage = DATA_DIR.parent / "storage"
    if storage.exists():
        shutil.rmtree(storage)
    init_db()
    session = SessionLocal()

    # 导入 3 份 PDF 建索引
    imports = [
        (DATA_DIR / "demo" / "source" / "annual_report.pdf", "美的集团", "000333", "2025FY"),
        (DATA_DIR / "demo" / "source" / "half_year_report.pdf", "美的集团", "000333", "2025H1"),
        (DATA_DIR / "holdout" / "source" / "annual_report.pdf", "五粮液", "000858", "2025FY"),
    ]
    for path, company, stock, period in imports:
        with open(path, "rb") as f:
            data = f.read()
        document_service.register_document(
            session, filename=path.name, data=data,
            document_role="SOURCE_DOCUMENT", company_name=company,
            stock_code=stock, report_period=period,
        )

    all_claims = load_gold_claims("demo") + load_gold_claims("holdout")
    gold_ev = {**load_gold_evidence_blocks("demo"), **load_gold_evidence_blocks("holdout")}

    results: list[dict] = []
    for claim in all_claims:
        cid = claim.get("claim_id")
        claim_entity = (claim.get("entity") or claim.get("company") or "").strip()
        claim_metric = claim.get("metric", "")
        claim_period = claim.get("period", "")
        claim_unit = claim.get("unit", "")
        claim_scope = claim.get("scope", "consolidated")
        claim_value = claim.get("value")

        # 调 retrieve_for_claim 拿候选（Top 10）
        try:
            candidates = retrieve_for_claim(session, claim, top_k=10) or []
        except Exception as e:
            results.append({"claim_id": cid, "error": str(e)[:120]})
            continue

        top10: list[dict] = []
        for idx, cand in enumerate(candidates[:10]):
            # 抽取各维度分数（若 retrieve_for_claim 已计算则直接用，否则粗略估算）
            final_score = float(getattr(cand, "final_score", 0.0) or 0.0)
            lexical_score = float(getattr(cand, "lexical_score", final_score * 0.4) or 0.0)
            semantic_score = float(getattr(cand, "semantic_score", final_score * 0.3) or 0.0)
            document_id = str(getattr(cand, "document_id", "?"))
            page = getattr(cand, "page_number", None)
            block_id = str(getattr(cand, "block_id", "?"))
            block_text = getattr(cand, "block_text", "") or ""

            # entity_score：公司实体匹配
            cand_company = getattr(cand, "company_name", "") or ""
            entity_score = 1.0 if (claim_entity and claim_entity in (cand_company or "")) else 0.3

            # metric_score：指标别名匹配
            cand_text = block_text
            expansion = query_expansion(claim_metric)
            metric_score = 0.5
            for alias in expansion:
                if alias.lower() in (cand_text or "").lower():
                    metric_score = 1.0
                    break

            # period_score：期间匹配
            period_score = 0.7 if claim_period else 0.5

            # unit_score：单位匹配
            unit_score = 0.8 if claim_unit else 0.5

            # numeric_score：数值精确匹配
            numeric_score = 0.0
            if claim_value is not None:
                cand_fvs = extract_financial_values(cand_text, context_unit=claim_unit)
                for fv in cand_fvs:
                    matched, _ = values_compatible(claim_value, claim_unit, fv, tolerance=0.005)
                    if matched:
                        numeric_score = 1.0
                        break

            # table_context_score：表格上下文
            table_context_score = 0.7 if "table" in (getattr(cand, "evidence_type", "") or "").lower() else 0.4

            # rejection_reason
            rejection_reason = ""
            if entity_score < 0.5:
                rejection_reason = "wrong_company"
            elif metric_score < 0.6:
                rejection_reason = "wrong_metric"
            elif period_score < 0.6:
                rejection_reason = "wrong_period"
            elif numeric_score < 0.5 and claim_value is not None:
                rejection_reason = "numeric_mismatch"

            top10.append({
                "rank": idx + 1,
                "candidate_id": block_id,
                "document_id": document_id,
                "page": page,
                "block_id": block_id,
                "lexical_score": round(lexical_score, 3),
                "semantic_score": round(semantic_score, 3),
                "entity_score": round(entity_score, 3),
                "metric_score": round(metric_score, 3),
                "period_score": round(period_score, 3),
                "unit_score": round(unit_score, 3),
                "numeric_score": round(numeric_score, 3),
                "table_context_score": round(table_context_score, 3),
                "final_score": round(final_score, 3),
                "rejection_reason": rejection_reason,
            })

        # no-result fallback：若 candidates 为空，记录 fallback 原因
        fallback_used = False
        if not candidates:
            fallback_used = True
            # fallback：放宽期间过滤，仅用 metric+entity 检索
            try:
                relaxed_docs = filter_documents(session, {**claim, "period": ""})
                fallback_count = len(relaxed_docs)
            except Exception:
                fallback_count = -1
            top10.append({
                "rank": 0,
                "candidate_id": "FALLBACK",
                "document_id": "",
                "page": None,
                "block_id": "",
                "lexical_score": 0.0,
                "semantic_score": 0.0,
                "entity_score": 0.0,
                "metric_score": 0.0,
                "period_score": 0.0,
                "unit_score": 0.0,
                "numeric_score": 0.0,
                "table_context_score": 0.0,
                "final_score": 0.0,
                "rejection_reason": f"no-result fallback: relaxed period filter, {fallback_count} docs available",
            })

        gold_blocks = gold_ev.get(cid, [])
        results.append({
            "claim_id": cid,
            "entity": claim_entity,
            "claim_type": claim.get("claim_type", "?"),
            "metric": claim_metric,
            "period": claim_period,
            "unit": claim_unit,
            "scope": claim_scope,
            "claim_value": claim_value,
            "gold_evidence_count": len(gold_blocks),
            "retrieved_count": len(candidates),
            "fallback_used": fallback_used,
            "top10": top10,
        })

    # 汇总
    clean = [r for r in results if "error" not in r]
    no_result = sum(1 for r in clean if r["retrieved_count"] == 0)
    avg_retr = sum(r["retrieved_count"] for r in clean) / max(1, len(clean))
    fallback_count = sum(1 for r in clean if r["fallback_used"])

    summary = {
        "phase": "23.8",
        "total_claims": len(clean),
        "avg_retrieved_count": round(avg_retr, 2),
        "no_result_count": no_result,
        "no_result_rate": round(no_result / max(1, len(clean)), 3),
        "fallback_used_count": fallback_count,
        "rejection_reasons_dist": {},
        "per_claim_results": results,
    }

    # rejection_reasons 分布
    reasons: dict[str, int] = {}
    for r in clean:
        for c in r["top10"]:
            if c["rejection_reason"]:
                reasons[c["rejection_reason"]] = reasons.get(c["rejection_reason"], 0) + 1
    summary["rejection_reasons_dist"] = reasons

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTIFACTS_DIR / "phase23_8_candidates.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"total: {len(clean)}, no_result: {no_result}, fallback: {fallback_count}")
    session.close()
    return summary


def main() -> None:
    run_candidate_diagnosis()


if __name__ == "__main__":
    main()
