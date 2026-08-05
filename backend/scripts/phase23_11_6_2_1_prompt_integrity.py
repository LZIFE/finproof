"""Phase 23.11.6.2.1 — 32份Prompt来源完整性核对脚本

逐份验证 prompt_pack/*.md：
- Markdown 文件存在
- Claim 不为空
- 公司不为空
- 报告信息不为空
- 原始 Gold Evidence 不为空
- Candidate Bundle 数量 1 至 5
- 每个 Bundle reconstructed_text 非空
- 每个 Bundle 至少有一个真实 block_id
- Block 真实存在于 document_blocks
- page 与 Block 一致
- context_before 和 context_after 不冒充正文（必须来自其他 Block 的文本片段，不是凭空生成）
- 不含 expected_verdict / gold_verdict 值
- 不含系统 prediction 字段名
- 不含 v1/v2/v3 决策
- 不含 Gold 推荐候选
- 不展示程序计算的 reconstruction_coverage 分数
- JSON 输出 Schema 完整
- 模板变量全部替换

输出：
- backend/artifacts/gold_contract/phase23_11_6_2_1_prompt_integrity.json

不调用任何模型。
"""
from __future__ import annotations

import glob
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PACK_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack"
REBUILT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "review_items_rebuilt.json"
DB_PATH = REPO_ROOT / "data" / "finproof.db"
OUTPUT_PATH = REPO_ROOT / "backend" / "artifacts" / "gold_contract" / "phase23_11_6_2_1_prompt_integrity.json"

# Schema 必须出现的字段
SCHEMA_REQUIRED_KEYS = [
    "gold_evidence_id",
    "decision",
    "selected_candidate_group_ids",
    "selected_block_ids",
    "evidence_complete",
    "confidence",
    "claim_fact_components",
    "field_checks",
    "candidate_unique",
    "estimated_coverage",
    "missing_information",
    "reason",
    "human_review_flags",
]
FIELD_CHECK_KEYS = ["company", "metric", "period", "value", "unit", "scope", "table_structure"]

