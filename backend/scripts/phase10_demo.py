"""Phase 10 · Demo — 美的集团金融知识图谱（Financial Knowledge Graph Engine）。

任务书 §8 Demo 要求：
- 使用美的集团投资案例
- 展示 Entity Extraction / Fact Graph / Conflict Reasoning

流程：
  Claims + Evidence + Company Facts
    ↓ Entity Extraction
  Entities + Relationships + Facts
    ↓ Conflict Reasoning
  ConflictFindings

设计约束（任务书）：
- 不修改已有 Verification 逻辑；
- Knowledge Graph 作为新增层，与已有模块解耦；
- Evidence First：每个 Fact 必须包含 source/evidence/confidence/timestamp。

运行：
    cd backend
    python -m scripts.phase10_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保可以 import app.*
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.services import document_service as dsvc  # noqa: E402
from app.services.agent.executor import run_audit  # noqa: E402
from app.services.knowledge_graph.conflict_reasoner import (  # noqa: E402
    compute_overall_risk,
    detect_conflicts,
)
from app.services.knowledge_graph.entity_extractor import extract_entities  # noqa: E402
from app.services.knowledge_graph.fact_graph import (  # noqa: E402
    get_business_map,
    get_company_profile,
    get_evidence_sources,
    get_entity_network,
)
from app.services.knowledge_graph.graph_builder import (  # noqa: E402
    build_graph,
    save_graph,
)


# ---------------------------------------------------------------------------
# 1) 注册投资材料并运行审计（生成 Claims / Evidence）
# ---------------------------------------------------------------------------
def _prepare_investment_material() -> tuple[int, int]:
    """注册一份含夸大表达与海外业务描述的投资材料，运行审计返回 (document_id, audit_id)。"""
    material = (
        "# 美的集团投资观点材料\n\n"
        "公司海外业务高速增长，已成为利润增长的核心引擎。\n"
        "公司保持行业领先，空调线上线下市场份额遥遥领先。\n"
        "盈利能力持续提升，归母净利润必将持续高速增长。\n"
        "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"
        "归母净利润439.45亿元，同比增长38.02%。\n"
        "主营业务包括暖通空调、消费电器、机器人与自动化。\n"
        "竞争对手为海尔、格力、海信。\n"
    ).encode("utf-8")
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="midea_kg_demo.md",
            data=material,
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        return doc.id, result["audit_id"]


# ---------------------------------------------------------------------------
# 2) 收集 Claims / Evidence / Company Facts
# ---------------------------------------------------------------------------
def _collect_inputs(session: Session, document_id: int, audit_id: int) -> tuple[list[dict], list[dict], list[dict]]:
    """收集构建知识图谱所需的输入源。"""
    import json

    from app.models.audit import AuditReport
    from app.models.claim import Claim, ExtractionRun
    from app.models.evidence import EvidenceCandidate

    claims: list[dict] = []
    evidence: list[dict] = []
    company_facts: list[dict] = []

    # ---- 1. Claims ----
    audit = session.get(AuditReport, audit_id)
    if audit is not None:
        doc_id = audit.document_id
        run = (
            session.query(ExtractionRun)
            .filter(ExtractionRun.document_id == doc_id)
            .order_by(ExtractionRun.id.desc())
            .first()
        )
        if run is not None:
            rows = (
                session.query(Claim)
                .filter(Claim.extraction_run_id == run.id)
                .all()
            )
            for r in rows:
                claims.append(
                    {
                        "claim_id": r.claim_uid,
                        "claim_uid": r.claim_uid,
                        "original_text": r.source_text,
                        "source_text": r.source_text,
                        "claim_type": r.claim_type,
                        "entity_name": r.entity_name,
                        "stock_code": r.stock_code,
                        "metric": r.metric,
                        "metric_code": r.metric_code,
                        "reported_value": r.reported_value,
                        "value": r.reported_value,
                        "unit": r.unit,
                        "period": r.period,
                    }
                )

    # ---- 2. Evidence ----
    evidence_rows = (
        session.query(EvidenceCandidate)
        .filter(EvidenceCandidate.document_id == document_id)
        .limit(50)
        .all()
    )
    for e in evidence_rows:
        evidence.append(
            {
                "page_number": e.page_number,
                "block_id": e.block_id,
                "text": e.text or "",
                "evidence_type": e.evidence_type,
            }
        )

    # ---- 3. Company Facts（演示用：从文档块抽取作为 Company Facts 兜底）----
    from app.models import DocumentBlock

    blocks = (
        session.query(DocumentBlock)
        .filter(DocumentBlock.document_id == document_id)
        .all()
    )
    for blk in blocks:
        text = (blk.text or "").strip()
        if not text:
            continue
        company_facts.append(
            {
                "fact_id": f"DEMO-CF-{len(company_facts) + 1:04d}",
                "dimension": "FINANCIAL",
                "subject": "美的集团",
                "statement": text[:80],
                "value": None,
                "unit": "",
                "period": "2025FY",
                "source": "FINANCIAL_REPORT",
                "source_label": "美的集团投资材料（兜底）",
                "evidence": text[:200],
                "timestamp": "2026-07-31T00:00:00Z",
                "confidence": 0.85,
            }
        )

    return claims, evidence, company_facts


# ---------------------------------------------------------------------------
# 3) 主入口
# ---------------------------------------------------------------------------
def run_demo() -> dict:
    init_db()
    document_id, audit_id = _prepare_investment_material()

    with SessionLocal() as s:
        claims, evidence, company_facts = _collect_inputs(s, document_id, audit_id)

        # Step 1: Entity Extraction
        entities = extract_entities(claims, evidence, company_facts)

        # Step 2: Build Graph
        graph = build_graph(entities, company_facts, claims, evidence)
        graph = save_graph(s, graph, document_id=document_id)

        # Step 3: Conflict Reasoning
        detection = detect_conflicts(claims, graph)
        overall_score, overall_level = compute_overall_risk(detection.findings)

        # Step 4: Fact Graph 查询
        profile = get_company_profile(graph)
        business_map = get_business_map(graph)
        evidence_sources = get_evidence_sources(graph)
        entity_network = get_entity_network(graph)

        return {
            "document_id": document_id,
            "audit_id": audit_id,
            "entity_count": len(graph.entities),
            "relationship_count": len(graph.relationships),
            "fact_count": len(graph.facts),
            "company_profile": profile.to_dict(),
            "business_map": business_map.to_dict(),
            "evidence_sources": evidence_sources,
            "entity_network": entity_network,
            "conflicts": {
                "findings": [f.to_dict() for f in detection.findings],
                "conflict_count": detection.conflict_count,
                "support_count": detection.support_count,
                "overall_risk_score": overall_score,
                "overall_risk_level": overall_level,
            },
            "graph": graph.to_dict(),
        }


def _print_report(report: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 10 · Financial Knowledge Graph Engine — 美的集团")
    print("=" * 78)
    print(f"Document ID        : {report['document_id']}")
    print(f"Audit ID           : {report['audit_id']}")
    print(f"Entity Count       : {report['entity_count']}")
    print(f"Relationship Count : {report['relationship_count']}")
    print(f"Fact Count         : {report['fact_count']}")

    print("\n--- Entity Network（实体网络）---")
    net = report["entity_network"]
    # 按类型分组
    by_type: dict[str, list[str]] = {}
    for n in net.get("nodes", []):
        by_type.setdefault(n["type"], []).append(n["name"])
    for etype, names in by_type.items():
        print(f"  [{etype}] ({len(names)}): {', '.join(names)}")
    print(f"  Edges: {len(net.get('edges', []))} 条")
    for e in net.get("edges", [])[:8]:
        print(f"    - {e['source']} —{e['label']}→ {e['target']} (置信度 {e['confidence']:.2f})")

    print("\n--- Company Profile（公司画像）---")
    profile = report["company_profile"]
    print(f"  Company      : {profile.get('company', '')}")
    print(f"  Businesses   : {profile.get('businesses', [])}")
    print(f"  Products     : {profile.get('products', [])}")
    print(f"  Regions      : {profile.get('regions', [])}")
    print(f"  Competitors  : {profile.get('competitors', [])}")
    print(f"  Executives   : {profile.get('executives', [])}")

    print("\n--- Business Map（业务图谱）---")
    bmap = report["business_map"]
    for seg in bmap.get("business_segments", [])[:5]:
        print(f"  · {seg.get('business', '')}")
        print(f"      products: {seg.get('products', [])}")
        print(f"      regions : {seg.get('regions', [])}")

    print("\n--- Evidence Sources（证据来源）---")
    for src in report.get("evidence_sources", [])[:5]:
        print(f"  [{src.get('source', '')}] {src.get('source_label', '')} — {src.get('fact_count', 0)} 条事实")

    print("\n--- Conflict Reasoning（冲突推理）---")
    conflicts = report["conflicts"]
    print(f"  Overall Risk: {conflicts['overall_risk_score']}/100 {conflicts['overall_risk_level']}")
    print(f"  冲突 {conflicts['conflict_count']} / 支持 {conflicts['support_count']} / 共 {len(conflicts['findings'])} 条 Claim")
    for f in conflicts.get("findings", [])[:8]:
        print(f"  · [{f['finding_id']}] {f['claim_id']} {f['conflict_type']} | {f['difference']}")
        print(f"      risk: {f['risk_type']} {f['risk_score']} {f['risk_level']}")

    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "document_id": report["document_id"],
        "entity_count": report["entity_count"],
        "relationship_count": report["relationship_count"],
        "fact_count": report["fact_count"],
        "overall_risk_score": conflicts["overall_risk_score"],
        "overall_risk_level": conflicts["overall_risk_level"],
        "conflict_count": conflicts["conflict_count"],
        "support_count": conflicts["support_count"],
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
    print("=" * 78)


if __name__ == "__main__":
    _report = run_demo()
    _print_report(_report)
