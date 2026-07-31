#!/usr/bin/env python3
"""Phase 4A 证据检索评测：Demo + Holdout 的 Page/Block Hit@K、MRR 等。

流程：
1. 确保证据文档已注册（holdout 需先导入 data/holdout/source/annual_report.pdf）；
2. 执行检索（ORACLE_GOLD 输入 = gold_claims）；
3. **检索完成后**读取 gold_evidence 计算 Hit@K（数据隔离：gold_evidence 仅用于评测，不参与排序）。

产物：artifacts/evaluations/evidence_retrieval/{demo,holdout}/metrics.json + report.md

用法：
  backend/.venv/bin/python scripts/evaluate_evidence_retrieval.py [--dataset demo|holdout] [--top-k 5]
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Document, DocumentBlock, DocumentPage  # noqa: E402
from app.services.evidence_retrieval.service import run_retrieval  # noqa: E402

ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "evaluations" / "evidence_retrieval"

HOLDOUT_SOURCE = REPO_ROOT / "data" / "holdout" / "source" / "annual_report.pdf"


def ensure_source_documents(session, dataset: str) -> None:
    """确保检索所需的证据文档存在（holdout 首次导入五粮液年报）。"""
    if dataset != "holdout":
        return
    from app.services import document_service as dsvc

    exists = (
        session.query(Document)
        .filter(Document.document_role == "SOURCE_DOCUMENT", Document.company_name == "五粮液")
        .first()
    )
    if exists:
        return
    dsvc.register_document(
        session,
        filename=HOLDOUT_SOURCE.name,
        data=HOLDOUT_SOURCE.read_bytes(),
        document_role="SOURCE_DOCUMENT",
        company_name="五粮液",
        stock_code="000858",
        report_period="2025FY",
    )
    print("已导入 holdout 证据文档（五粮液年报）")


def _doc_id_by_name(session, dataset: str) -> dict[str, int]:
    """document_name（gold_evidence 用）→ document_id。"""
    if dataset == "holdout":
        doc = (
            session.query(Document)
            .filter(Document.document_role == "SOURCE_DOCUMENT", Document.company_name == "五粮液")
            .first()
        )
        return {doc.original_filename: doc.id, "annual_report.pdf": doc.id} if doc else {}
    # demo：按文件名映射
    out = {}
    for d in session.query(Document).filter(Document.document_role == "SOURCE_DOCUMENT").all():
        out[d.original_filename] = d.id
    return out


def find_gold_block(session, document_id: int, page_number: int, fragment: str) -> int | None:
    """定位金标准证据文本所在块（仅评测用；空白归一化后匹配 fragment 前 20 字）。"""
    frag = re.sub(r"\s+", "", (fragment or "").strip())[:20]
    if not frag:
        return None
    page = (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == document_id, DocumentPage.page_number == page_number)
        .first()
    )
    if not page:
        return None
    from sqlalchemy import func

    blocks = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.page_id == page.id)
        .all()
    )
    for b in blocks:
        if frag in re.sub(r"\s+", "", b.text or ""):
            return b.id
    return None


def evaluate_dataset(session, dataset: str, top_k: int) -> dict:
    """对单个数据集执行检索并计算评测指标。"""
    ensure_source_documents(session, dataset)
    run = run_retrieval(session, dataset=dataset, input_mode="ORACLE_GOLD", top_k=top_k, version="v1")

    # ---- 检索完成后读取 gold_evidence（仅评测，不参与排序）----
    gold_claims = json.loads(
        (REPO_ROOT / "data" / dataset / "annotations" / "gold_claims.json").read_text(encoding="utf-8")
    )["claims"]
    gold_evidence = json.loads(
        (REPO_ROOT / "data" / dataset / "annotations" / "gold_evidence.json").read_text(encoding="utf-8")
    )["evidence"]
    doc_map = _doc_id_by_name(session, dataset)

    ev_by_claim: dict[str, list[dict]] = {}
    for e in gold_evidence:
        ev_by_claim.setdefault(e["claim_id"], []).append(e)

    from app.services.evidence_retrieval.service import get_run_claims

    grouped = get_run_claims(session, run.id)

    page_ranks: list[int | None] = []
    block_ranks: list[int | None] = []
    no_result = 0
    candidate_counts: list[int] = []
    failures: list[dict] = []

    for claim in gold_claims:
        cid = claim["claim_id"]
        cands = grouped.get(cid, [])
        candidate_counts.append(len(cands))
        if not cands:
            no_result += 1
            continue
        evs = ev_by_claim.get(cid, [])
        if not evs:
            continue  # 无证据标注的主张不参与 Hit 计算
        for e in evs:
            g_doc = doc_map.get(e["document_name"])
            g_page = e.get("page")
            g_block = (
                find_gold_block(session, g_doc, g_page, e.get("evidence_text", ""))
                if g_doc and g_page
                else None
            )
            # Page Hit：gold 页出现在 Top-K 中的最小排名
            page_rank = next((c["rank"] for c in cands if c["document_id"] == g_doc and c["page_number"] == g_page), None)
            page_ranks.append(page_rank)
            # Block Hit：gold 块出现在 Top-K 中的最小排名
            block_rank = next((c["rank"] for c in cands if c["block_id"] == g_block), None) if g_block else None
            block_ranks.append(block_rank)
            if page_rank is None and block_rank is None:
                failures.append(
                    {
                        "claim_id": cid,
                        "gold_document": e["document_name"],
                        "gold_page": g_page,
                        "top_pages": [(c["document_id"], c["page_number"]) for c in cands[:3]],
                    }
                )

    def hit_at(ranks: list, k: int) -> float:
        if not ranks:
            return 0.0
        return round(sum(1 for r in ranks if r is not None and r <= k) / len(ranks), 4)

    def mrr(ranks: list) -> float:
        if not ranks:
            return 0.0
        return round(sum(1.0 / r for r in ranks if r is not None) / len(ranks), 4)

    metrics = {
        "dataset": dataset,
        "retrieval_run_id": run.id,
        "input_mode": run.input_mode,
        "top_k": top_k,
        "claim_count": run.claim_count,
        "gold_evidence_count": len(gold_evidence),
        "duration_ms": run.duration_ms,
        "page_hit_at_1": hit_at(page_ranks, 1),
        "page_hit_at_3": hit_at(page_ranks, 3),
        "page_hit_at_5": hit_at(page_ranks, 5),
        "block_hit_at_1": hit_at(block_ranks, 1),
        "block_hit_at_3": hit_at(block_ranks, 3),
        "block_hit_at_5": hit_at(block_ranks, 5),
        "mrr": mrr(page_ranks),
        "block_mrr": mrr(block_ranks),
        "no_result_rate": round(no_result / max(len(gold_claims), 1), 4),
        "average_candidate_count": round(sum(candidate_counts) / max(len(candidate_counts), 1), 2),
        "average_latency": run.duration_ms,
    }

    out_dir = ARTIFACT_ROOT / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# 证据检索评测：{dataset}（run {run.id}，Oracle 模式）",
        "",
        f"| 指标 | 值 |",
        f"| ---- | -- |",
    ]
    for k in (
        "page_hit_at_1", "page_hit_at_3", "page_hit_at_5",
        "block_hit_at_1", "block_hit_at_3", "block_hit_at_5",
        "mrr", "block_mrr", "no_result_rate", "average_candidate_count", "average_latency",
    ):
        lines.append(f"| {k} | {metrics[k]} |")
    lines.append("")
    lines.append(f"检索任务：run {run.id}（{run.status}，{run.duration_ms}ms，{run.claim_count} 条主张）")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["demo", "holdout"], default="demo")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    init_db()
    with SessionLocal() as s:
        m = evaluate_dataset(s, args.dataset, args.top_k)
    print(json.dumps(m, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
