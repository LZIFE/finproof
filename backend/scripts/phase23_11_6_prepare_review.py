"""Phase 23.11.6 Review Pack Preparer (Task 2).

Generates offline blind review package for 32 HUMAN_REVIEW_REQUIRED evidence:
- review.html (offline page, NO expected_verdict / prediction / gold labels)
- review_items.json
- review_results.template.json
- review_progress.json
- review_instructions.md

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_6_prepare_review.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.evaluation_claim_schema import load_canonical_claims
from app.db import SessionLocal
from app.models import DocumentBlock

REVIEW_DIR = BACKEND.parent / "data" / "gold_review" / "phase23_11_6"
AUDIT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_5_1_grounding_audit.json"

# First-round review must NOT expose these
BLINDED_FIELDS = ("expected_verdict", "prediction", "selected_by_system", "is_gold", "agent_recommendation")


def main() -> int:
    claims, _ = load_canonical_claims()
    claim_by_id = {c.claim_id: c for c in claims}
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    session = SessionLocal()
    try:
        all_blocks = session.query(DocumentBlock).order_by(
            DocumentBlock.document_id, DocumentBlock.page_id, DocumentBlock.block_index).all()
    finally:
        session.close()
    block_by_id = {str(b.id): b for b in all_blocks}
    blocks_by_page: dict = {}
    for b in all_blocks:
        blocks_by_page.setdefault(b.page_id, []).append(b)

    # Only HUMAN_REVIEW_REQUIRED entries (32)
    items = []
    for p in audit["per_evidence"]:
        if p["new_status"] != "HUMAN_REVIEW_REQUIRED":
            continue
        cid = p["claim_id"]
        cc = claim_by_id.get(cid)
        cand_ids = p.get("candidate_block_ids", []) or []
        groups = []
        # Up to 5 candidate groups, no duplicates, in original order
        seen = set()
        for bid in cand_ids:
            if bid in seen:
                continue
            seen.add(bid)
            if len(groups) >= 5:
                break
            b = block_by_id.get(bid)
            if not b:
                continue
            page_blocks = blocks_by_page.get(b.page_id, [])
            idx = next((i for i, x in enumerate(page_blocks) if str(x.id) == bid), None)
            before = str(page_blocks[idx - 1].text or "")[:200] if (idx is not None and idx > 0) else ""
            after = str(page_blocks[idx + 1].text or "")[:200] if (idx is not None and idx < len(page_blocks) - 1) else ""
            groups.append({
                "candidate_group_id": f"{p['gold_evidence_id']}-g{len(groups) + 1}",
                "document_id": b.document_id,
                "page": b.page_id,
                "block_ids": [bid],
                "reconstructed_text": str(b.text or "")[:400],
                "context_before": before,
                "context_after": after,
                "reconstruction_coverage": round(p.get("reconstruction_coverage", 0.0), 4),
                "number_match": False,
                "metric_match": "UNKNOWN",
                "period_match": "UNKNOWN",
                "unit_match": "UNKNOWN",
                "company_match": "UNKNOWN",
            })
        # First-round item: NO expected_verdict / prediction / gold
        items.append({
            "item_id": p["gold_evidence_id"],
            "claim_id": cid,
            "claim_text": str(cc.claim_text if cc else "")[:300],
            "company": str(cc.company if cc else ""),
            "report_name": "annual_report" if (cc.dataset if cc else "") == "demo" else "holdout_report",
            "dataset": cc.dataset if cc else "",
            "gold_evidence_text": p["evidence_text"][:300],
            "candidate_groups": groups,
            "reviewer_choice": "",
            "selected_block_ids": [],
            "evidence_complete": "",
            "reviewer_note": "",
            "review_status": "PENDING",
        })

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # review_items.json
    (REVIEW_DIR / "review_items.json").write_text(
        json.dumps({"phase": "23.11.6", "total": len(items), "items": items},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # review_results.template.json (reviewer fills this)
    template = {
        "phase": "23.11.6",
        "instructions": "Fill reviewer_choice / selected_block_ids / evidence_complete / reviewer_note for each item. DO NOT touch other fields.",
        "items": [{k: ("" if k.startswith("reviewer") else ([] if k == "selected_block_ids" else v))
                   for k, v in it.items()} for it in items],
    }
    (REVIEW_DIR / "review_results.template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")

    # review_progress.json
    (REVIEW_DIR / "review_progress.json").write_text(
        json.dumps({"phase": "23.11.6", "total": len(items), "reviewed": 0, "pending": len(items),
                    "last_updated": ""}, ensure_ascii=False, indent=2), encoding="utf-8")

    # review_instructions.md
    (REVIEW_DIR / "review_instructions.md").write_text(_instructions(), encoding="utf-8")

    # review.html (offline, no JS framework; first round blind)
    (REVIEW_DIR / "review.html").write_text(_build_html(items), encoding="utf-8")

    print(f"Review pack written to {REVIEW_DIR}")
    print(f"  items: {len(items)}")
    print(f"  files: review.html / review_items.json / review_results.template.json / review_progress.json / review_instructions.md")
    return 0


def _instructions() -> str:
    return """# 第一轮盲审说明（Evidence Alignment）

