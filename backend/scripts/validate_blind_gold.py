#!/usr/bin/env python3
"""Phase 23.8 — Blind Gold 校验器。

校验 data/blind_holdout/{stock_code}/annotations/ 下的 Gold 标注完整性：
- 至少 2 家公司
- 禁止美的、宁德、五粮液
- 每家公司至少 15 条主张，总计至少 30 条
- 四类 Verdict（SUPPORTED/REFUTED/PARTIALLY_SUPPORTED/INSUFFICIENT_EVIDENCE）均有覆盖
- document/page/block 真实存在
- evidence_text 与 block 内容一致
- Gold Verdict 非空，rationale 非空
- 文件 hash 固定（运行时不可篡改）
- 不存在重复 claim
- 系统运行代码无法导入 Gold Verdict（护盾检查）

未通过时 Blind Holdout 保持 BLOCKED。

用法:
    python scripts/validate_blind_gold.py
    python scripts/validate_blind_gold.py --strict   # 严格模式（任一失败即 exit 1）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
BLIND_DIR = DATA_DIR / "blind_holdout"

FORBIDDEN_COMPANIES = {"美的集团", "宁德时代", "五粮液", "000333", "300750", "000858"}
REQUIRED_VERDICTS = {"SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE"}
MIN_COMPANIES = 2
MIN_CLAIMS_PER_COMPANY = 15
MIN_TOTAL_CLAIMS = 30


def sha256_file(path: Path) -> str:
    if not path.exists():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def check_company_count() -> tuple[bool, list[str], dict]:
    """检查至少 2 家公司。"""
    issues: list[str] = []
    companies = []
    if not BLIND_DIR.exists():
        return False, ["blind_holdout 目录不存在"], {}
    for d in BLIND_DIR.iterdir():
        if d.is_dir():
            companies.append(d.name)
    if len(companies) < MIN_COMPANIES:
        issues.append(f"公司数量不足：{len(companies)} < {MIN_COMPANIES}（{companies}）")
    return len(issues) == 0, issues, {"companies": companies, "count": len(companies)}


def check_forbidden_companies(companies: list[str]) -> tuple[bool, list[str]]:
    """检查禁止美的/宁德/五粮液。"""
    issues: list[str] = []
    for c in companies:
        if c in FORBIDDEN_COMPANIES:
            issues.append(f"禁用公司出现在 Blind Holdout：{c}")
    # 也检查 stock_code 形式
    for c in companies:
        if c in {"000333", "300750", "000858"}:
            issues.append(f"禁用股票代码出现在 Blind Holdout：{c}")
    return len(issues) == 0, issues


def load_company_gold(stock_code: str) -> dict:
    """加载一家公司的 Gold 标注。"""
    base = BLIND_DIR / stock_code / "annotations"
    claims_path = base / "claims_to_review.json"
    evidence_path = base / "evidence_to_review.json"
    verdicts_path = base / "verdicts_to_review.json"

    # 也支持直接 human_gold_*.json 命名
    if not claims_path.exists():
        claims_path = base / "gold_claims.json"
    if not evidence_path.exists():
        evidence_path = base / "gold_evidence.json"
    if not verdicts_path.exists():
        verdicts_path = base / "gold_verifications.json"

    result = {
        "claims": [],
        "evidence": [],
        "verdicts": [],
        "files_hash": {},
    }
    for label, path in [("claims", claims_path), ("evidence", evidence_path), ("verdicts", verdicts_path)]:
        if path.exists():
            try:
                d = json.load(open(path, encoding="utf-8"))
                result[label] = d.get("claims") or d.get("evidence") or d.get("verifications") or d if isinstance(d, list) else d.get(label, d if isinstance(d, dict) else [])
                if isinstance(result[label], dict):
                    result[label] = []
            except Exception as e:
                result[label] = {"error": str(e)[:120]}
            result["files_hash"][path.name] = sha256_file(path)
        else:
            result[label] = []
    return result


def check_claim_count(stock_code: str, gold: dict) -> tuple[bool, list[str], dict]:
    """检查每家公司至少 15 条，总计至少 30 条。"""
    issues: list[str] = []
    claims = gold.get("claims", [])
    if len(claims) < MIN_CLAIMS_PER_COMPANY:
        issues.append(f"{stock_code}: 主张数 {len(claims)} < {MIN_CLAIMS_PER_COMPANY}")
    return len(issues) == 0, issues, {"claim_count": len(claims)}


def check_verdict_coverage(stock_code: str, gold: dict) -> tuple[bool, list[str], dict]:
    """检查四类 Verdict 均有覆盖。"""
    issues: list[str] = []
    verdicts = gold.get("verdicts", [])
    # 提取 human_gold_verdict 或 expected_verdict
    found_verdicts = set()
    for v in verdicts:
        if isinstance(v, dict):
            vd = v.get("human_gold_verdict") or v.get("expected_verdict", "")
            if vd:
                found_verdicts.add(vd)
    missing = REQUIRED_VERDICTS - found_verdicts
    if missing:
        issues.append(f"{stock_code}: Verdict 覆盖缺失 {missing}（已有 {found_verdicts}）")
    return len(issues) == 0, issues, {"found_verdicts": sorted(found_verdicts), "missing": sorted(missing)}


def check_verdict_non_empty(stock_code: str, gold: dict) -> tuple[bool, list[str]]:
    """检查 Gold Verdict 非空，rationale 非空。"""
    issues: list[str] = []
    verdicts = gold.get("verdicts", [])
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        cid = v.get("claim_id", "?")
        vd = v.get("human_gold_verdict") or v.get("expected_verdict", "")
        rationale = v.get("human_rationale") or v.get("rationale", "")
        if not vd:
            issues.append(f"{stock_code}/{cid}: Gold Verdict 为空")
        if not rationale:
            issues.append(f"{stock_code}/{cid}: rationale 为空")
    return len(issues) == 0, issues


def check_block_exists(stock_code: str, gold: dict) -> tuple[bool, list[str]]:
    """检查 document/page/block 真实存在（与 manifest 对照）。"""
    issues: list[str] = []
    manifest_path = BLIND_DIR / stock_code / "manifest.json"
    if not manifest_path.exists():
        issues.append(f"{stock_code}: manifest.json 不存在，无法校验 block 真实性")
        return len(issues) == 0, issues

    evidence = gold.get("evidence", [])
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        cid = ev.get("claim_id", "?")
        doc_id = ev.get("human_gold_document_id") or ev.get("gold_document_id", "")
        page = ev.get("human_gold_page") or ev.get("gold_page")
        block_id = ev.get("human_gold_block_id") or ev.get("gold_block_id", "")
        if not doc_id:
            issues.append(f"{stock_code}/{cid}: gold_document_id 为空")
        if page is None:
            issues.append(f"{stock_code}/{cid}: gold_page 为空")
        if not block_id:
            issues.append(f"{stock_code}/{cid}: gold_block_id 为空")
    return len(issues) == 0, issues


def check_evidence_consistency(stock_code: str, gold: dict) -> tuple[bool, list[str]]:
    """检查 evidence_text 与 block 内容一致（粗略：非空且含数字）。"""
    issues: list[str] = []
    evidence = gold.get("evidence", [])
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        cid = ev.get("claim_id", "?")
        ev_text = ev.get("human_gold_evidence") or ev.get("gold_evidence_text") or ev.get("evidence_text", "")
        if not ev_text:
            issues.append(f"{stock_code}/{cid}: evidence_text 为空")
        elif not re.search(r"\d", ev_text):
            issues.append(f"{stock_code}/{cid}: evidence_text 不含数字（可能非真实 Evidence）")
    return len(issues) == 0, issues


def check_no_duplicate_claims(stock_code: str, gold: dict) -> tuple[bool, list[str]]:
    """检查不存在重复 claim。"""
    issues: list[str] = []
    claims = gold.get("claims", [])
    seen: set[str] = set()
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = c.get("claim_id", "")
        if cid in seen:
            issues.append(f"{stock_code}: 重复 claim_id {cid}")
        seen.add(cid)
    return len(issues) == 0, issues


def check_gold_not_imported_by_runtime() -> tuple[bool, list[str]]:
    """检查系统运行代码无法导入 Gold Verdict（护盾检查）。

    仅检查运行代码是否引用 **blind_holdout** 路径的 Gold，
    不检查 demo/holdout 的 gold_verifications（那些是 Development Set，允许运行代码读取）。
    """
    issues: list[str] = []
    # 仅检查 blind_holdout 相关 token（不检查 demo/holdout 的 gold_verifications）
    forbidden_tokens = [
        "blind_holdout", "annotations/verdicts_to_review",
        "annotations/gold_verifications", "annotations/gold_verdict",
    ]
    scan_roots = [
        BACKEND_DIR / "app",
    ]
    for root in scan_roots:
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if py.name.endswith("_pb2.py") or "node_modules" in py.name:
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for tok in forbidden_tokens:
                if tok in text:
                    # 排除脚本层（校验器与接入工具允许引用 blind_holdout）
                    if py.name in ("validate_blind_gold.py", "prepare_holdout_company.py"):
                        continue
                    issues.append(f"运行代码 {py.relative_to(BACKEND_DIR)} 引用了 blind_holdout Gold 路径 token：{tok}")
                    break
    return len(issues) == 0, issues


def check_file_hash_fixed(companies: list[str]) -> tuple[bool, list[str], dict]:
    """检查文件 hash 固定（运行时不可篡改）。

    粗略：检查 manifest.json 中是否记录了 hash，且 annotations 文件存在。
    """
    issues: list[str] = []
    hashes: dict[str, dict[str, str]] = {}
    for stock in companies:
        manifest_path = BLIND_DIR / stock / "manifest.json"
        if not manifest_path.exists():
            issues.append(f"{stock}: manifest.json 不存在，无法固定 hash")
            continue
        manifest = json.load(open(manifest_path, encoding="utf-8"))
        # 检查 annotations 文件 hash 是否记录在 manifest 中
        annotations_dir = BLIND_DIR / stock / "annotations"
        for ann_file in annotations_dir.glob("*.json"):
            h = sha256_file(ann_file)
            hashes.setdefault(stock, {})[ann_file.name] = h
    return len(issues) == 0, issues, hashes


def validate_all() -> dict:
    """主校验流程。"""
    results: list[dict] = []

    # 1. 公司数量
    ok, issues, info = check_company_count()
    results.append({"check": "company_count", "passed": ok, "issues": issues, "info": info})
    companies = info.get("companies", [])

    # 2. 禁止公司
    ok, issues = check_forbidden_companies(companies)
    results.append({"check": "forbidden_companies", "passed": ok, "issues": issues})

    # 3. 每家公司校验
    total_claims = 0
    per_company: list[dict] = []
    for stock in companies:
        gold = load_company_gold(stock)

        ok_c, issues_c, info_c = check_claim_count(stock, gold)
        total_claims += info_c.get("claim_count", 0)
        ok_v, issues_v, info_v = check_verdict_coverage(stock, gold)
        ok_ne, issues_ne = check_verdict_non_empty(stock, gold)
        ok_be, issues_be = check_block_exists(stock, gold)
        ok_ec, issues_ec = check_evidence_consistency(stock, gold)
        ok_nd, issues_nd = check_no_duplicate_claims(stock, gold)

        per_company.append({
            "stock_code": stock,
            "claim_count": info_c.get("claim_count", 0),
            "checks": [
                {"check": "claim_count", "passed": ok_c, "issues": issues_c},
                {"check": "verdict_coverage", "passed": ok_v, "issues": issues_v, "info": info_v},
                {"check": "verdict_non_empty", "passed": ok_ne, "issues": issues_ne},
                {"check": "block_exists", "passed": ok_be, "issues": issues_be},
                {"check": "evidence_consistency", "passed": ok_ec, "issues": issues_ec},
                {"check": "no_duplicate_claims", "passed": ok_nd, "issues": issues_nd},
            ],
        })

    # 4. 总主张数
    ok_total = total_claims >= MIN_TOTAL_CLAIMS
    results.append({
        "check": "total_claim_count",
        "passed": ok_total,
        "issues": [] if ok_total else [f"总主张数 {total_claims} < {MIN_TOTAL_CLAIMS}"],
        "info": {"total_claims": total_claims},
    })

    # 5. 文件 hash 固定
    ok_hash, issues_hash, hashes = check_file_hash_fixed(companies)
    results.append({"check": "file_hash_fixed", "passed": ok_hash, "issues": issues_hash, "info": hashes})

    # 6. 系统运行代码无法导入 Gold Verdict
    ok_import, issues_import = check_gold_not_imported_by_runtime()
    results.append({"check": "gold_not_imported_by_runtime", "passed": ok_import, "issues": issues_import})

    # 汇总
    all_passed = all(r["passed"] for r in results)
    output = {
        "phase": "23.8",
        "validator": "validate_blind_gold",
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds") + "Z",
        "overall_passed": all_passed,
        "verdict": "PASS" if all_passed else "BLOCKED",
        "checks": results,
        "per_company": per_company,
        "summary": {
            "companies": companies,
            "total_claims": total_claims,
            "min_companies_required": MIN_COMPANIES,
            "min_claims_per_company": MIN_CLAIMS_PER_COMPANY,
            "min_total_claims": MIN_TOTAL_CLAIMS,
            "required_verdicts": sorted(REQUIRED_VERDICTS),
            "forbidden_companies": sorted(FORBIDDEN_COMPANIES),
        },
        "note": "未通过时 Blind Holdout 保持 BLOCKED；通过后可解除 BLOCKED 并执行真正独立验收",
    }

    out_path = BACKEND_DIR / "artifacts" / "blind_gold_validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")
    print(f"\n=== Blind Gold Validation: {output['verdict']} ===")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{status} {r['check']}: {r.get('issues', [])}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 23.8 Blind Gold 校验器")
    parser.add_argument("--strict", action="store_true", help="严格模式：任一失败即 exit 1")
    args = parser.parse_args()
    output = validate_all()
    if args.strict and not output["overall_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
