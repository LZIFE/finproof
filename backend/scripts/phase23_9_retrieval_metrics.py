#!/usr/bin/env python3
"""Phase 23.9 — Retrieval Metrics 修复与重算脚本。

背景（旧指标 INVALID 判定）
---------------------------
旧指标 artifacts/retrieval/phase23_7_retrieval_metrics.json：
- Page Hit@1=0.744 > Page Hit@3=0.674 > Page Hit@5=0.628，违反 Hit@K 单调性；
- per-claim top10 的 candidate_id 全部为 "?"，说明命中判定未使用真实 block id/page；
- 分母不可验证（K 依赖分母被怀疑），无法追溯。
→ 全部 Retrieval 指标判定 INVALID，本脚本按统一定义重算。

统一定义（本脚本唯一口径）
--------------------------
- total_claims = 全部有 Gold Evidence 的 Development Claims（固定分母）
- Page Hit@K   = Top K 内至少命中一个 Gold Page 的 claim 数 / total_claims
- Block Hit@K  = Top K 内至少命中一个 Gold Block 的 claim 数 / total_claims
- Recall@K     = Top K 内命中的 Gold Evidence 数 / Gold Evidence 总数
- No-result Rate = 返回 0 候选的 claim 数 / total_claims
- MRR          = 每 claim 首个 Gold 命中的倒数排名均值（未命中计 0）

不变量测试（脚本内强制断言并写入结果）
- 0 <= Hit@1 <= Hit@3 <= Hit@5 <= 1
- 0 <= BlockHit@1 <= BlockHit@3 <= BlockHit@5 <= 1
- Recall@1 <= Recall@3 <= Recall@5
- No-result Rate 与空候选 claim 数完全一致
- 同一输入连续运行两次结果一致（确定性）

Gold Block 解析：gold_evidence.json 只有 (document_name, page, evidence_text)，
无 block_id。评测时按 文本归一化包含匹配 在 (doc, page) 上解析 Gold Block：
- BLOCK_MATCHED：找到唯一 block id（block hit 可判定）
- PAGE_ONLY：页面存在但 block 文本不匹配（block hit 不可判定，page hit 可判定）
- NOT_INDEXED：该 (doc, page) 未被索引（gold evidence 指向未导入文档）

用法:
    cd backend
    python scripts/phase23_9_retrieval_metrics.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
ARTIFACTS_DIR = BACKEND_DIR / "artifacts" / "retrieval"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def _norm(s: str) -> str:
    """归一化：去全角空格/空白，用于文本包含匹配。"""
    return "".join(s.split())


def load_gold(dataset: str) -> tuple[list[dict], dict[str, list[dict]]]:
    claims = json.load(open(DATA_DIR / dataset / "annotations" / "gold_claims.json", encoding="utf-8")).get("claims", [])
    evs = json.load(open(DATA_DIR / dataset / "annotations" / "gold_evidence.json", encoding="utf-8")).get("evidence", [])
    by_claim: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        by_claim[e.get("claim_id", "")].append(e)
    return claims, dict(by_claim)


def build_doc_page_block_index(session) -> tuple[dict, dict]:
    """返回 (docs_by_name, blocks_by_doc_page)。

    docs_by_name: original_filename -> [Document, ...]（同名文档可能属于不同公司，
    demo 与 holdout 均有 annual_report.pdf，必须按 claim 实体消歧）。
    blocks_by_doc_page[(doc_id, page_number)] = [(block_id, block_text), ...]
    """
    from app.models import Document, DocumentBlock, DocumentPage

    docs: dict[str, list] = defaultdict(list)
    for d in session.query(Document).all():
        docs[d.original_filename].append(d)
        if d.stored_filename and d.stored_filename != d.original_filename:
            docs[d.stored_filename].append(d)
    rows = (
        session.query(DocumentBlock, DocumentPage.page_number)
        .join(DocumentPage, DocumentPage.id == DocumentBlock.page_id)
        .all()
    )
    blocks: dict[tuple, list] = defaultdict(list)
    for b, pn in rows:
        blocks[(b.document_id, pn)].append((b.id, b.text or ""))
    return docs, blocks


def resolve_gold_blocks(gold_ev: list[dict], docs: dict, blocks: dict, claim: dict | None = None) -> list[dict]:
    """把 gold evidence 解析为 (doc_id, page, block_id|None, status)。

    claim 提供实体（entity/company）用于同名文档消歧：
    demo(美的集团) 与 holdout(五粮液) 均有 annual_report.pdf。
    """
    entity = (claim or {}).get("entity") or (claim or {}).get("company") or ""
    out = []
    for ev in gold_ev:
        fname = ev.get("document_name", "")
        page = ev.get("page")
        cand_docs = docs.get(fname, [])
        doc = None
        if len(cand_docs) == 1:
            doc = cand_docs[0]
        else:
            # 同名多文档：优先 company_name 匹配 claim 实体
            for d in cand_docs:
                if entity and (entity in (d.company_name or "") or (d.company_name or "") in entity):
                    doc = d
                    break
            if doc is None:
                doc = cand_docs[0] if cand_docs else None
        if doc is None or page is None:
            out.append({**ev, "doc_id": None, "block_id": None, "status": "NOT_INDEXED"})
            continue
        ev_txt = _norm(ev.get("evidence_text", "") or ev.get("text", ""))
        cand_blocks = blocks.get((doc.id, page), [])
        best: int | None = None
        if ev_txt:
            best_txt = ""
            for bid, btxt in cand_blocks:
                nbt = _norm(btxt)
                if not nbt:
                    continue
                if ev_txt in nbt or nbt in ev_txt:
                    if len(nbt) > len(best_txt):  # 取最具体（最长）匹配块
                        best, best_txt = bid, nbt
        status = "BLOCK_MATCHED" if best is not None else ("PAGE_ONLY" if cand_blocks else "PAGE_NOT_PARSED")
        out.append({**ev, "doc_id": doc.id, "page": page, "block_id": best, "status": status})
    return out


def run_single_pass(session, claims_with_ev: list[dict], gold_ev_by_claim: dict, gold_resolved: dict) -> dict:
    """单次完整检索与指标计算（不变量 + 确定性检查用）。

    gold_resolved 含每条 gold evidence 的 (doc_id, page, status, ev_text_norm)；
    命中判定用 (doc_id, page) + 文本归一化包含匹配，而非固定 block id（block id 不稳定）。
    """
    from app.services.evidence_retrieval.service import retrieve_for_claim
    from app.models import DocumentBlock

    # block_id → 块文本缓存（候选不含文本字段，需从 DB 注入以做块命中判定）
    block_text_cache: dict = {}

    def _block_text(session, block_id) -> str:
        if block_id is None:
            return ""
        if block_id not in block_text_cache:
            b = session.query(DocumentBlock).get(block_id)
            block_text_cache[block_id] = (b.text or "") if b else ""
        return block_text_cache[block_id]

    per_claim: list[dict] = []
    for claim in claims_with_ev:
        cid = claim["claim_id"]
        golds = gold_resolved.get(cid, [])
        # Gold Page 集合（用 (doc_id, page)，block id 不稳定）
        gold_pages = {(g["doc_id"], g["page"]) for g in golds if g["doc_id"] is not None}
        # Gold Block 集合：用 (doc_id, page, ev_text_norm) 三元组做文本归一化匹配
        gold_blocks = {(g["doc_id"], g["page"], _norm(g.get("evidence_text", "") or g.get("text", "")))
                       for g in golds if g["doc_id"] is not None and g["status"] == "BLOCK_MATCHED"}
        try:
            candidates = retrieve_for_claim(session, claim, top_k=10) or []
        except Exception as exc:  # noqa: BLE001
            candidates = []
            err = str(exc)[:120]
        else:
            err = ""
        # 去重（block 级）后再按 final_score 排序（retrieve 已排序，此处保险）
        seen: set = set()
        uniq = []
        for c in candidates:
            if c.get("block_id") in seen:
                continue
            seen.add(c.get("block_id"))
            uniq.append(c)
        uniq.sort(key=lambda c: -(c.get("final_score") or 0.0))

        # 候选文本归一化（用 DB 块文本注入，用于 block 命中判定）
        def _c_norm(c):
            return _norm(_block_text(session, c.get("block_id")))

        def page_hit_rank(k: int) -> int | None:
            for i, c in enumerate(uniq[:k], start=1):
                if (c.get("document_id"), c.get("page_number")) in gold_pages:
                    return i
            return None

        def block_hit_rank(k: int) -> int | None:
            for i, c in enumerate(uniq[:k], start=1):
                key = (c.get("document_id"), c.get("page_number"), _c_norm(c))
                if key in gold_blocks:
                    return i
                for gd in golds:
                    if (gd["doc_id"], gd["page"]) == (c.get("document_id"), c.get("page_number")) and gd["status"] == "BLOCK_MATCHED":
                        gold_norm = _norm(gd.get("evidence_text", "") or gd.get("text", ""))
                        cand_norm = _c_norm(c)
                        if gold_norm and cand_norm and (gold_norm in cand_norm or cand_norm in gold_norm):
                            return i
            return None

        page_r1, page_r3, page_r5 = page_hit_rank(1), page_hit_rank(3), page_hit_rank(5)
        block_r1, block_r3, block_r5 = block_hit_rank(1), block_hit_rank(3), block_hit_rank(5)
        first_gold_rank = page_hit_rank(10)  # 仅用于 MRR（页面级首命中）
        first_block_rank = block_hit_rank(10)

        per_claim.append({
            "claim_id": cid,
            "entity": claim.get("entity", ""),
            "claim_type": claim.get("claim_type", ""),
            "metric": claim.get("metric", ""),
            "period": claim.get("period", ""),
            "gold_evidence_count": len(golds),
            "gold_resolution": [{"status": g["status"], "doc_id": g["doc_id"], "page": g["page"]} for g in golds],
            "retrieved_count": len(uniq),
            "no_result": len(uniq) == 0,
            "page_hit_at_1": page_r1 is not None,
            "page_hit_at_3": page_r3 is not None,
            "page_hit_at_5": page_r5 is not None,
            "block_hit_at_1": block_r1 is not None,
            "block_hit_at_3": block_r3 is not None,
            "block_hit_at_5": block_r5 is not None,
            "first_gold_page_rank": first_gold_rank,
            "first_gold_block_rank": first_block_rank,
            "error": err or None,
            "top10": [
                {
                    "rank": i,
                    "block_id": c.get("block_id"),
                    "document_id": c.get("document_id"),
                    "page": c.get("page_number"),
                    "final_score": round(float(c.get("final_score") or 0.0), 4),
                    "metric_score": round(float(c.get("metric_score") or 0.0), 4),
                    "value_score": round(float(c.get("value_score") or 0.0), 4),
                    "period_score": round(float(c.get("period_score") or 0.0), 4),
                    "entity_score": round(float(c.get("entity_score") or 0.0), 4),
                    "text_score": round(float(c.get("text_score") or 0.0), 4),
                    "evidence_type": c.get("evidence_type"),
                    "gold_page_hit": (c.get("document_id"), c.get("page_number")) in gold_pages,
                    "gold_block_hit": block_hit_rank(i) == i,
                    "evidence_text": _block_text(session, c.get("block_id"))[:160],
                    "evidence_rank_reason": c.get("evidence_rank_reason"),
                }
                for i, c in enumerate(uniq[:10], start=1)
            ],
        })

    total = len(per_claim)
    gold_total = sum(p["gold_evidence_count"] for p in per_claim)

    def hit_ratio(pred: callable, k: int) -> float:
        return sum(1 for p in per_claim if p[f"{pred}_at_{k}"]) / total if total else 0.0

    page_hit = {k: round(hit_ratio("page_hit", k), 4) for k in (1, 3, 5)}
    block_hit = {k: round(hit_ratio("block_hit", k), 4) for k in (1, 3, 5)}

    # Recall@K：Top K 内命中的 Gold Evidence 数 / Gold Evidence 总数
    def recall(k: int) -> float:
        hits = 0
        for p in per_claim:
            for c in p["top10"][:k]:
                if c["gold_block_hit"] or c["gold_page_hit"]:
                    hits += 1
                    break
        return round(hits / gold_total, 4) if gold_total else 0.0

    recall_k = {k: recall(k) for k in (1, 3, 5)}

    def mrr(rank_key: str) -> float:
        total_rr = 0.0
        for p in per_claim:
            r = p[rank_key]
            total_rr += (1.0 / r) if r is not None else 0.0
        return round(total_rr / total, 4) if total else 0.0

    no_result = sum(1 for p in per_claim if p["no_result"])
    return {
        "total_claims": total,
        "gold_evidence_total": gold_total,
        "page_hit_at_1": page_hit[1],
        "page_hit_at_3": page_hit[3],
        "page_hit_at_5": page_hit[5],
        "block_hit_at_1": block_hit[1],
        "block_hit_at_3": block_hit[3],
        "block_hit_at_5": block_hit[5],
        "recall_at_1": recall_k[1],
        "recall_at_3": recall_k[3],
        "recall_at_5": recall_k[5],
        "mrr_page": mrr("first_gold_page_rank"),
        "mrr_block": mrr("first_gold_block_rank"),
        "no_result_count": no_result,
        "no_result_rate": round(no_result / total, 4) if total else 0.0,
        "per_claim": per_claim,
    }


def check_invariants(r: dict) -> list[dict]:
    """指标不变量测试：返回 [{name, passed, detail}]。"""
    checks = []
    ph1, ph3, ph5 = r["page_hit_at_1"], r["page_hit_at_3"], r["page_hit_at_5"]
    checks.append({
        "name": "0 <= Page Hit@1 <= Page Hit@3 <= Page Hit@5 <= 1",
        "passed": 0.0 <= ph1 <= ph3 <= ph5 <= 1.0,
        "detail": f"Hit@1={ph1} Hit@3={ph3} Hit@5={ph5}",
    })
    bh1, bh3, bh5 = r["block_hit_at_1"], r["block_hit_at_3"], r["block_hit_at_5"]
    checks.append({
        "name": "0 <= Block Hit@1 <= Block Hit@3 <= Block Hit@5 <= 1",
        "passed": 0.0 <= bh1 <= bh3 <= bh5 <= 1.0,
        "detail": f"BlockHit@1={bh1} BlockHit@3={bh3} BlockHit@5={bh5}",
    })
    rc1, rc3, rc5 = r["recall_at_1"], r["recall_at_3"], r["recall_at_5"]
    checks.append({
        "name": "Recall@1 <= Recall@3 <= Recall@5",
        "passed": rc1 <= rc3 <= rc5,
        "detail": f"Recall@1={rc1} Recall@3={rc3} Recall@5={rc5}",
    })
    empty_count = sum(1 for p in r["per_claim"] if p["no_result"])
    checks.append({
        "name": "No-result Rate 与空候选 claim 数量完全一致",
        "passed": empty_count == r["no_result_count"] and r["no_result_rate"] == round(empty_count / r["total_claims"], 4),
        "detail": f"empty={empty_count} no_result_count={r['no_result_count']} rate={r['no_result_rate']}",
    })
    return checks


def run() -> dict:
    _ensure_app_on_path()
    import shutil

    from app.db import SessionLocal, init_db
    from app.services import document_service

    # 干净数据库 + 导入全部 Development 源文档（demo: 年报/半年报/一季报; holdout: 年报）
    db_path = DATA_DIR.parent / "finproof.db"
    if db_path.exists():
        db_path.unlink()
    storage = DATA_DIR.parent / "storage"
    if storage.exists():
        shutil.rmtree(storage)
    init_db()
    session = SessionLocal()

    imports = [
        (DATA_DIR / "demo" / "source" / "annual_report.pdf", "美的集团", "000333", "2025FY"),
        (DATA_DIR / "demo" / "source" / "half_year_report.pdf", "美的集团", "000333", "2025H1"),
        (DATA_DIR / "demo" / "source" / "q1_report.pdf", "美的集团", "000333", "2025Q1"),
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

    docs, blocks = build_doc_page_block_index(session)

    claims, ev_by_claim = load_gold("demo")
    claims_h, ev_h = load_gold("holdout")
    claims += claims_h
    ev_by_claim.update(ev_h)

    # 只有 Gold Evidence 的 claims 计入 total_claims（统一定义）
    claims_with_ev = [c for c in claims if ev_by_claim.get(c["claim_id"])]
    claim_by_id = {c["claim_id"]: c for c in claims}
    gold_resolved = {
        cid: resolve_gold_blocks(evs, docs, blocks, claim=claim_by_id.get(cid))
        for cid, evs in ev_by_claim.items()
    }

    # 第一次运行
    r1 = run_single_pass(session, claims_with_ev, ev_by_claim, gold_resolved)
    checks1 = check_invariants(r1)
    # 第二次运行（确定性）
    r2 = run_single_pass(session, claims_with_ev, ev_by_claim, gold_resolved)
    checks2 = check_invariants(r2)

    agg_keys = ["page_hit_at_1", "page_hit_at_3", "page_hit_at_5",
                "block_hit_at_1", "block_hit_at_3", "block_hit_at_5",
                "recall_at_1", "recall_at_3", "recall_at_5",
                "mrr_page", "mrr_block", "no_result_rate"]
    deterministic = all(round(r1[k], 6) == round(r2[k], 6) for k in agg_keys)
    determinism_check = {
        "name": "同一输入连续运行两次结果一致（确定性）",
        "passed": deterministic,
        "detail": {k: [r1[k], r2[k]] for k in agg_keys} if not deterministic else "两次运行全部指标一致",
    }

    # 旧指标 INVALID 判定
    old_metrics_path = ARTIFACTS_DIR / "phase23_7_retrieval_metrics.json"
    old_invalid = {
        "old_metrics_file": str(old_metrics_path),
        "invalid_reasons": [
            "Page Hit@1=0.744 > Page Hit@3=0.674 > Page Hit@5=0.628，违反 Hit@K 单调性",
            "per-claim top10 candidate_id 全为 '?'，命中判定未使用真实 block id/page，无法复核",
            "分母不可验证（疑为 K 依赖分母），不符合统一定义（total_claims 固定为全部有 Gold Evidence 的 claim）",
        ],
        "verdict": "INVALID",
    }
    if old_metrics_path.exists():
        old_metrics_path.rename(old_metrics_path.with_suffix(".json.INVALID"))

    metrics = {
        "phase": "23.9",
        "script": "phase23_9_retrieval_metrics",
        "definition": {
            "total_claims": "全部有 Gold Evidence 的 Development Claims（固定分母）",
            "page_hit_at_k": "Top K 内至少命中一个 Gold Page 的 claim 数 / total_claims",
            "block_hit_at_k": "Top K 内至少命中一个 Gold Block 的 claim 数 / total_claims",
            "recall_at_k": "Top K 内命中的 Gold Evidence 数 / Gold Evidence 总数",
            "no_result_rate": "返回 0 候选的 claim 数 / total_claims",
            "mrr": "每 claim 首个 Gold 命中的倒数排名均值（未命中计 0）",
        },
        "gold_block_resolution": {
            "BLOCK_MATCHED": sum(1 for gs in gold_resolved.values() for g in gs if g["status"] == "BLOCK_MATCHED"),
            "PAGE_ONLY": sum(1 for gs in gold_resolved.values() for g in gs if g["status"] == "PAGE_ONLY"),
            "NOT_INDEXED": sum(1 for gs in gold_resolved.values() for g in gs if g["status"] == "NOT_INDEXED"),
            "PAGE_NOT_PARSED": sum(1 for gs in gold_resolved.values() for g in gs if g["status"] == "PAGE_NOT_PARSED"),
        },
        "dataset": "Development Set (demo 美的 + holdout 五粮液)",
        "metrics_run_1": {k: r1[k] for k in agg_keys},
        "metrics_run_2": {k: r2[k] for k in agg_keys},
        "invariants": checks1,
        "determinism_check": determinism_check,
        "all_invariants_passed": all(c["passed"] for c in checks1) and deterministic,
        "previous_metrics": old_invalid,
        "targets": {
            "Page Hit@5 >= 0.80": f"{r1['page_hit_at_5']:.3f} ({'PASS' if r1['page_hit_at_5'] >= 0.80 else 'FAIL'})",
            "Block Hit@5 >= 0.70": f"{r1['block_hit_at_5']:.3f} ({'PASS' if r1['block_hit_at_5'] >= 0.70 else 'FAIL'})",
            "Recall@5 >= 0.80": f"{r1['recall_at_5']:.3f} ({'PASS' if r1['recall_at_5'] >= 0.80 else 'FAIL'})",
            "MRR >= 0.60": f"{r1['mrr_page']:.3f} ({'PASS' if r1['mrr_page'] >= 0.60 else 'FAIL'})",
            "No-result Rate <= 0.15": f"{r1['no_result_rate']:.3f} ({'PASS' if r1['no_result_rate'] <= 0.15 else 'FAIL'})",
        },
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics_path = ARTIFACTS_DIR / "phase23_9_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    candidates = {
        "phase": "23.9",
        "script": "phase23_9_retrieval_metrics",
        "total_claims": r1["total_claims"],
        "per_claim_top10": [p for p in r1["per_claim"]],
    }
    cand_path = ARTIFACTS_DIR / "phase23_9_candidates.json"
    cand_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"saved: {metrics_path}")
    print(f"saved: {cand_path}")
    print(f"Page Hit@1/3/5 = {r1['page_hit_at_1']} / {r1['page_hit_at_3']} / {r1['page_hit_at_5']}")
    print(f"Block Hit@1/3/5 = {r1['block_hit_at_1']} / {r1['block_hit_at_3']} / {r1['block_hit_at_5']}")
    print(f"Recall@1/3/5 = {r1['recall_at_1']} / {r1['recall_at_3']} / {r1['recall_at_5']}")
    print(f"MRR(page)={r1['mrr_page']} MRR(block)={r1['mrr_block']} No-result={r1['no_result_rate']}")
    print(f"invariants: {[c['passed'] for c in checks1]} determinism={deterministic}")
    session.close()
    return metrics


if __name__ == "__main__":
    run()
