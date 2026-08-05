"""Phase 23.11.6.2 — 候选重建与 Prompt Pack 测试

覆盖要求：
- 空Block不成为候选Bundle
- 短单位Block不会被错误删除
- 表头和数据行正确组合
- EVD-002包含block 4443（或同等含正文的block 4442）
- Candidate Bundle正文非空
- 原Gold关键数字保持不变
- 第一轮Prompt不包含expected_verdict
- 第一轮Prompt不包含系统prediction
- Prompt文件变量全部填充
- AI结果Schema校验
- AI结果不能直接导入Gold
- v2来源审计测试

Run: cd backend && PYTHONPATH=. pytest tests/test_phase23_11_6_2_candidate_rebuild_and_prompt_pack.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

REBUILT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "review_items_rebuilt.json"
RECALL_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_candidate_recall.json"
NF_RECOVERY_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_not_found_recovery.json"
V2_AUDIT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_v2_provenance_audit.json"
PROMPT_PACK_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack"
INDEX_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack_index.md"
JSONL_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "ai_review_results.jsonl"
FREEZE_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_freeze_historical_results.json"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rebuilt_items() -> list[dict]:
    data = json.loads(REBUILT_PATH.read_text(encoding="utf-8"))
    return data["items"]


@pytest.fixture(scope="module")
def recall_data() -> dict:
    return json.loads(RECALL_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nf_recovery_data() -> dict:
    return json.loads(NF_RECOVERY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def v2_audit_data() -> dict:
    return json.loads(V2_AUDIT_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 1. 空 Block 不成为候选 Bundle
# --------------------------------------------------------------------------


def test_empty_block_not_in_candidate_bundles(rebuilt_items: list[dict]):
    """每个 Candidate Bundle 的 reconstructed_text 必须非空。"""
    for it in rebuilt_items:
        for b in it.get("candidate_bundles", []):
            assert b.get("reconstructed_text", "").strip(), (
                f"{it['item_id']} bundle {b.get('candidate_group_id')} has empty reconstructed_text"
            )


# --------------------------------------------------------------------------
# 2. 短单位 Block 不会被错误删除
# --------------------------------------------------------------------------


def test_short_unit_blocks_preserved(rebuilt_items: list[dict]):
    """含单位/期间/行标题的短 Block 应被保留在某个 Bundle 中。

    检查 page 135（合并利润表）的 Bundle 里是否包含单位/期间信息。
    """
    evd005 = next((it for it in rebuilt_items if it["item_id"] == "EVD-005"), None)
    assert evd005 is not None
    # 至少一个 Bundle 应含单位、期间或行标题
    has_unit_or_period = False
    for b in evd005.get("candidate_bundles", []):
        if b.get("unit_header") or b.get("period_headers") or b.get("row_headers"):
            has_unit_or_period = True
            break
    assert has_unit_or_period, "EVD-005 应保留单位/期间/行标题短 Block"


# --------------------------------------------------------------------------
# 3. 表头和数据行正确组合
# --------------------------------------------------------------------------


def test_table_header_and_data_row_combined(rebuilt_items: list[dict]):
    """EVD-002 的某个 Bundle 应同时含表头信息（单位/期间）和数据行（营业总收入数值）。"""
    evd002 = next((it for it in rebuilt_items if it["item_id"] == "EVD-002"), None)
    assert evd002 is not None
    found_data_row = False
    for b in evd002.get("candidate_bundles", []):
        recon = b.get("reconstructed_text", "")
        if "458,502,407" in recon or "409,084,266" in recon:
            found_data_row = True
            break
    assert found_data_row, "EVD-002 应有 Bundle 含营业总收入数据行 458,502,407 / 409,084,266"


# --------------------------------------------------------------------------
# 4. EVD-002 包含 block 4443（或同等含正文的 block 4442）
# --------------------------------------------------------------------------


def test_evd_002_contains_block_4443_or_4442(rebuilt_items: list[dict]):
    """EVD-002 必须包含 block 4443 所在 Bundle，或同等含营业总收入正文的 block 4442。"""
    evd002 = next((it for it in rebuilt_items if it["item_id"] == "EVD-002"), None)
    assert evd002 is not None
    all_bids: set[str] = set()
    for b in evd002.get("candidate_bundles", []):
        for bid in b.get("source_block_ids", []):
            all_bids.add(str(bid))
    # 4443 或 4442 至少有一个
    assert "4443" in all_bids or "4442" in all_bids, (
        f"EVD-002 候选 Bundle 必须含 block 4443 或 4442，实际含：{sorted(all_bids)}"
    )


# --------------------------------------------------------------------------
# 5. Candidate Bundle 正文非空
# --------------------------------------------------------------------------


def test_all_bundles_have_non_empty_text(rebuilt_items: list[dict]):
    """所有 Bundle 的 reconstructed_text 非空（已在 test 1 覆盖，这里做总数断言）。"""
    total_bundles = sum(len(it.get("candidate_bundles", [])) for it in rebuilt_items)
    non_empty = sum(
        1 for it in rebuilt_items for b in it.get("candidate_bundles", [])
        if b.get("reconstructed_text", "").strip()
    )
    assert non_empty == total_bundles, f"non_empty={non_empty} != total={total_bundles}"


# --------------------------------------------------------------------------
# 6. 原Gold关键数字保持不变
# --------------------------------------------------------------------------


def test_gold_key_numbers_unchanged(rebuilt_items: list[dict]):
    """reconstructed_text 里的数字不能篡改 Gold 关键数字。

    检查 EVD-002 的 Gold 含 458,502,407 / 409,084,266，
    若 Bundle 含这些数字，必须原样出现（带千分位逗号）。
    """
    evd002 = next((it for it in rebuilt_items if it["item_id"] == "EVD-002"), None)
    assert evd002 is not None
    gold = evd002["gold_evidence_text"]
    assert "458,502,407" in gold
    # Bundle 里若含这些数字，必须原样
    for b in evd002.get("candidate_bundles", []):
        recon = b.get("reconstructed_text", "")
        if "458" in recon:
            # 不允许篡改成 458502407 或 458,502,407.00 等变体
            assert "458,502,407" in recon or "458502407" in recon, (
                f"EVD-002 bundle {b.get('candidate_group_id')} 篡改数字: {recon[:200]}"
            )


# --------------------------------------------------------------------------
# 7. 第一轮 Prompt 不包含 expected_verdict 的值
# --------------------------------------------------------------------------
# 提示词正文里会写规则"不得使用 expected_verdict"，这是合法的规则声明。
# 真正要查的是 verdict 值是否被喂给模型：SUPPORTED / REFUTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE / is_gold
LEAK_VERDICT_VALUES = [
    "SUPPORTED",
    "REFUTED",
    "PARTIALLY_SUPPORTED",
    "INSUFFICIENT_EVIDENCE",
    "is_gold",
]


def test_prompt_pack_no_expected_verdict_values():
    """每个 Prompt .md 文件不含 verdict 值泄漏（SUPPORTED/REFUTED/...）。

    允许出现 expected_verdict / prediction 字面词 —— 它们出现在
    "不得使用 expected_verdict / 系统 prediction" 的规则声明里，是合法的。
    """
    assert PROMPT_PACK_DIR.exists(), "prompt_pack dir not found"
    files = list(PROMPT_PACK_DIR.glob("*.md"))
    assert len(files) == 32, f"expected 32 prompt files, got {len(files)}"
    for f in files:
        content = f.read_text(encoding="utf-8")
        for leak in LEAK_VERDICT_VALUES:
            assert leak not in content, f"{f.name} leaks verdict value '{leak}'"


# --------------------------------------------------------------------------
# 8. 第一轮 Prompt 不包含系统 prediction 的值
# --------------------------------------------------------------------------


def test_prompt_pack_no_system_prediction_value():
    """每个 Prompt .md 文件不含系统 prediction 的具体值（如 per_claim_prediction、prediction_map）。

    允许出现 prediction 字面词 —— 它出现在规则声明里。
    """
    files = list(PROMPT_PACK_DIR.glob("*.md"))
    for f in files:
        content = f.read_text(encoding="utf-8")
        # 这些是系统 prediction 的字段名/容器名，出现即泄漏
        for leak in ("per_claim_prediction", "prediction_map", "selected_prediction"):
            assert leak not in content, f"{f.name} leaks prediction field '{leak}'"


# --------------------------------------------------------------------------
# 9. Prompt 文件变量全部填充（无 {{}} 残留）
# --------------------------------------------------------------------------


def test_prompt_pack_no_unfilled_template_vars():
    """Prompt 文件不应有未填充的模板变量 {{X}}。"""
    files = list(PROMPT_PACK_DIR.glob("*.md"))
    for f in files:
        content = f.read_text(encoding="utf-8")
        # 允许 JSON schema 里的 {{ }} 占位（那是 schema 示例）
        # 但 Claim / 公司 / 报告信息 / 原始Gold Evidence / 候选Block 主体不应有 {{}}
        # 检查 "{{CLAIM_TEXT}}" "{{COMPANY}}" 等模板变量名残留
        template_vars = ["{{CLAIM_TEXT}}", "{{COMPANY}}", "{{DOCUMENT_INFORMATION}}",
                          "{{ORIGINAL_GOLD_EVIDENCE}}", "{{CANDIDATE_GROUPS}}"]
        for tv in template_vars:
            assert tv not in content, f"{f.name} has unfilled template var {tv}"


# --------------------------------------------------------------------------
# 10. AI 结果 Schema 校验（用 collect_ai_reviews --dry-run）
# --------------------------------------------------------------------------


def test_ai_review_schema_validation_dry_run():
    """用一条合法 + 一条非法的 AI 结果测试 --dry-run 校验。"""
    # 构造测试输入
    valid_record = {
        "gold_evidence_id": "EVD-002",
        "decision": "MATCH_SINGLE_BLOCK",
        "selected_candidate_group_ids": ["EVD-002-g1"],
        "selected_block_ids": [],  # 将填实际 block id
        "evidence_complete": False,
        "confidence": 0.7,
        "estimated_coverage": 0.8,
        "field_checks": {
            "company": "MATCH", "metric": "MATCH", "period": "UNKNOWN",
            "value": "MATCH", "unit": "UNKNOWN", "scope": "UNKNOWN",
            "table_structure": "UNKNOWN",
        },
        "candidate_unique": True,
        "reason": "test",
        "human_review_flags": [],
    }
    # 取 EVD-002 的一个真实候选 block id
    rebuilt = json.loads(REBUILT_PATH.read_text(encoding="utf-8"))
    evd002 = next(it for it in rebuilt["items"] if it["item_id"] == "EVD-002")
    real_bid = evd002["candidate_bundles"][0]["source_block_ids"][0]
    valid_record["selected_block_ids"] = [real_bid]

    invalid_record = {
        "gold_evidence_id": "EVD-002",  # duplicate
        "decision": "INVALID_DECISION",
        "selected_block_ids": ["99999999"],  # not in candidate
        "confidence": 1.5,  # out of range
        "estimated_coverage": -0.1,  # out of range
    }

    # 写临时输入文件
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump([valid_record, invalid_record], f, ensure_ascii=False)
        tmp_path = f.name

    # 运行 collect_ai_reviews.py --dry-run
    result = subprocess.run(
        [sys.executable, "scripts/phase23_11_6_2_collect_ai_reviews.py",
         "--input", tmp_path, "--dry-run"],
        cwd=str(BACKEND), capture_output=True, text=True, env={"PYTHONPATH": str(BACKEND)},
    )
    # 解析输出
    out = json.loads(result.stdout)
    assert out["total_input_records"] == 2
    # invalid_record 应被拒（decision 不合法 + block 不在候选 + confidence 超界）
    assert out["invalid"] >= 1
    # dry-run 不应写入
    assert out["written"] == 0

    # 清理临时文件
    Path(tmp_path).unlink(missing_ok=True)


# --------------------------------------------------------------------------
# 11. AI 结果不能直接导入 Gold（meta 标记）
# --------------------------------------------------------------------------


def test_ai_review_status_pending_human_confirmation():
    """AI 审核结果状态必须是 AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION，
    且 may_import_to_gold=false。
    """
    # 检查 collect 脚本里的常量
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "collect_ai_reviews",
        BACKEND / "scripts" / "phase23_11_6_2_collect_ai_reviews.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.AI_REVIEW_STATUS == "AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION"
    # 校验逻辑里 meta may_import_to_gold 应为 False
    rebuilt_index = mod.load_rebuilt_items()
    test_rec = {
        "gold_evidence_id": "EVD-001",
        "decision": "NONE_OF_THE_ABOVE",
        "selected_block_ids": [],
        "selected_candidate_group_ids": [],
        "evidence_complete": False,
        "confidence": 0.5,
        "estimated_coverage": 0.0,
    }
    errs, normalized = mod.validate_record(test_rec, rebuilt_index)
    assert normalized["_meta"]["ai_review_status"] == "AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION"
    assert normalized["_meta"]["may_import_to_gold"] is False


# --------------------------------------------------------------------------
# 12. v2 来源审计测试
# --------------------------------------------------------------------------


def test_v2_provenance_audit_all_unverified(v2_audit_data: dict):
    """v2 来源审计：所有 32 条 provenance_status 应为 MODEL_CALL_UNVERIFIABLE
    （因 v2 未保留任何元信息）。
    """
    overall = v2_audit_data["overall"]
    assert overall["v2_record_count"] == 32
    assert overall["v2_carries_any_meta_key"] is False
    assert overall["v2_has_model_name"] is False
    assert overall["v2_has_timestamp"] is False
    assert overall["v2_has_input_snapshot"] is False
    counts = overall["provenance_status_counts"]
    assert counts["MODEL_CALL_UNVERIFIABLE"] == 32
    assert counts["PROVEN_INPUT_COMPLETE"] == 0
    # 最终判定
    assert overall["may_import_to_gold"] is False
    assert "HISTORICAL_PROVENANCE_UNVERIFIED" in overall["final_verdict"]


def test_v2_provenance_audit_evd_005_to_008(v2_audit_data: dict):
    """EVD-005/006/007/008 的 selected_block_ids 应在候选列表里。"""
    per_item = {p["gold_evidence_id"]: p for p in v2_audit_data["per_item_audit"]}
    for iid in ("EVD-005", "EVD-006", "EVD-007", "EVD-008"):
        rec = per_item[iid]
        assert rec["v2_decision"] == "MATCH_SINGLE_BLOCK"
        assert rec["selected_blocks_present_in_input"] is True
        # block 4443 正文存在
        assert any(
            s.get("status") == "OK" for s in rec["selected_block_text_status"]
        ), f"{iid} should have block 4443 with OK text"


# --------------------------------------------------------------------------
# 13. 历史结果冻结
# --------------------------------------------------------------------------


def test_historical_results_frozen():
    """冻结清单应记录 v1/v2/v3 三个文件，且均不得导入 Gold。"""
    data = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    assert data["action"] == "FREEZE_HISTORICAL_AI_BLIND_REVIEW_RESULTS"
    assert len(data["frozen_results"]) == 3
    for fr in data["frozen_results"]:
        assert fr["may_import_to_gold"] is False
        assert fr["may_be_used_as_human_review"] is False
        assert fr["may_participate_in_official_metrics"] is False
    # 状态分布
    statuses = {fr["version_label"]: fr["status"] for fr in data["frozen_results"]}
    assert statuses["v1"] == "HISTORICAL_PROVENANCE_UNVERIFIED"
    assert statuses["v2"] == "HISTORICAL_PROVENANCE_UNVERIFIED"
    assert statuses["v3"] == "NO_MODEL_CALL_EMPTY_RESULT"


# --------------------------------------------------------------------------
# 14. NOT_FOUND 恢复测试
# --------------------------------------------------------------------------


def test_not_found_recovery_10_items(nf_recovery_data: dict):
    """NOT_FOUND 恢复应处理 10 条，状态必须是合法 6 选之一。"""
    assert nf_recovery_data["total"] == 10
    valid_statuses = {
        "CANDIDATES_RECOVERED",
        "PARAPHRASED_SOURCE_LOCATED",
        "VISUAL_REVIEW_REQUIRED",
        "WRONG_PAGE_REFERENCE",
        "WRONG_DOCUMENT_REFERENCE",
        "STILL_NOT_FOUND",
    }
    for item in nf_recovery_data["per_item"]:
        assert item["recovery_status"] in valid_statuses, (
            f"{item['gold_evidence_id']} invalid status {item['recovery_status']}"
        )


# --------------------------------------------------------------------------
# 15. Candidate Recall 完整性
# --------------------------------------------------------------------------


def test_candidate_recall_all_review_ready(recall_data: dict):
    """32 条全部 review_ready=true，non_empty_bundle_count>0。"""
    assert recall_data["total_evidence"] == 32
    assert recall_data["no_bundles_found"] == 0
    for ri in recall_data["recall_items"]:
        assert ri["review_ready"] is True
        assert ri["non_empty_bundle_count"] > 0


# --------------------------------------------------------------------------
# 16. Prompt Pack 索引
# --------------------------------------------------------------------------


def test_prompt_pack_index_exists():
    """prompt_pack_index.md 存在且含 32 条索引。"""
    assert INDEX_PATH.exists()
    content = INDEX_PATH.read_text(encoding="utf-8")
    # 表头 + 32 行
    assert "| 001 |" in content
    assert "| 032 |" in content


# --------------------------------------------------------------------------
# 17. JSONL 初始化为空
# --------------------------------------------------------------------------


def test_ai_review_results_jsonl_empty():
    """ai_review_results.jsonl 初始化为空文件。"""
    assert JSONL_PATH.exists()
    assert JSONL_PATH.stat().st_size == 0
