#!/usr/bin/env python3
"""金标准数据完整性校验脚本（数据质量工具，非业务核验逻辑）。

只负责检查 data/demo/annotations/ 下金标准文件的完整性：
- JSON 格式是否合法
- claim_id 是否唯一
- evidence / verification 引用的 claim_id 是否存在
- 枚举值是否合法（expected_verdict / claim_type / source_level）
- 页码是否为空（evidence.page 必须为正整数）
- 必填字段是否缺失
- 是否达到数量与类别要求（主张总数 / 正确 / 错误 / 证据不足 / 错误类型数 /
  确定性计算 / 单季与累计口径 / 非数字语义证据）

用法：python scripts/validate_gold.py [--data-dir data/demo/annotations]
退出码：0 = 全部通过；1 = 存在错误；2 = 文件缺失或 JSON 解析失败
"""

import argparse
import json
import sys
from pathlib import Path

CLAIM_REQUIRED = ["claim_id", "original_text", "claim_type", "entity", "metric"]
EVIDENCE_REQUIRED = ["evidence_id", "claim_id", "document_name", "evidence_text", "evidence_type", "source_level"]
VERIFICATION_REQUIRED = ["claim_id", "expected_verdict", "explanation"]

VERDICTS = {
    "SUPPORTED",
    "REFUTED",
    "PARTIALLY_SUPPORTED",
    "INSUFFICIENT_EVIDENCE",
    "UNABLE_TO_DETERMINE",
    "OPINION_OR_FORECAST",
}
CLAIM_TYPES = {
    "raw_number",
    "calculated_financial_metric",
    "scope",
    "business_fact",
    "causality",
    "forecast",
    "comparison",
}
SOURCE_LEVELS = {"S", "A", "B", "C", "D"}

# 数量与类别要求（对齐 mvp_scope.md 金标准质量要求）
REQ = {
    "min_claims": 20,
    "min_supported": 5,
    "min_refuted": 8,
    "min_insufficient_or_unable": 3,
    "min_error_types": 6,
    "min_calc_claims": 5,          # 带 calculation_formula 的核验
    "min_quarter_cumulative": 3,   # 涉及单季度与累计口径
    "min_semantic_claims": 3,      # 非数字语义证据（business_fact/causality/forecast/comparison）
}

SEMANTIC_TYPES = {"business_fact", "causality", "forecast", "comparison"}