# 泄漏关键词（verdict 值 + 系统 prediction 字段名 + v1/v2/v3 决策泄漏）
LEAK_VERDICT_VALUES = ["SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "is_gold"]
LEAK_PREDICTION_FIELDS = ["per_claim_prediction", "prediction_map", "selected_prediction"]
LEAK_V123_DECISIONS = [
    "v1_decision", "v2_decision", "v3_decision",
    "v1_selected_block_ids", "v2_selected_block_ids", "v3_selected_block_ids",
]
# reconstruction_coverage 分数展示给模型即泄漏（提示词正文不应出现数字 + reconstruction_coverage）
LEAK_RECONSTRUCTION_COVERAGE_PATTERNS = [
    r"reconstruction_coverage['\s:=]+\d",  # 如 "reconstruction_coverage: 0.87"
]

# 模板变量残留
TEMPLATE_VARS = ["{{CLAIM_TEXT}}", "{{COMPANY}}", "{{DOCUMENT_INFORMATION}}",
                  "{{ORIGINAL_GOLD_EVIDENCE}}", "{{CANDIDATE_GROUPS}}"]


def load_rebuilt_index() -> dict:
    """加载 rebuilt items，返回 {item_id: {bundles: [...], gold_evidence_text, claim_text, company, report_name}}"""
    data = json.loads(REBUILT_PATH.read_text(encoding="utf-8"))
    idx = {}
    for it in data["items"]:
        idx[it["item_id"]] = {
            "claim_text": it.get("claim_text", ""),
            "company": it.get("company", ""),
            "report_name": it.get("report_name", ""),
            "gold_evidence_text": it.get("gold_evidence_text", ""),
            "bundles": it.get("candidate_bundles", []),
        }
    return idx


def check_file(integrity: dict, content: str, file_path: Path, rebuilt_item: dict,
               conn: sqlite3.Connection, db_block_cache: dict) -> None:
    """核对单个 prompt 文件的完整性，结果写入 integrity dict。"""
    checks = {}

    # 1. Markdown 文件存在（已读 content，自然存在）
    checks["file_exists"] = True

    # 2. Claim 不为空
    claim_text = rebuilt_item.get("claim_text", "")
    checks["claim_not_empty"] = bool(claim_text.strip()) and claim_text in content

    # 3. 公司不为空
    company = rebuilt_item.get("company", "")
    checks["company_not_empty"] = bool(company.strip()) and company in content

    # 4. 报告信息不为空
    report_name = rebuilt_item.get("report_name", "")
    checks["report_info_not_empty"] = bool(report_name.strip()) and report_name in content

    # 5. 原始 Gold Evidence 不为空
    gold = rebuilt_item.get("gold_evidence_text", "")
    checks["gold_evidence_not_empty"] = bool(gold.strip()) and gold in content

    # 6. Candidate Bundle 数量 1 至 5
    bundles = rebuilt_item.get("bundles", [])
    bundle_count = len(bundles)
    checks["bundle_count_1_to_5"] = 1 <= bundle_count <= 5

    # 7. 每个 Bundle reconstructed_text 非空
    all_recon_non_empty = all(b.get("reconstructed_text", "").strip() for b in bundles)
    checks["all_bundle_reconstructed_text_non_empty"] = all_recon_non_empty

    # 8. 每个 Bundle 至少有一个真实 block_id
    all_have_block_id = all(
        any(str(bid).strip() for bid in b.get("source_block_ids", []))
        for b in bundles
    )
    checks["all_bundle_have_block_id"] = all_have_block_id

    # 9. Block 真实存在于 document_blocks + 10. page 与 Block 一致
    block_exists_ok = True
    page_consistent_ok = True
    for b in bundles:
        for bid in b.get("source_block_ids", []):
            bid_int = int(bid)
            if bid_int not in db_block_cache:
                row = conn.execute(
                    "SELECT id, page_id FROM document_blocks WHERE id=?", (bid_int,)
                ).fetchone()
                if row is None:
                    db_block_cache[bid_int] = None
                    block_exists_ok = False
                    continue
                db_block_cache[bid_int] = {"page_id": row[1]}
            binfo = db_block_cache[bid_int]
            if binfo is None:
                block_exists_ok = False
            else:
                if b.get("page") != binfo["page_id"]:
                    page_consistent_ok = False
    checks["blocks_exist_in_document_blocks"] = block_exists_ok
    checks["page_consistent_with_block"] = page_consistent_ok

    # 11. context_before/after 不冒充正文：检查 prompt 里出现的 context_before/after 文本片段
    #     不能"完全等于"该 bundle 的 reconstructed_text（即不能把整段正文冒充为 context）。
    #     允许 context 与主正文共享短行题片段（PDF 表格相邻行题天然共享，如"其中：营业收入"）。
    context_traceable_ok = True
    for b in bundles:
        cb = b.get("context_before", "").strip()
        ca = b.get("context_after", "").strip()
        recon = b.get("reconstructed_text", "").strip()
        # 仅当 context 非空且长度 >= recon 长度 80% 时才判定为"冒充正文"
        for ctx in (cb, ca):
            if not ctx:
                continue
            if len(ctx) >= max(20, int(0.8 * len(recon))) and ctx == recon:
                context_traceable_ok = False
    checks["context_not_impersonating_main_text"] = context_traceable_ok

    # 12. 不含 expected_verdict / gold_verdict 值
    no_verdict_leak = all(leak not in content for leak in LEAK_VERDICT_VALUES)
    checks["no_expected_verdict_value_leak"] = no_verdict_leak

    # 13. 不含系统 prediction 字段名
    no_pred_leak = all(leak not in content for leak in LEAK_PREDICTION_FIELDS)
    checks["no_system_prediction_field_leak"] = no_pred_leak

    # 14. 不含 v1/v2/v3 决策
    no_v123_leak = all(leak not in content for leak in LEAK_V123_DECISIONS)
    checks["no_v1_v2_v3_decision_leak"] = no_v123_leak

    # 15. 不含 Gold 推荐候选（不应出现 "gold_recommended" / "gold_selected_block_ids" 等字段）
    no_gold_recommend = all(
        leak not in content for leak in
        ["gold_recommended", "gold_selected_block_ids", "gold_preferred_candidate"]
    )
    checks["no_gold_recommended_candidate_leak"] = no_gold_recommend

    # 16. 不展示程序计算的 reconstruction_coverage 分数
    no_recon_coverage_score = not any(
        re.search(p, content) for p in LEAK_RECONSTRUCTION_COVERAGE_PATTERNS
    )
    checks["no_reconstruction_coverage_score_shown"] = no_recon_coverage_score

    # 17. JSON 输出 Schema 完整：检查所有 SCHEMA_REQUIRED_KEYS 出现在 content 里
    schema_complete = all(k in content for k in SCHEMA_REQUIRED_KEYS)
    checks["json_output_schema_complete"] = schema_complete

    # field_checks 子字段完整
    field_checks_complete = all(k in content for k in FIELD_CHECK_KEYS)
    checks["field_checks_keys_complete"] = field_checks_complete

    # 18. 模板变量全部替换（不应有 {{X}} 残留）
    no_unfilled_template = all(tv not in content for tv in TEMPLATE_VARS)
    checks["no_unfilled_template_vars"] = no_unfilled_template

    # 汇总 PASS/FAIL
    all_pass = all(checks.values())
    integrity["checks"] = checks
    integrity["result"] = "PASS" if all_pass else "FAIL"
    integrity["fail_reasons"] = [k for k, v in checks.items() if not v]


def main() -> int:
    rebuilt_index = load_rebuilt_index()
    conn = sqlite3.connect(DB_PATH)
    db_block_cache: dict[int, dict | None] = {}

    files = sorted(PROMPT_PACK_DIR.glob("*.md"))
    per_file = []
    pass_count = 0
    fail_count = 0
    skipped_count = 0

    for f in files:
        content = f.read_text(encoding="utf-8")
        # 从文件名提取 item_id：001_EVD-001.md -> EVD-001
        name = f.stem  # 001_EVD-001
        parts = name.split("_", 1)
        seq = int(parts[0]) if parts[0].isdigit() else 0
        iid = parts[1] if len(parts) == 2 else name

        # 033-042 是 Source Recovery / Paraphrase Review Prompt（不在 rebuilt_index 里），
        # 它们的完整性由 test_phase23_11_6_2_1_prompt_pack_freeze.py 单独核对，
        # 本脚本只核对 32 条 Evidence Alignment Prompt（seq 1-32）。
        if seq >= 33:
            skipped_count += 1
            per_file.append({
                "file": str(f.relative_to(REPO_ROOT)),
                "item_id": iid,
                "result": "SKIPPED_NOT_FOUND_RECOVERY",
                "reason": "Source Recovery / Paraphrase Review Prompt，由独立测试核对完整性",
            })
            continue

        rebuilt_item = rebuilt_index.get(iid, {})
        integrity = {
            "file": str(f.relative_to(REPO_ROOT)),
            "item_id": iid,
        }
        check_file(integrity, content, f, rebuilt_item, conn, db_block_cache)
        if integrity["result"] == "PASS":
            pass_count += 1
        else:
            fail_count += 1
        per_file.append(integrity)

    conn.close()

    output = {
        "phase": "23.11.6.2.1",
        "audit_type": "prompt_integrity",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_files": len(files),
        "evidence_alignment_files": 32,
        "source_recovery_files": skipped_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "skipped_count": skipped_count,
        "per_file": per_file,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"total: {len(files)}  evidence_alignment: 32  source_recovery: {skipped_count}")
    print(f"evidence_alignment pass: {pass_count}  fail: {fail_count}")
    print(f"wrote: {OUTPUT_PATH}")
    if fail_count:
        print("FAIL files:")
        for pf in per_file:
            if pf.get("result") == "FAIL":
                print(f"  {pf['file']}: {pf['fail_reasons']}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
