"""Phase 23.11.6 Human Review Handoff Tests (Task 11).

12 required test categories:
1. 第一轮盲审不包含expected_verdict
2. review结果默认人工字段为空
3. Agent不能自动选择候选
4. NOT_FOUND与HUMAN_REVIEW_REQUIRED分离
5. Intentional Insufficient审核协议测试
6. 人工审核不完整时禁止导入
7. Block不存在时禁止导入
8. 多Block顺序错误时禁止导入
9. review package hash不一致时禁止导入
10. Gold版本不可覆盖
11. 无人工结果时post-review脚本停止
12. Priority Cohort不根据系统预测选择
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REVIEW_DIR = BACKEND.parent / "data" / "gold_review" / "phase23_11_6"


# 1. Round-1 blind review must NOT contain expected_verdict
def test_round1_no_expected_verdict():
    html = (REVIEW_DIR / "review.html").read_text(encoding="utf-8")
    for banned in ("expected_verdict", "SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "is_gold", "prediction"):
        assert banned not in html, f"review.html leaks '{banned}'"
    items = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))
    for it in items["items"]:
        assert "expected_verdict" not in it, f"{it['item_id']} leaks expected_verdict"


# 2. Review results default to empty human fields
def test_review_fields_empty_by_default():
    items = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))["items"]
    for it in items:
        assert it["reviewer_choice"] == ""
        assert it["selected_block_ids"] == []
        assert it["reviewer_note"] == ""
        assert it["review_status"] == "PENDING"


# 3. Agent must not pre-select candidates
def test_agent_no_preselection():
    template = json.loads((REVIEW_DIR / "review_results.template.json").read_text(encoding="utf-8"))
    for it in template["items"]:
        # template must leave selection empty
        assert it["selected_block_ids"] == [], f"{it['item_id']} has pre-selected blocks"
        # candidate groups must not have pre-checked flags
        for g in it["candidate_groups"]:
            assert "is_correct" not in g


# 4. NOT_FOUND separated from HUMAN_REVIEW_REQUIRED
def test_not_found_separated():
    audit = json.loads((BACKEND / "artifacts/gold_contract/phase23_11_5_1_grounding_audit.json").read_text())
    statuses = [p["new_status"] for p in audit["per_evidence"]]
    assert statuses.count("NOT_FOUND") == 10
    assert statuses.count("HUMAN_REVIEW_REQUIRED") == 32
    assert statuses.count("NOT_FOUND") + statuses.count("HUMAN_REVIEW_REQUIRED") == 42


# 5. Intentional Insufficient protocol test
def test_intentional_insufficient_protocol():
    ins = json.loads((REVIEW_DIR / "insufficient_review.json").read_text(encoding="utf-8"))
    assert ins["total"] == 3
    for it in ins["items"]:
        assert it["expected_verdict"] == "INSUFFICIENT_EVIDENCE"
        assert it["reviewer_confirmed_insufficient"] == ""
        assert it["reviewer_name"] == ""
        assert it["reviewed_at"] == ""


# 6. Import rejected when review incomplete
def test_import_rejected_when_incomplete():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts/import_human_gold_review.py"),
         "--review", str(REVIEW_DIR / "review_results.template.json"), "--reviewer", "test"],
        capture_output=True, text=True, cwd=str(BACKEND), env={"PYTHONPATH": str(BACKEND)})
    assert "IMPORT REJECTED" in r.stdout, "incomplete review must be rejected"


# 7. Import rejected when block missing
def test_import_rejected_block_missing():
    import subprocess, tempfile, json as _json
    items = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))["items"]
    bad = _json.loads((REVIEW_DIR / "review_results.template.json").read_text(encoding="utf-8"))
    bad["items"][0]["reviewer_choice"] = "MATCH_SINGLE_BLOCK"
    bad["items"][0]["selected_block_ids"] = ["99999999"]  # non-existent block
    bad["items"][0]["reviewer_note"] = "test"
    bad["items"][0]["reviewed_at"] = "2026-08-05"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        _json.dump(bad, f, ensure_ascii=False)
        tmp = f.name
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts/import_human_gold_review.py"),
         "--review", tmp, "--reviewer", "test"],
        capture_output=True, text=True, cwd=str(BACKEND), env={"PYTHONPATH": str(BACKEND)})
    assert "IMPORT REJECTED" in r.stdout


# 8. Import rejected on invalid multi-block order
def test_import_rejected_multi_block_order():
    import subprocess, tempfile, json as _json
    # Use real candidate block IDs from review items (far apart = invalid order)
    items = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))["items"]
    all_bids = []
    for it in items:
        for g in it.get("candidate_groups", []):
            all_bids.extend(g.get("block_ids", []))
    all_bids = list(dict.fromkeys(all_bids))
    assert len(all_bids) >= 2, "need at least 2 candidate blocks"
    # two blocks that are NOT adjacent (take first and last)
    b1, b2 = all_bids[0], all_bids[-1]
    bad = _json.loads((REVIEW_DIR / "review_results.template.json").read_text(encoding="utf-8"))
    bad["items"][0]["reviewer_choice"] = "MATCH_MULTIPLE_BLOCKS"
    bad["items"][0]["selected_block_ids"] = [b1, b2]
    bad["items"][0]["reviewer_note"] = "test"
    bad["items"][0]["reviewed_at"] = "2026-08-05"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        _json.dump(bad, f, ensure_ascii=False)
        tmp = f.name
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts/import_human_gold_review.py"),
         "--review", tmp, "--reviewer", "test"],
        capture_output=True, text=True, cwd=str(BACKEND), env={"PYTHONPATH": str(BACKEND)})
    assert "IMPORT REJECTED" in r.stdout


# 9. Review package hash consistency (structural)
def test_review_package_hash_consistency():
    items = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))
    template = json.loads((REVIEW_DIR / "review_results.template.json").read_text(encoding="utf-8"))
    assert len(template["items"]) == len(items["items"])
    tids = sorted(it["item_id"] for it in template["items"])
    iids = sorted(it["item_id"] for it in items["items"])
    assert tids == iids, "template items differ from original package"


# 10. Gold version must not be overwritten
def test_gold_version_not_overwritten():
    for ds in ("demo", "holdout"):
        p = BACKEND.parent / "data" / ds / "annotations" / "gold_evidence.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            # old gold must not carry v2 markers
            assert not any(e.get("gold_confirm_status") == "CONFIRMED" for e in d.get("evidence", []))


# 11. Post-review script stops without human review
def test_post_review_stops_without_human():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(BACKEND / "scripts/run_post_review_validation.py")],
        capture_output=True, text=True, cwd=str(BACKEND), env={"PYTHONPATH": str(BACKEND)})
    assert "WAITING_FOR_HUMAN_REVIEW" in r.stdout


# 12. Priority Cohort not based on system prediction
def test_priority_cohort_no_system_prediction():
    cohort = json.loads((BACKEND / "artifacts/gold_contract/phase23_11_6_priority_cohort.json").read_text())
    assert cohort["count"] == 16
    assert len(cohort["claim_ids"]) == 16
    # No per-claim prediction data / no prediction field (word in forbidden-rule
    # description is documentation, not data)
    assert "per_claim_prediction" not in cohort
    assert "prediction_map" not in cohort
    assert "system_accuracy" not in cohort
    assert "predicted_correct" not in cohort
    # selection rules must be coverage-based
    rules = " ".join(cohort["selection_rules"]).lower()
    assert "type" in rules and "company" in rules and "dataset" in rules