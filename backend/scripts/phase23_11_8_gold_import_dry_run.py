"""Phase 23.11.8-A — Gold Import Preview Dry Run

基于 Phase 23.11.7 Gold Import 前置验证结果，执行 dry-run 验证。

读取：
- data/gold_review/phase23_11_6_2/ai_review_results.jsonl
- data/gold_review/phase23_11_6_2/claim_gold_conflicts.json
- data/gold_review/phase23_11_6_2/import_candidate.json

检查（Evidence 层 / 人工确认层 / 冲突层）：
1. Evidence ID 存在
2. Block ID 存在（document_blocks 表）
3. Block 属于 candidate group
4. selected_block_ids 非空
5. human_confirmed=true 且 confirmed_by=user
6. gold_evidence_id 不存在于 claim_gold_conflicts.json

输出：
- data/gold_review/phase23_11_6_2/gold_import_dry_run_report.md

严格边界（本脚本不执行）：
- 不修改 data/gold/
- 不执行 import_human_gold_review.py
- 不改变 ai_review_results.jsonl
- 不运行 phase23_11_7 acceptance / Oracle evaluation / Real E2E

Run: cd backend && PYTHONPATH=. python scripts/phase23_11_8_gold_import_dry_run.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REVIEW_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2"
JSONL_PATH = REVIEW_DIR / "ai_review_results.jsonl"
CONFLICTS_PATH = REVIEW_DIR / "claim_gold_conflicts.json"
IMPORT_CANDIDATE_PATH = REVIEW_DIR / "import_candidate.json"
PREVIEW_PATH = REVIEW_DIR / "gold_import_preview.json"
REPORT_PATH = REVIEW_DIR / "gold_import_dry_run_report.md"
DB_PATH = REPO_ROOT / "data" / "finproof.db"
REBUILT_PATH = REVIEW_DIR / "review_items_rebuilt.json"

ALLOWED_DECISIONS = {"MATCH_SINGLE_BLOCK", "MATCH_MULTIPLE_BLOCKS"}
REJECTED_DECISIONS = {"NONE_FOUND", "NONE_OF_THE_ABOVE", "UNSURE"}


def load_review_records() -> dict:
    """读取 ai_review_results.jsonl → {gold_evidence_id: record}"""
    recs = {}
    if JSONL_PATH.exists():
        for line in JSONL_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            recs[r["gold_evidence_id"]] = r
    return recs


def load_conflicts() -> dict:
    """读取 claim_gold_conflicts.json → {gold_evidence_id: conflict}"""
    conf = json.loads(CONFLICTS_PATH.read_text(encoding="utf-8"))
    return {c["gold_evidence_id"]: c for c in conf.get("conflicts", [])}


def load_import_candidates() -> list:
    """读取 import_candidate.json → candidates list"""
    data = json.loads(IMPORT_CANDIDATE_PATH.read_text(encoding="utf-8"))
    return data.get("candidates", [])


def load_candidate_group_block_ids() -> dict:
    """读取 review_items_rebuilt.json → {gold_evidence_id: set(block_ids)}（含 NOT_FOUND 来源）"""
    index = {}
    data = json.loads(REBUILT_PATH.read_text(encoding="utf-8"))
    for it in data["items"]:
        bids: set[str] = set()
        for b in it.get("candidate_bundles", []):
            for bid in b.get("source_block_ids", []):
                bids.add(str(bid))
        index[it["item_id"]] = bids
    return index


def check_block_exists(conn: sqlite3.Connection, block_id: int) -> bool:
    row = conn.execute("SELECT id FROM document_blocks WHERE id=?", (block_id,)).fetchone()
    return row is not None


def validate_evidence(conn: sqlite3.Connection, iid: str, rec: dict,
                      group_bids: dict, conflicts: dict) -> dict:
    """Evidence 层 + 人工确认层 + 冲突层检查，返回检查明细与判定。"""
    checks = {}
    errors = []

    # Evidence 层
    checks["evidence_id_exists"] = iid in group_bids or iid in {  # noqa: C901
        c.get("gold_evidence_id") for c in conflicts.values()
    }
    sel_bids = [str(b) for b in (rec.get("selected_block_ids") or [])]
    checks["selected_block_ids_non_empty"] = bool(sel_bids)

    # Block ID 存在 + 属于 candidate group
    blocks_exist = True
    blocks_in_group = True
    cand_bids = group_bids.get(iid, set())
    for bid in sel_bids:
        try:
            bid_int = int(bid)
        except (TypeError, ValueError):
            blocks_exist = False
            blocks_in_group = False
            continue
        if not check_block_exists(conn, bid_int):
            blocks_exist = False
        if cand_bids and bid not in cand_bids:
            blocks_in_group = False
    checks["block_ids_exist_in_document_blocks"] = blocks_exist
    checks["blocks_belong_to_candidate_group"] = blocks_in_group

    # 人工确认层
    meta = rec.get("_meta", {})
    checks["human_confirmed"] = meta.get("human_review_status") == "HUMAN_CONFIRMED"
    checks["confirmed_by_user"] = meta.get("confirmed_by") == "user"
    checks["decision_allowed"] = rec.get("decision") in ALLOWED_DECISIONS

    # 冲突层
    checks["no_conflict"] = iid not in conflicts

    eligible = all(checks.values())
    if not eligible:
        for k, v in checks.items():
            if not v:
                errors.append(k)
    return {"checks": checks, "eligible": eligible, "errors": errors}


def main() -> int:
    print("=" * 60)
    print("Phase 23.11.8-A Gold Import Dry Run")
    print("=" * 60)

    recs = load_review_records()
    conflicts = load_conflicts()
    candidates = load_import_candidates()
    group_bids = load_candidate_group_block_ids()
    conn = sqlite3.connect(DB_PATH)

    # 所有出现在 ai_review_results.jsonl 的 Evidence
    all_ids = sorted(recs.keys())
    print(f"review records: {len(all_ids)} -> {all_ids}")

    eligible_list = []
    rejected_list = []

    for iid in all_ids:
        rec = recs[iid]
        decision = rec.get("decision")
        verdict = validate_evidence(conn, iid, rec, group_bids, conflicts)

        if verdict["eligible"]:
            eligible_list.append({"gold_evidence_id": iid, "decision": decision,
                                  "selected_block_ids": rec.get("selected_block_ids", []),
                                  "reason": "全部检查通过"})
        else:
            # 判定拒绝原因
            reasons = []
            c = verdict["checks"]
            if decision in REJECTED_DECISIONS:
                reasons.append(f"decision={decision} 禁止导入")
            if not c["human_confirmed"]:
                reasons.append("human_confirmed 缺失")
            if not c["confirmed_by_user"]:
                reasons.append("confirmed_by 非 user")
            if not c["no_conflict"]:
                cfl = conflicts.get(iid, {})
                reasons.append(f"存在冲突 {cfl.get('conflict_type')} ({cfl.get('status')})")
            if not c["decision_allowed"]:
                reasons.append(f"decision={decision} 不在允许范围")
            if not c["selected_block_ids_non_empty"]:
                reasons.append("selected_block_ids 为空")
            if not c["block_ids_exist_in_document_blocks"]:
                reasons.append("Block ID 不存在于 document_blocks")
            if not c["blocks_belong_to_candidate_group"]:
                reasons.append("Block 不属于 candidate group")
            rejected_list.append({"gold_evidence_id": iid, "decision": decision,
                                  "reason": "; ".join(reasons) or "未知原因"})

    conn.close()

    # 生成报告
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append("# Phase 23.11.8-A Gold Import Dry Run 报告")
    lines.append("")
    lines.append(f"> 生成时间：{now}")
    lines.append(f"> 输入：ai_review_results.jsonl（{len(all_ids)} 条）、claim_gold_conflicts.json、import_candidate.json")
    lines.append("> 性质：**dry-run 只读验证，不导入 Gold，不修改任何数据**")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- candidate_count（review records）: **{len(all_ids)}**")
    lines.append(f"- eligible_count: **{len(eligible_list)}**")
    lines.append(f"- rejected_count: **{len(rejected_list)}**")
    lines.append("")
    lines.append("## Eligible")
    lines.append("")
    lines.append("| Evidence ID | decision | selected_block_ids | 说明 |")
    lines.append("| --- | --- | --- | --- |")
    for e in eligible_list:
        lines.append(f"| {e['gold_evidence_id']} | {e['decision']} | {e['selected_block_ids']} | {e['reason']} |")
    lines.append("")
    lines.append("## Rejected")
    lines.append("")
    lines.append("| Evidence ID | decision | 原因 |")
    lines.append("| --- | --- | --- |")
    for r in rejected_list:
        lines.append(f"| {r['gold_evidence_id']} | {r['decision']} | {r['reason']} |")
    lines.append("")
    lines.append("## 严格边界确认")
    lines.append("")
    lines.append("- 未修改 `data/gold/`：✅（本脚本只读）")
    lines.append("- 未执行 `import_human_gold_review.py`：✅（未调用）")
    lines.append("- 未改变 `ai_review_results.jsonl`：✅（只读）")
    lines.append("- 未运行 phase23_11_7 acceptance：✅")
    lines.append("- 未运行 Oracle evaluation：✅")
    lines.append("- 未运行 Real E2E：✅")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote: {REPORT_PATH}")
    print(f"eligible={len(eligible_list)} rejected={len(rejected_list)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