## 你的任务
对每条 Gold Evidence 文本，判断哪（些）候选 Block 真正对应它。

## 可选答案
- MATCH_SINGLE_BLOCK: 单个 Block 完全对应
- MATCH_MULTIPLE_BLOCKS: 多个相邻 Block 共同对应
- NONE_OF_THE_ABOVE: 候选都不对应
- UNSURE: 无法确定

## 必填字段
- selected_block_ids: 你确认的 Block ID 列表
- evidence_complete: yes / no（候选是否完整包含 Gold Evidence 全部内容）
- reviewer_note: 你的判断依据

## 注意
- 页面不显示 expected_verdict / 系统预测 / Gold 标签，避免影响你的判断。
- 相同 Block 不会重复出现。
- 只能选择页面提供的候选，不要自行臆测。
"""


def _build_html(items) -> str:
    cards = []
    for it in items:
        groups_html = ""
        for g in it["candidate_groups"]:
            groups_html += f"""
            <div class="candidate">
              <h4>候选组 {g['candidate_group_id']}</h4>
              <p><b>document_id:</b> {g['document_id']} &nbsp; <b>page:</b> {g['page']}</p>
              <p><b>block_ids:</b> {g['block_ids']}</p>
              <div class="block"><b>候选原文:</b><br>{g['reconstructed_text']}</div>
              <div class="ctx"><b>前一个Block:</b><br>{g['context_before']}</div>
              <div class="ctx"><b>后一个Block:</b><br>{g['context_after']}</div>
              <p><b>重建覆盖率:</b> {g['reconstruction_coverage']} &nbsp; <b>匹配方式:</b> fuzzy</p>
            </div>"""
        cards.append(f"""
        <div class="item">
          <h3>Evidence: {it['item_id']} (claim {it['claim_id']})</h3>
          <p><b>公司:</b> {it['company']} &nbsp; <b>报告:</b> {it['report_name']} &nbsp; <b>数据集:</b> {it['dataset']}</p>
          <p><b>Claim文本:</b> {it['claim_text']}</p>
          <div class="gold"><b>原Gold Evidence文本:</b><br>{it['gold_evidence_text']}</div>
          {groups_html}
          <p><b>审核选择:</b> MATCH_SINGLE_BLOCK / MATCH_MULTIPLE_BLOCKS / NONE_OF_THE_ABOVE / UNSURE</p>
          <p><b>selected_block_ids:</b> ________________</p>
          <p><b>evidence_complete:</b> yes / no</p>
          <p><b>reviewer_note:</b> ________________________________________________</p>
        </div>""")
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>Phase 23.11.6 Gold Evidence 盲审包</title>
<style>
body {{ font-family: sans-serif; max-width: 1000px; margin: 20px auto; padding: 0 20px; }}
.item {{ border: 1px solid #ccc; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
.candidate {{ border-left: 4px solid #888; margin: 10px 0; padding: 8px 12px; background: #fafafa; }}
.gold {{ background: #fff8e1; border: 1px solid #f0c; padding: 8px 12px; }}
.block {{ background: #e8f5e9; padding: 8px 12px; margin: 6px 0; }}
.ctx {{ background: #f3e5f5; padding: 6px 10px; margin: 4px 0; font-size: 0.9em; }}
h3 {{ margin-top: 0; }} h4 {{ margin: 6px 0; }}
</style></head><body>
<h1>Phase 23.11.6 Gold Evidence 盲审包（第一轮：Evidence Alignment）</h1>
<p>共 {len(items)} 条待审核。请勿参考系统预测或Gold标签（本页已隐藏）。</p>
{''.join(cards)}
</body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())