def load_json(path: Path) -> tuple[dict | None, list[str]]:
    """读取 JSON；返回 (数据, 问题列表)。解析失败时数据为 None。"""
    if not path.exists():
        return None, [f"文件缺失: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"JSON 解析失败 {path.name}: {exc}"]
    return data, []


def validate_claims(claims: list[dict]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for c in claims:
        cid = c.get("claim_id")
        if cid in seen:
            issues.append(f"claim_id 重复: {cid}")
        seen.add(cid)
        for field in CLAIM_REQUIRED:
            if field not in c or c[field] in (None, ""):
                issues.append(f"{cid or '(unknown)'} 缺失必填字段: {field}")
        if c.get("claim_type") not in CLAIM_TYPES:
            issues.append(f"{cid} claim_type 非法: {c.get('claim_type')}")
    return issues


def validate_evidence(evidence: list[dict], claim_ids: set[str]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for e in evidence:
        eid = e.get("evidence_id")
        if eid in seen:
            issues.append(f"evidence_id 重复: {eid}")
        seen.add(eid)
        for field in EVIDENCE_REQUIRED:
            if field not in e or e[field] in (None, ""):
                issues.append(f"{eid or '(unknown)'} 缺失必填字段: {field}")
        if e.get("claim_id") not in claim_ids:
            issues.append(f"证据 {eid} 引用的 claim_id 不存在: {e.get('claim_id')}")
        page = e.get("page")
        if not isinstance(page, int) or page < 1:
            issues.append(f"证据 {eid} 页码为空或非法: {page!r}")
        if e.get("source_level") not in SOURCE_LEVELS:
            issues.append(f"证据 {eid} source_level 非法: {e.get('source_level')}")
    return issues


def validate_verifications(verifications: list[dict], claim_ids: set[str]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for v in verifications:
        cid = v.get("claim_id")
        if cid in seen:
            issues.append(f"verification claim_id 重复: {cid}")
        seen.add(cid)
        for field in VERIFICATION_REQUIRED:
            if field not in v or v[field] in (None, ""):
                issues.append(f"{cid or '(unknown)'} 缺失必填字段: {field}")
        if cid not in claim_ids:
            issues.append(f"核验 {cid} 引用的 claim_id 不存在")
        if v.get("expected_verdict") not in VERDICTS:
            issues.append(f"{cid} expected_verdict 非法: {v.get('expected_verdict')}")
    return issues


def check_requirements(claims: list[dict], verifications: list[dict]) -> list[str]:
    issues: list[str] = []
    verdicts = [v.get("expected_verdict") for v in verifications]
    n_supported = verdicts.count("SUPPORTED")
    n_refuted = verdicts.count("REFUTED")
    n_insufficient = verdicts.count("INSUFFICIENT_EVIDENCE")
    n_unable = verdicts.count("UNABLE_TO_DETERMINE")
    error_types = {v.get("error_type") for v in verifications if v.get("error_type")}
    n_calc = sum(1 for v in verifications if v.get("calculation_formula"))
    n_quarter = sum(
        1
        for c in claims
        if c.get("claim_type") == "scope"
        or (c.get("metric") or "").startswith("quarterly_")
    )
    n_semantic = sum(1 for c in claims if c.get("claim_type") in SEMANTIC_TYPES)

    checks = [
        ("总主张数量", len(claims), REQ["min_claims"]),
        ("正确主张(SUPPORTED)", n_supported, REQ["min_supported"]),
        ("错误主张(REFUTED)", n_refuted, REQ["min_refuted"]),
        ("证据不足或无法判断", n_insufficient + n_unable, REQ["min_insufficient_or_unable"]),
        ("错误类型数", len(error_types), REQ["min_error_types"]),
        ("确定性计算主张(带公式)", n_calc, REQ["min_calc_claims"]),
        ("单季度与累计口径主张", n_quarter, REQ["min_quarter_cumulative"]),
        ("非数字语义证据主张", n_semantic, REQ["min_semantic_claims"]),
    ]
    for name, actual, minimum in checks:
        if actual < minimum:
            issues.append(f"数量要求未达标: {name} = {actual}（要求 ≥{minimum}）")
    return issues


def validate_all(data_dir: Path) -> tuple[list[str], list[str]]:
    """返回 (错误列表, 汇总行)。"""
    claims_data, errs = load_json(data_dir / "gold_claims.json")
    ev_data, errs2 = load_json(data_dir / "gold_evidence.json")
    ver_data, errs3 = load_json(data_dir / "gold_verifications.json")
    errors = errs + errs2 + errs3
    if any(e.startswith("JSON 解析失败") or e.startswith("文件缺失") for e in errors):
        return errors, []

    claims = claims_data.get("claims", [])
    evidence = ev_data.get("evidence", [])
    verifications = ver_data.get("verifications", [])
    claim_ids = {c.get("claim_id") for c in claims}

    errors += validate_claims(claims)
    errors += validate_evidence(evidence, claim_ids)
    errors += validate_verifications(verifications, claim_ids)
    errors += check_requirements(claims, verifications)

    summary = (
        f"claims={len(claims)} evidence={len(evidence)} verifications={len(verifications)} "
        f"errors={len(errors)}"
    )
    return errors, [summary]


def main() -> int:
    ap = argparse.ArgumentParser(description="金标准数据完整性校验")
    ap.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / "data" / "demo" / "annotations"))
    args = ap.parse_args()

    errors, summary = validate_all(Path(args.data_dir))
    for line in summary:
        print(line)
    if errors:
        for e in errors:
            print(f"[错误] {e}")
        print(f"共 {len(errors)} 项问题，校验失败。")
        return 1
    print("金标准校验通过：无错误。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
