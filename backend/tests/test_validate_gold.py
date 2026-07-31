"""金标准校验脚本（scripts/validate_gold.py）的单元测试。

运行方式：cd backend && python -m pytest tests/test_validate_gold.py -v
"""

import json
import sys
from pathlib import Path

# 使 backend/tests 可以导入仓库根目录下的 scripts/ 模块
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_gold import (  # noqa: E402
    REQ,
    validate_all,
    validate_claims,
    validate_evidence,
    validate_verifications,
    check_requirements,
    load_json,
)

VALID_CLAIM = {
    "claim_id": "CLM-001",
    "original_text": "测试主张",
    "claim_type": "raw_number",
    "entity": "测试公司",
    "metric": "revenue",
}
VALID_EVIDENCE = {
    "evidence_id": "EVD-001",
    "claim_id": "CLM-001",
    "document_name": "annual_report.pdf",
    "page": 9,
    "evidence_text": "测试证据片段",
    "evidence_type": "financial_table",
    "source_level": "S",
}
VALID_VERIFICATION = {
    "claim_id": "CLM-001",
    "expected_verdict": "SUPPORTED",
    "error_type": None,
    "reported_value": None,
    "correct_value": None,
    "calculation_formula": None,
    "calculation_inputs": [],
    "explanation": "测试说明",
    "review_required": False,
}


def _mk_claims(n: int, refuted: int = 0, insufficient: int = 0) -> list[dict]:
    claims = []
    for i in range(1, n + 1):
        c = dict(VALID_CLAIM, claim_id=f"CLM-{i:03d}")
        if i <= refuted:
            c["claim_type"] = "scope"
        elif i <= refuted + insufficient:
            c["claim_type"] = "business_fact"
        claims.append(c)
    return claims


_REFUTED_ERROR_TYPES = [
    "计算错误",
    "口径错误",
    "时间错误",
    "单位错误",
    "引用错配",
    "因果关系过度推断",
    "预测事实化",
    "证据不足",
]


def _mk_verifications(claims: list[dict], refuted: int = 0, insufficient: int = 0) -> list[dict]:
    vers = []
    for i, c in enumerate(claims, start=1):
        v = dict(VALID_VERIFICATION, claim_id=c["claim_id"])
        if i <= refuted:
            v["expected_verdict"] = "REFUTED"
            # 分配不同的错误类型，保证错误类型数 ≥6 的检查可满足
            v["error_type"] = _REFUTED_ERROR_TYPES[(i - 1) % len(_REFUTED_ERROR_TYPES)]
            v["calculation_formula"] = "a+b"
            v["calculation_inputs"] = [1, 2]
        elif i <= refuted + insufficient:
            v["expected_verdict"] = "INSUFFICIENT_EVIDENCE"
            v["error_type"] = "证据不足"
        vers.append(v)
    return vers


# ---------- 单项校验 ----------

def test_validate_claims_duplicate_id():
    claims = [dict(VALID_CLAIM), dict(VALID_CLAIM)]
    issues = validate_claims(claims)
    assert any("重复" in i for i in issues)


def test_validate_claims_missing_field():
    claim = dict(VALID_CLAIM)
    del claim["metric"]
    assert any("缺失必填字段: metric" in i for i in validate_claims([claim]))


def test_validate_claims_bad_type():
    claim = dict(VALID_CLAIM, claim_type="not_a_type")
    assert any("claim_type 非法" in i for i in validate_claims([claim]))


def test_validate_evidence_missing_claim():
    issues = validate_evidence([dict(VALID_EVIDENCE)], claim_ids={"CLM-999"})
    assert any("引用的 claim_id 不存在" in i for i in issues)


def test_validate_evidence_empty_page():
    ev = dict(VALID_EVIDENCE, page=None)
    assert any("页码为空或非法" in i for i in validate_evidence([ev], {"CLM-001"}))


def test_validate_verifications_missing_claim():
    issues = validate_verifications([dict(VALID_VERIFICATION)], claim_ids={"CLM-999"})
    assert any("引用的 claim_id 不存在" in i for i in issues)


def test_validate_verifications_bad_verdict():
    v = dict(VALID_VERIFICATION, expected_verdict="WRONG")
    assert any("expected_verdict 非法" in i for i in validate_verifications([v], {"CLM-001"}))


# ---------- 数量与类别要求 ----------

def test_check_requirements_pass():
    claims = _mk_claims(20, refuted=8, insufficient=3)
    vers = _mk_verifications(claims, refuted=8, insufficient=3)
    assert check_requirements(claims, vers) == []


def test_check_requirements_too_few_claims():
    claims = _mk_claims(5, refuted=1, insufficient=1)
    vers = _mk_verifications(claims, refuted=1, insufficient=1)
    issues = check_requirements(claims, vers)
    assert any("总主张数量" in i for i in issues)
    assert any("正确主张" in i for i in issues)


# ---------- 文件级校验（对真实金标准） ----------

def test_real_gold_standard_passes():
    data_dir = REPO_ROOT / "data" / "demo" / "annotations"
    errors, summary = validate_all(data_dir)
    assert errors == [], f"真实金标准校验应通过，但发现: {errors[:5]}"
    assert "claims=26" in summary[0]


def test_invalid_json_detected(tmp_path):
    bad = tmp_path / "gold_claims.json"
    bad.write_text("{not valid json", encoding="utf-8")
    (tmp_path / "gold_evidence.json").write_text("{}", encoding="utf-8")
    (tmp_path / "gold_verifications.json").write_text("{}", encoding="utf-8")
    errors, _ = validate_all(tmp_path)
    assert any("JSON 解析失败" in e for e in errors)


def test_load_json_missing_file(tmp_path):
    data, errors = load_json(tmp_path / "nope.json")
    assert data is None
    assert any("文件缺失" in e for e in errors)


def test_json_roundtrip_of_real_files():
    """真实金标准文件可被 json 解析且关键字段齐备（防御性回归）。"""
    data_dir = REPO_ROOT / "data" / "demo" / "annotations"
    for name in ("gold_claims.json", "gold_evidence.json", "gold_verifications.json"):
        data, errors = load_json(data_dir / name)
        assert errors == [], errors
        assert data is not None
