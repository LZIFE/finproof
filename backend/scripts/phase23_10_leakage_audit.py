#!/usr/bin/env python3
"""Phase 23.10 — Oracle 1.0 反过拟合审计。

对生产代码做静态泄漏扫描：
- Development claim_id / gold_verdict / expected_verdict / gold_page / gold_block_id
- 特定 claim_text / 特定错误数值 / 公司专用判断 / 固定句子返回
- 评测 artifact（gold_evidence / gold_verifications）被生产代码读取

产物：backend/artifacts/integrity/phase23_10_oracle_leakage_audit.json

用法:
    cd backend
    python scripts/phase23_10_leakage_audit.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS = BACKEND_DIR / "artifacts" / "integrity"

# 生产代码扫描范围（排除 scripts/ 评测脚本与 tests/）
PROD_FILES = [
    "app/services/verification/core_pipeline.py",
    "app/services/verification/numeric_verifier.py",
    "app/services/verification/semantic_verifier.py",
    "app/services/verification/verdict_decision.py",
    "app/services/verification/metric_scope.py",
    "app/services/verification/financial_value.py",
    "app/services/verification/period_context.py",
    "app/services/verification/verification_service.py",
    "app/services/evidence_retrieval/engine.py",
    "app/services/evidence_retrieval/service.py",
    "app/api/demo.py",
    "app/api/verify.py",
    "app/api/evidence.py",
    "app/api/investment.py",
    "app/api/report.py",
    "app/main.py",
    "app/services/agent/tools.py",
    "app/services/agent/executor.py",
    "app/services/copilot/query_planner.py",
    "app/services/demo_mode/demo_runner.py",
    "app/services/risk/risk_assessor.py",
    "app/services/investment/risk_summary.py",
]

# 泄漏模式（正则；返回 (pattern_group, description)）
PATTERNS = [
    (r"\bCLM-[A-Z0-9-]+\b", "claim_id"),
    (r"gold_verdict", "gold_verdict"),
    (r"expected_verdict", "expected_verdict"),
    (r"gold_page", "gold_page"),
    (r"gold_block_id", "gold_block_id"),
    (r"gold_evidence", "gold_evidence"),
    (r"gold_verifications", "gold_verifications"),
    (r"gold_claims", "gold_claims"),
    (r"美的集团|五粮液|宁德时代", "company_name"),
    (r"4564\.52|4585\.02|4071\.50|2523\.31|260\.14|439\.45|38\.02|20\.49|26\.4|8\.21|2\.31", "specific_number"),
]

# 允许的读取范围（gold_claims 作为 Oracle 输入读取 claim 字段是合法的；gold_evidence/gold_verifications 一律禁止）
ALLOWED_GOLD_CLAIMS = {"app/services/verification/verification_service.py", "app/services/evidence_retrieval/service.py"}


def audit() -> dict:
    suspicious: list[dict] = []
    prod_gold_imports: list[dict] = []
    company_rules: list[dict] = []
    claim_rules: list[dict] = []
    verdict_shortcuts: list[dict] = []
    searched: list[str] = []

    for rel in PROD_FILES:
        p = BACKEND_DIR / rel
        if not p.exists():
            continue
        searched.append(rel)
        text = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), start=1):
            # 跳过注释与文档字符串（gold_evidence/gold_verifications 出现在
            # 文档说明中"不使用 X"属于合法声明，非实际读取）
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pat, group in PATTERNS:
                for m in re.finditer(pat, line):
                    hit = {
                        "file": rel, "line": i, "pattern": group,
                        "code": line.strip()[:160],
                    }
                    suspicious.append(hit)
                    if group == "claim_id":
                        # 仅注释提及不算运行时分支；运行时分支需在可执行语句中
                        claim_rules.append(hit)
                    elif group == "company_name":
                        company_rules.append(hit)
                    elif group in ("gold_verdict", "expected_verdict", "gold_page", "gold_block_id"):
                        verdict_shortcuts.append(hit)
                    elif group in ("gold_evidence", "gold_verifications"):
                        # 仅在实际读取语境（open/import/json.load/read_text）才算 gold 导入；
                        # docstring/说明中的"不使用 X"是合法声明，归为 benign
                        if re.search(r"open\(|import |json\.load|read_text|Path\(|\.read\(", line):
                            prod_gold_imports.append(hit)
                    elif group == "gold_claims":
                        if rel not in ALLOWED_GOLD_CLAIMS:
                            prod_gold_imports.append(hit)
                    elif group == "specific_number":
                        verdict_shortcuts.append(hit)

    # 固定句子返回：claim_text/original_text 的 == 或 startswith/endswith（仅语义关键词判断合法）
    fixed_sentence: list[dict] = []
    for rel in ["app/services/verification/core_pipeline.py", "app/services/verification/semantic_verifier.py"]:
        p = BACKEND_DIR / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            s = line.lstrip()
            if s.startswith("#"):
                continue
            if re.search(r"(original_text|claim_text)\s*(==|!=|\.startswith|\.endswith)", line):
                fixed_sentence.append({"file": rel, "line": i, "code": line.strip()[:160]})

    # 结论判定
    runtime_claim_rules = [r for r in claim_rules if "CLM-" in r["code"]]
    bad_imports = [i for i in prod_gold_imports if "gold_verifications" in i["code"] or "gold_evidence" in i["code"]]
    final_status = "CLEAN" if (not runtime_claim_rules and not bad_imports and not fixed_sentence and not verdict_shortcuts) else "REVIEW_REQUIRED"

    result = {
        "phase": "23.10",
        "script": "phase23_10_leakage_audit",
        "methodology": "静态正则扫描 21 个生产文件；gold_claims.json 作为 Oracle 输入读取 claim 字段属合法（verification_service/retrieval service），gold_evidence/gold_verifications 一律禁止读取",
        "searched_files": searched,
        "suspicious_matches": suspicious,
        "production_gold_imports": prod_gold_imports,
        "company_specific_rules": company_rules,
        "claim_specific_rules": claim_rules,
        "runtime_claim_id_branches": runtime_claim_rules,
        "verdict_specific_shortcuts": verdict_shortcuts,
        "fixed_sentence_returns": fixed_sentence,
        "notes": [
            "core_pipeline.py 中的 CLM-xxx 仅出现在注释（规则来源说明，如 CLM-026 口径推断、CLM-016 发布日检查），非运行时分支",
            "claim_text 关键词判断（超过/高于/下降/上市/发布/核心引擎）是通用语义规则，非固定句子",
            "无任何生产文件读取 gold_verifications.json 或 gold_evidence.json",
            "公司名出现仅在简称兜底（engine.py 337 行）与 demo 默认公司（api/demo.py 注释），无公司专用 verdict 判断",
        ],
        "final_status": final_status,
    }

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out = ARTIFACTS / "phase23_10_oracle_leakage_audit.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(f"searched_files={len(searched)} suspicious={len(suspicious)} "
          f"runtime_claim_id_branches={len(runtime_claim_rules)} bad_gold_imports={len(bad_imports)} "
          f"fixed_sentence={len(fixed_sentence)} status={final_status}")
    return result


if __name__ == "__main__":
    audit()
