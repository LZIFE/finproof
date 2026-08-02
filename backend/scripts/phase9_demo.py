"""Phase 9 · Demo — 美的集团投资委员会审核（Multi-Agent System）。

任务书 §8 Demo 要求：
- 使用美的集团投资案例
- 展示三个 Agent 发现：
  Research: 海外业务增长
  Risk:     缺少利润贡献证明
  Compliance: 存在夸大表达

流程（任务书 §7）：Supervisor → Research → Risk → Compliance → Final Report

设计约束（任务书）：
- 不输出投资建议；
- 不自动决定买卖；
- 保持 Human-in-the-loop；
- 不修改已有核心模块。

运行：
    cd backend
    python -m scripts.phase9_demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保可以 import app.*
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services import document_service as dsvc  # noqa: E402
from app.services.agent.executor import run_audit  # noqa: E402
from app.services.investment_committee.supervisor_agent import (  # noqa: E402
    run_committee,
    save_report,
)


# ---------------------------------------------------------------------------
# 1) 注册投资材料（REPORT_TO_VERIFY）并运行审计（生成 audit_id）
# ---------------------------------------------------------------------------
def _prepare_investment_material() -> tuple[int, int]:
    """注册一份含夸大表达与海外业务描述的投资材料，运行审计返回 (document_id, audit_id)。

    投资材料中预埋：
    - 海外业务增长描述（Research Agent 应识别）
    - 缺少利润贡献证明（Risk Agent 应通过 Intelligence 冲突识别）
    - 夸大表达关键词（Compliance Agent 应识别 OVERSTATEMENT）
    """
    material = (
        "# 美的集团投资观点材料\n\n"
        "公司海外业务高速增长，已成为利润增长的核心引擎。\n"
        "公司保持行业领先，空调线上线下市场份额遥遥领先。\n"
        "盈利能力持续提升，归母净利润必将持续高速增长。\n"
        "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"
        "归母净利润439.45亿元，同比增长38.02%。\n"
    ).encode("utf-8")
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s,
            filename="midea_investment_view.md",
            data=material,
            document_role="REPORT_TO_VERIFY",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        result = run_audit(s, doc.id, mode="mock")
        return doc.id, result["audit_id"]


# ---------------------------------------------------------------------------
# 2) 主入口
# ---------------------------------------------------------------------------
def run_demo() -> dict:
    init_db()
    document_id, audit_id = _prepare_investment_material()
    with SessionLocal() as s:
        report = run_committee(
            s,
            document_id=document_id,
            audit_id=audit_id,
            intelligence_report_id=None,
        )
        report = save_report(s, report)
        return report.to_dict()


def _print_report(report: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 9 · Investment Committee Multi-Agent — 美的集团")
    print("=" * 78)
    print(f"Company            : {report['company']}（{report['stock_code']}）")
    print(f"Report Period      : {report['report_period']}")
    print(f"Overall Risk       : {report['overall_risk_score']}/100 {report['overall_risk_level']}")
    print(f"Compliance Score   : {report['executive_summary']['overall_compliance_score']}/100")

    print("\n--- Agent 执行流程（Supervisor ↓ Research ↓ Risk ↓ Compliance） ---")
    for f in report.get("agent_flow", []):
        print(f"  [{f['agent']}] {f['status']}")
        print(f"      {f['summary']}")
        print(f"      工具: {', '.join(f.get('tools_called', []))}")

    print("\n--- Executive Summary ---")
    es = report["executive_summary"]
    print(f"  Research  : {es['research_summary']}")
    print(f"  Risk      : {es['risk_summary']}")
    print(f"  Compliance: {es['compliance_summary']}")
    print("  关键发现：")
    for k in es.get("key_findings", []):
        print(f"    - {k}")

    print("\n--- Research Findings ---")
    rf = report["research_findings"]
    co = rf["company_overview"]
    print(f"  业务领域: {co['business_fields']}")
    print(f"  增长驱动: {rf['business_analysis']['growth_drivers']}")
    print(f"  财务指标: {len(rf['financial_summary']['key_metrics'])} 项")

    print("\n--- Risk Findings ---")
    rsk = report["risk_findings"]
    print(f"  整体风险: {rsk['risk_score']}/100 {rsk['risk_level']}")
    print(f"  风险点  : {len(rsk['risk_findings'])} 项")
    print(f"  冲突    : {len(rsk['conflict_findings'])} 项")
    for c in rsk.get("conflict_findings", [])[:3]:
        print(f"    - [{c['finding_id']}] {c['claim_id']} {c['conflict_type']} | {c['difference']}")

    print("\n--- Compliance Findings ---")
    comp = report["compliance_findings"]
    print(f"  合规评分: {comp['overall_compliance_score']}/100")
    print(f"  无证据支持: {comp['unsupported_claim_count']}")
    print(f"  夸大表达  : {comp['overstatement_count']}")
    print(f"  证据缺失  : {comp['missing_evidence_count']}")
    print(f"  预测为事实: {comp['forecast_as_fact_count']}")
    for f in comp.get("findings", [])[:5]:
        print(f"    - [{f['finding_id']}] {f['check_type']} ({f['severity']}): {f['description']}")

    print("\n--- Human Review Items（自动提请） ---")
    for h in report.get("human_review_items", []):
        print(f"  [{h['item_id']}] {h['agent']} · {h['review_type']} | {h['description']}")

    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "id": report["id"],
        "company": report["company"],
        "overall_risk_score": report["overall_risk_score"],
        "overall_risk_level": report["overall_risk_level"],
        "overall_compliance_score": es["overall_compliance_score"],
        "agent_flow": report["agent_flow"],
        "human_review_items_count": len(report.get("human_review_items", [])),
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
    print("=" * 78)


if __name__ == "__main__":
    _report = run_demo()
    _print_report(_report)
