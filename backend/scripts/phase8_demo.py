"""Phase 8 · Demo — 美的集团投资调查（Investment Intelligence Agent）。

任务书 §5 Demo 要求：
- 投资材料中的 3 条观点：
  1. 海外业务高速增长
  2. 公司保持行业领先
  3. 盈利能力持续提升
- 展示：Claim ↓ External Evidence ↓ Conflict/Support ↓ Risk

设计约束（任务书）：
- 不开发自动投资建议；
- 不进行股票推荐；
- 不替代投资经理决策。
- 不修改已有核心验证逻辑。

运行：
    cd backend
    python -m scripts.phase8_demo
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 确保可以 import app.*
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
sys.path.insert(0, str(_BACKEND))

from app.core.config import BASE_DIR  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import document_service as dsvc  # noqa: E402
from app.services.intelligence.intelligence_agent import (  # noqa: E402
    run_investigation,
    save_report,
)
from app.services.intelligence.schemas import (  # noqa: E402
    FACT_DIM_COMPETITION,
    FACT_DIM_FINANCIAL,
    FACT_DIM_MARKET,
    FACT_SOURCE_ANNOUNCEMENT,
    FACT_SOURCE_NEWS,
    FACT_SOURCE_OFFICIAL_SITE,
    InvestmentClaim,
)


# ---------------------------------------------------------------------------
# 1) 投资材料中的 3 条观点（InvestmentClaim）
# ---------------------------------------------------------------------------
def _build_claims() -> list[InvestmentClaim]:
    return [
        InvestmentClaim(
            claim_id="INV-0001",
            claim="海外业务高速增长",
            dimension=FACT_DIM_MARKET,
            period="2025FY",
        ),
        InvestmentClaim(
            claim_id="INV-0002",
            claim="公司保持行业领先",
            dimension=FACT_DIM_COMPETITION,
            period="2025FY",
        ),
        InvestmentClaim(
            claim_id="INV-0003",
            claim="盈利能力持续提升",
            dimension=FACT_DIM_FINANCIAL,
            period="2025FY",
        ),
    ]


# ---------------------------------------------------------------------------
# 2) 外部事实（公告 / 新闻 / 官网，Evidence First）
# ---------------------------------------------------------------------------
def _build_external_facts() -> list[dict]:
    ts_base = datetime(2026, 7, 31, 12, 0, 0)
    # 时间戳交错，便于证据链展示
    announcement_ts = (ts_base - timedelta(days=10)).isoformat(timespec="seconds") + "Z"
    news_ts = (ts_base - timedelta(days=3)).isoformat(timespec="seconds") + "Z"
    official_ts = (ts_base - timedelta(days=30)).isoformat(timespec="seconds") + "Z"

    return [
        {
            "dimension": FACT_DIM_FINANCIAL,
            "subject": "美的集团",
            "statement": "公司发布 2025 年半年度业绩预增公告，归母净利润预增",
            "source": FACT_SOURCE_ANNOUNCEMENT,
            "source_label": "美的集团 2025 年半年度业绩预增公告",
            "evidence": "公司发布 2025 年半年度业绩预增公告，预计归母净利润同比增长。",
            "timestamp": announcement_ts,
            "confidence": 0.85,
            "period": "2025H1",
        },
        {
            "dimension": FACT_DIM_COMPETITION,
            "subject": "美的空调",
            "statement": "美的空调线上线下市场份额双第一",
            "source": FACT_SOURCE_NEWS,
            "source_label": "行业第三方报告：美的空调线上线下份额双第一",
            "evidence": "行业第三方报告显示，2025 年美的空调线上线下市场份额均位列第一。",
            "timestamp": news_ts,
            "confidence": 0.75,
            "period": "2025FY",
        },
        {
            "dimension": FACT_DIM_MARKET,
            "subject": "美的集团",
            "statement": "公司官网披露核心产品线：暖通空调 / 消费电器 / 机器人与自动化",
            "source": FACT_SOURCE_OFFICIAL_SITE,
            "source_label": "美的集团官网产品介绍",
            "evidence": "公司官网披露核心产品线：暖通空调 / 消费电器 / 机器人与自动化。",
            "timestamp": official_ts,
            "confidence": 0.90,
            "period": "2025FY",
        },
    ]


# ---------------------------------------------------------------------------
# 3) 注册演示文档（年报 PDF），返回 document_id
# ---------------------------------------------------------------------------
def _ensure_demo_document() -> int:
    annual_report = BASE_DIR.parent / "data" / "demo" / "source" / "annual_report.pdf"
    # 优先查找已登记的同名同 SHA 文档；无则注册
    from app.models import Document

    with SessionLocal() as s:
        if annual_report.exists():
            doc, _ = dsvc.register_document(
                s,
                filename=annual_report.name,
                data=annual_report.read_bytes(),
                document_role="SOURCE_DOCUMENT",
                company_name="美的集团",
                stock_code="000333",
                report_period="2025FY",
            )
            return doc.id
        # 无 PDF 则用一份小型 Markdown 演示文档兜底
        demo_md = (
            "# 美的集团 2025 年年度报告\n\n"
            "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n"
            "归母净利润439.45亿元，同比增长38.02%。\n"
            "公司主营业务包括暖通空调、消费电器、机器人与自动化。\n"
            "海外业务已成为公司利润增长的核心引擎。\n"
            "公司空调线上线下市场份额保持第一。\n"
        ).encode("utf-8")
        doc, _ = dsvc.register_document(
            s,
            filename="midea_demo.md",
            data=demo_md,
            document_role="SOURCE_DOCUMENT",
            company_name="美的集团",
            stock_code="000333",
            report_period="2025FY",
        )
        return doc.id


# ---------------------------------------------------------------------------
# 4) 主入口
# ---------------------------------------------------------------------------
def run_demo() -> dict:
    init_db()
    with SessionLocal() as s:
        doc_id = _ensure_demo_document()
        claims = _build_claims()
        external_facts = _build_external_facts()
        report = run_investigation(
            s,
            doc_id,
            claims,
            external_fact_records=external_facts,
        )
        report = save_report(s, report)
        return report.to_dict()


def _print_report(report: dict) -> None:
    print("=" * 78)
    print("FinProof Phase 8 · Investment Intelligence Agent — 美的集团")
    print("=" * 78)
    print(f"Company          : {report['company']}（{report['stock_code']}）")
    print(f"Report Period    : {report['report_period']}")
    print(f"Overall Risk     : {report['overall_risk_score']}/100 {report['overall_risk_level']}")
    print(f"Conflict / Support: {report['conflict_count']} / {report['support_count']}")
    print(f"Verified Facts   : {len(report['verified_facts'])}")

    print("\n--- Company Profile ---")
    profile = report["company_profile"]
    print(f"  business_fields : {profile['business_fields']}")
    print(f"  key_financials  : {profile['key_financials'][:5]}")
    print(f"  products         : {profile['products']}")
    print(f"  competitors      : {profile['competitors']}")

    print("\n--- Conflicts (Claim ↓ Fact ↓ Conflict) ---")
    for c in report["conflicts"]:
        print(f"  [{c['finding_id']}] {c['claim_id']} → {c['conflict_type']}")
        print(f"      claim    : {c['claim']}")
        print(f"      fact     : {c['fact']}")
        print(f"      diff     : {c['difference']}")
        print(f"      risk     : {c['risk_type']} {c['risk_score']} {c['risk_level']}")

    print("\n--- Risk Findings ---")
    for r in report["risk_findings"]:
        print(f"  [{r['finding_id']}] {r['claim_id']} {r['risk_type']} {r['risk_score']} {r['risk_level']}")
        print(f"      {r['summary']}")

    print("\n--- Evidence Chain (Claim ↓ External Evidence ↓ Conflict/Support ↓ Risk) ---")
    for ec in report["evidence_chain"]:
        print(f"  • {ec['claim_id']}: {ec['claim']}")
        for ev in ec.get("evidence", []):
            role = ev.get("role", "fact")
            if role == "fact":
                print(f"      ↓ fact[{ev.get('source','')}] {ev.get('text','')[:80]}")
            else:
                print(f"      ↓ claim {ev.get('text','')[:80]}")
        print(f"      ↓ conflict: {ec['conflict_type']} | risk {ec['risk_score']} {ec['risk_level']}")

    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "id": report["id"],
        "company": report["company"],
        "overall_risk_score": report["overall_risk_score"],
        "overall_risk_level": report["overall_risk_level"],
        "conflict_count": report["conflict_count"],
        "support_count": report["support_count"],
        "conflicts": report["conflicts"],
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
    print("=" * 78)


if __name__ == "__main__":
    _report = run_demo()
    _print_report(_report)
