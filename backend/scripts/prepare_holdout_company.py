#!/usr/bin/env python3
"""Phase 23.8 — Blind Holdout 数据接入工具。

输入：
- company_name
- stock_code
- PDF 路径
- audit_report 文本路径

自动完成：
1. 复制 PDF 到标准目录 data/blind_holdout/{stock_code}/source/
2. 计算 SHA256
3. 创建 company manifest
4. 解析 PDF（document/page/block）
5. 建立真实 Evidence 索引
6. 真实执行 Claim Extraction（禁止读取 gold_claims）
7. 导出待人工标注模板（claims_to_review / evidence_to_review / verdicts_to_review）

模板字段含 human_gold_* 字段，默认为空。
**禁止 Agent 自动把自身预测写入 human_gold_verdict。**

生成：
- data/blind_holdout/{stock_code}/manifest.json
- data/blind_holdout/{stock_code}/source/{filename}
- data/blind_holdout/{stock_code}/annotations/claims_to_review.json
- data/blind_holdout/{stock_code}/annotations/evidence_to_review.json
- data/blind_holdout/{stock_code}/annotations/verdicts_to_review.json

用法:
    python scripts/prepare_holdout_company.py \\
        --company-name "贵州茅台" \\
        --stock-code 600519 \\
        --pdf-path /path/to/annual_report.pdf \\
        --report-path /path/to/audit_report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
BLIND_DIR = DATA_DIR / "blind_holdout"


def _ensure_app_on_path() -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def sha256_file(path: Path) -> str:
    if not path.exists():
        return "NOT_FOUND"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_layout(stock_code: str) -> dict:
    """创建标准目录结构。"""
    base = BLIND_DIR / stock_code
    layout = {
        "root": base,
        "source": base / "source",
        "annotations": base / "annotations",
    }
    for p in layout.values():
        if isinstance(p, Path):
            p.mkdir(parents=True, exist_ok=True)
    return layout


def copy_pdf(pdf_path: Path, stock_code: str) -> Path:
    """复制 PDF 到标准目录。"""
    dest = BLIND_DIR / stock_code / "source" / pdf_path.name
    shutil.copy2(pdf_path, dest)
    return dest


def create_manifest(company_name: str, stock_code: str, pdf_path: Path,
                    report_path: Path, pdf_dest: Path) -> dict:
    """创建 company manifest。"""
    manifest = {
        "company_name": company_name,
        "stock_code": stock_code,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "source_pdf": {
            "filename": pdf_dest.name,
            "path": str(pdf_dest.relative_to(DATA_DIR.parent)),
            "sha256": sha256_file(pdf_dest),
            "size_bytes": pdf_dest.stat().st_size,
        },
        "audit_report": {
            "path": str(report_path) if report_path else "",
            "sha256": sha256_text(report_path.read_text(encoding="utf-8", errors="ignore")) if report_path and report_path.exists() else "",
        },
        "status": "prepared",
        "next_steps": [
            "parse_pdf → document/page/block",
            "build_evidence_index",
            "extract_claims（真实 Claim Extraction，禁止读 gold_claims）",
            "export_review_templates",
            "human_annotation: 填充 human_gold_evidence / human_gold_verdict",
        ],
    }
    manifest_path = BLIND_DIR / stock_code / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_pdf_and_build_index(pdf_dest: Path, stock_code: str, session) -> dict:
    """解析 PDF → document/page/block → 建立真实 Evidence 索引。"""
    _ensure_app_on_path()
    from app.services import document_service

    with open(pdf_dest, "rb") as f:
        data = f.read()
    doc, blocks = document_service.register_document(
        session, filename=pdf_dest.name, data=data,
        document_role="SOURCE_DOCUMENT", company_name=stock_code,
        stock_code=stock_code, report_period="2025FY",
    )
    return {
        "document_id": doc.id,
        "company_name": doc.company_name,
        "report_period": doc.report_period,
        "page_count": getattr(doc, "page_count", None),
        "block_count": len(blocks) if blocks else 0,
    }


def extract_claims_real(report_text: str, stock_code: str) -> list[dict]:
    """真实执行 Claim Extraction。

    **禁止读取 gold_claims 作为抽取结果。** 仅从 audit_report 文本抽取。
    """
    _ensure_app_on_path()
    try:
        from app.services.claims.extractor import extract_claims_from_text
        claims = extract_claims_from_text(report_text, company=stock_code)
    except Exception as e:
        # fallback：粗略按句切分
        claims = []
        for idx, sent in enumerate(report_text.split("。")[:30]):
            if not sent.strip():
                continue
            claims.append({
                "claim_id": f"BC-{stock_code}-{idx+1:03d}",
                "claim_text": sent.strip(),
                "claim_type": "raw_number",
                "extraction_confidence": 0.3,
            })
    return claims


def export_review_templates(stock_code: str, claims: list[dict],
                            parsed_index: dict) -> dict:
    """导出待人工标注模板。"""
    annotations_dir = BLIND_DIR / stock_code / "annotations"

    # claims_to_review.json：含 human_gold_* 字段默认空
    claims_template = []
    for c in claims:
        claims_template.append({
            "claim_id": c.get("claim_id"),
            "claim_text": c.get("claim_text") or c.get("original_text", ""),
            "claim_type": c.get("claim_type", ""),
            "metric": c.get("metric", ""),
            "value": c.get("value"),
            "unit": c.get("unit", ""),
            "period": c.get("period", ""),
            "scope": c.get("scope", ""),
            "suggested_document_id": parsed_index.get("document_id"),
            "suggested_page": None,
            "suggested_block_id": "",
            "suggested_evidence_text": "",
            "human_gold_evidence": "",
            "human_gold_verdict": "",
            "human_rationale": "",
            "review_status": "pending",
        })

    # evidence_to_review.json：每个 claim 对应的候选 evidence（待人工确认）
    evidence_template = []
    for c in claims_template:
        evidence_template.append({
            "claim_id": c["claim_id"],
            "suggested_document_id": c["suggested_document_id"],
            "suggested_page": c["suggested_page"],
            "suggested_block_id": c["suggested_block_id"],
            "suggested_evidence_text": c["suggested_evidence_text"],
            "human_gold_evidence": "",
            "human_gold_document_id": "",
            "human_gold_page": None,
            "human_gold_block_id": "",
            "review_status": "pending",
        })

    # verdicts_to_review.json：每个 claim 的待人工确认 verdict
    verdicts_template = []
    for c in claims_template:
        verdicts_template.append({
            "claim_id": c["claim_id"],
            "claim_text": c["claim_text"],
            "claim_type": c["claim_type"],
            "human_gold_verdict": "",
            "human_rationale": "",
            "review_status": "pending",
        })

    paths = {
        "claims": annotations_dir / "claims_to_review.json",
        "evidence": annotations_dir / "evidence_to_review.json",
        "verdicts": annotations_dir / "verdicts_to_review.json",
    }
    paths["claims"].write_text(json.dumps(claims_template, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["evidence"].write_text(json.dumps(evidence_template, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["verdicts"].write_text(json.dumps(verdicts_template, ensure_ascii=False, indent=2), encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


def prepare_holdout_company(company_name: str, stock_code: str,
                            pdf_path: str, report_path: str) -> dict:
    """主接入流程。"""
    _ensure_app_on_path()
    from app.db import SessionLocal

    pdf = Path(pdf_path).resolve()
    report = Path(report_path).resolve() if report_path else None

    if not pdf.exists():
        return {"status": "ERROR", "reason": f"PDF not found: {pdf}"}

    # 1. 创建目录结构
    layout = ensure_layout(stock_code)

    # 2. 复制 PDF
    pdf_dest = copy_pdf(pdf, stock_code)

    # 3. 创建 manifest
    manifest = create_manifest(company_name, stock_code, pdf, report, pdf_dest)

    # 4-5. 解析 PDF + 建索引
    session = SessionLocal()
    parsed_index = {}
    try:
        parsed_index = parse_pdf_and_build_index(pdf_dest, stock_code, session)
    except Exception as e:
        parsed_index = {"error": str(e)[:200]}
    session.close()

    # 6. 真实 Claim Extraction
    claims = []
    if report and report.exists():
        report_text = report.read_text(encoding="utf-8", errors="ignore")
        claims = extract_claims_real(report_text, stock_code)
    else:
        # 无 audit_report，导出空模板待人工填入
        claims = []

    # 7. 导出待人工标注模板
    template_paths = export_review_templates(stock_code, claims, parsed_index)

    return {
        "status": "prepared",
        "company_name": company_name,
        "stock_code": stock_code,
        "manifest_path": str(layout["root"] / "manifest.json"),
        "manifest": manifest,
        "parsed_index": parsed_index,
        "extracted_claim_count": len(claims),
        "template_paths": template_paths,
        "note": "human_gold_* 字段默认为空，需人工填充；Agent 不得自动写入 human_gold_verdict",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 23.8 Blind Holdout 数据接入工具")
    parser.add_argument("--company-name", required=True, help="公司名称")
    parser.add_argument("--stock-code", required=True, help="股票代码（如 600519）")
    parser.add_argument("--pdf-path", required=True, help="财报 PDF 路径")
    parser.add_argument("--report-path", help="待审计 AI 报告文本路径（可选）")
    args = parser.parse_args()

    result = prepare_holdout_company(
        args.company_name, args.stock_code, args.pdf_path, args.report_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
