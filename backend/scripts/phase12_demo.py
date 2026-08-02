"""Phase 12 · Demo — Enterprise Investment Governance Layer。

任务书 §5 Demo 要求：
- 投资组合：3 家公司（美的集团 / 五粮液 / 宁德时代）
- 模拟：某公司出现新风险（新 Fact 与历史 Claim 冲突）
- 展示：Portfolio Risk Dashboard + Continuous Monitoring + Audit Trail

流程：
  ① Portfolio          3 家公司入组合 → 加权风险分 / 排名 / 分布
  ② Monitoring         保存历史投资观点 → 模拟新 Fact → 检测 Thesis Conflict
  ③ Audit Trail        记录关键操作 → 证据溯源
  ④ 模拟新风险         美的集团毛利率大幅下滑 → 生成告警

设计约束（任务书）：
- 不修改已有核心模块；Portfolio / Monitoring / Audit Trail 作为新增治理层。
- 不输出投资建议、不自动决定买卖。

运行：
    cd backend
    python -m scripts.phase12_demo
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
from app.services.portfolio import (  # noqa: E402
    add_project,
    build_snapshot,
    list_projects,
    update_project_risk,
)
from app.services.monitoring import (  # noqa: E402
    add_thesis,
    list_alerts,
    run_monitoring,
    update_alert_status,
)
from app.services.audit_trail import list_logs, log_audit  # noqa: E402


PORTFOLIO_ID = "PF-PHASE12"


def _companies() -> list[dict]:
    """3 家公司投资组合（任务书 §5）。"""
    return [
        {
            "company": "美的集团",
            "stock_code": "000333",
            "weight": 0.40,
            "latest_risk_score": 42.0,  # MEDIUM
        },
        {
            "company": "五粮液",
            "stock_code": "000858",
            "weight": 0.35,
            "latest_risk_score": 28.0,  # LOW
        },
        {
            "company": "宁德时代",
            "stock_code": "300750",
            "weight": 0.25,
            "latest_risk_score": 68.0,  # HIGH
        },
    ]


def _theses() -> list[dict]:
    """历史投资观点（Continuous Monitoring 追踪对象）。"""
    return [
        {
            "thesis_id": "THS-MIDEA-001",
            "company": "美的集团",
            "claim": "美的集团毛利率维持稳定，2024 年毛利率约 28%",
            "metric": "毛利率",
            "metric_value": 28.0,
            "metric_unit": "%",
            "source": "2024 年年报",
            "risk_score": 20.0,
            "portfolio_id": PORTFOLIO_ID,
        },
        {
            "thesis_id": "THS-WULIANG-001",
            "company": "五粮液",
            "claim": "五粮液高端白酒营收持续增长，批价稳定",
            "metric": "营收增速",
            "metric_value": 12.0,
            "metric_unit": "%",
            "source": "2024 年年报",
            "risk_score": 15.0,
            "portfolio_id": PORTFOLIO_ID,
        },
        {
            "thesis_id": "THS-CATL-001",
            "company": "宁德时代",
            "claim": "宁德时代动力电池市占率全球第一，海外扩张顺利",
            "metric": "市占率",
            "metric_value": 37.0,
            "metric_unit": "%",
            "source": "2024 年年报",
            "risk_score": 45.0,
            "portfolio_id": PORTFOLIO_ID,
        },
    ]


def _new_facts() -> list[dict]:
    """模拟新 Fact（任务书 §5：某公司出现新风险）。

    - 美的集团：毛利率大幅下滑（METRIC_DRIFT + DIRECTION_REVERSAL）
    - 宁德时代：收到监管问询函（NEW_RISK）
    - 五粮液：营收保持稳定（无冲突）
    """
    return [
        {
            "thesis_id": "THS-MIDEA-001",
            "new_fact": "美的集团 2025 年一季度毛利率同比大幅下滑至 22%",
            "new_metric_value": 22.0,
        },
        {
            "thesis_id": "THS-CATL-001",
            "new_fact": "宁德时代收到监管问询函，涉及海外子公司财务披露",
        },
        {
            "thesis_id": "THS-WULIANG-001",
            "new_fact": "五粮液 2025 年一季度营收保持稳定增长",
            "new_metric_value": 13.0,
        },
    ]


def run_demo() -> dict:
    init_db()
    result: dict = {"portfolio_id": PORTFOLIO_ID}

    with SessionLocal() as s:
        # =======================================================
        # ① Portfolio Risk Dashboard：3 家公司入组合
        # =======================================================
        print("\n[1/4] Portfolio Risk Dashboard：3 家公司入组合…")

        # 清理旧数据（开发用）
        from app.models.portfolio import PortfolioProjectRow, PortfolioRiskSnapshotRow
        from app.models.monitoring import InvestmentThesisRow, MonitoringAlertRow

        s.query(PortfolioRiskSnapshotRow).filter(
            PortfolioRiskSnapshotRow.portfolio_id == PORTFOLIO_ID
        ).delete()
        s.query(PortfolioProjectRow).filter(
            PortfolioProjectRow.portfolio_id == PORTFOLIO_ID
        ).delete()
        s.query(MonitoringAlertRow).filter(
            MonitoringAlertRow.portfolio_id == PORTFOLIO_ID
        ).delete()
        s.query(InvestmentThesisRow).filter(
            InvestmentThesisRow.portfolio_id == PORTFOLIO_ID
        ).delete()
        s.commit()

        projects = []
        for c in _companies():
            p = add_project(
                s,
                portfolio_id=PORTFOLIO_ID,
                company=c["company"],
                stock_code=c["stock_code"],
                weight=c["weight"],
                latest_risk_score=c["latest_risk_score"],
            )
            projects.append(p)
            print(f"  · {p.company}（{p.stock_code}）权重 {p.weight:.0%} 风险分 {p.latest_risk_score}")

        # 审计日志：录入投资组合
        log_audit(
            s,
            user="analyst_zhang",
            action="PORTFOLIO_CREATE",
            target_type="portfolio",
            target_id=None,
            model_version="v1.0",
            rule_version="r2025",
            evidence_used=[{"source": "2024年报", "company": c["company"]} for c in _companies()],
            detail={"portfolio_id": PORTFOLIO_ID, "company_count": 3},
        )

        # 构建风险快照
        snapshot = build_snapshot(s, PORTFOLIO_ID)
        result["portfolio"] = snapshot.to_dict()

        print(f"\n  组合风险评分：{snapshot.portfolio_risk_score}（{snapshot.portfolio_risk_level}）")
        print("  公司风险排名：")
        for c in snapshot.company_ranking:
            print(f"    {c.rank}. {c.company} — {c.risk_score}（{c.risk_level}）")
        print("  风险分布：")
        for d in snapshot.risk_distribution:
            print(f"    {d.risk_level}: {d.count} 个（{d.share:.0%}）")

        # =======================================================
        # ② Continuous Monitoring：保存历史投资观点
        # =======================================================
        print("\n[2/4] Continuous Monitoring：保存历史投资观点…")
        for t in _theses():
            add_thesis(
                s,
                thesis_id=t["thesis_id"],
                company=t["company"],
                claim=t["claim"],
                metric=t["metric"],
                metric_value=t["metric_value"],
                metric_unit=t["metric_unit"],
                source=t["source"],
                risk_score=t["risk_score"],
                portfolio_id=t["portfolio_id"],
            )
            print(f"  · {t['thesis_id']} {t['company']}")

        # =======================================================
        # ③ 模拟新风险：新 Fact vs 历史 Claim
        # =======================================================
        print("\n[3/4] 模拟新风险：新 Fact vs 历史 Claim…")
        alerts = run_monitoring(s, PORTFOLIO_ID, _new_facts())
        result["monitoring"] = {
            "theses_count": len(_theses()),
            "new_facts_count": len(_new_facts()),
            "alerts_count": len(alerts),
            "alerts": [a.to_dict() for a in alerts],
        }

        for a in alerts:
            print(f"\n  ⚠ Alert {a.alert_id}")
            print(f"    公司      : {a.company}")
            print(f"    历史 claim: {a.claim[:50]}…")
            print(f"    新 Fact   : {a.new_fact[:50]}…")
            print(f"    差异      : {a.difference}")
            print(f"    冲突类型  : {a.conflict_type}")
            print(f"    风险分    : {a.risk_score}（{a.risk_level}）")

        # 审计日志：运行监控
        log_audit(
            s,
            user="analyst_zhang",
            action="RUN_MONITORING",
            target_type="portfolio",
            model_version="v1.0",
            rule_version="r2025",
            evidence_used=[
                {"thesis_id": nf["thesis_id"], "new_fact": nf["new_fact"][:30]}
                for nf in _new_facts()
            ],
            detail={"alerts_generated": len(alerts)},
        )

        # 模拟：美的集团风险分上调（因新风险）
        midea = next(p for p in projects if p.company == "美的集团")
        updated = update_project_risk(s, midea.project_id, 75.0)
        print(f"\n  美的集团风险分上调：{updated.latest_risk_score}（{updated.latest_risk_level}）")

        # 重新构建快照，展示风险变化
        snap2 = build_snapshot(s, PORTFOLIO_ID)
        result["portfolio_after_risk"] = snap2.to_dict()
        print(f"  组合风险评分更新：{snap2.portfolio_risk_score}（{snap2.portfolio_risk_level}）")

        # 标记告警为已处理
        for a in alerts:
            update_alert_status(s, a.alert_id, "RESOLVED")

        # =======================================================
        # ④ Audit Trail：审计日志与证据溯源
        # =======================================================
        print("\n[4/4] Audit Trail：审计日志与证据溯源…")
        logs = list_logs(s, limit=20)
        result["audit_trail"] = {
            "logs_count": len(logs),
            "logs": [l.to_dict() for l in logs],
        }

        for l in logs:
            print(f"  · {l.log_id} | {l.user} | {l.action} | {l.timestamp} | 证据 {len(l.evidence_used)} 条")

        # 证据溯源：查询 PORTFOLIO_CREATE 相关日志
        create_logs = list_logs(s, action="PORTFOLIO_CREATE", limit=5)
        result["evidence_trace"] = {
            "action": "PORTFOLIO_CREATE",
            "trace": [l.to_dict() for l in create_logs],
        }

    return result


def _print_summary(result: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 12 · Enterprise Investment Governance Layer — Demo Summary")
    print("=" * 78)

    p = result["portfolio"]
    print(f"\n[Portfolio] 组合 {p['portfolio_id']}")
    print(f"  组合风险评分 : {p['portfolio_risk_score']}（{p['portfolio_risk_level']}）")
    print(f"  公司风险排名 :")
    for c in p["company_ranking"]:
        print(f"    {c['rank']}. {c['company']} — {c['risk_score']}（{c['risk_level']}）")

    m = result["monitoring"]
    print(f"\n[Monitoring] 历史观点 {m['theses_count']} 条 · 新 Fact {m['new_facts_count']} 条")
    print(f"  生成告警 : {m['alerts_count']} 条")
    for a in m["alerts"]:
        print(f"    ⚠ {a['company']} — {a['conflict_type']} — 风险分 {a['risk_score']}")

    at = result["audit_trail"]
    print(f"\n[Audit Trail] 审计日志 {at['logs_count']} 条")
    print(f"  动作类型 : {', '.join(sorted({l['action'] for l in at['logs']}))}")

    print("\n" + "=" * 78)
    print("Demo 完成：Portfolio + Monitoring + Audit Trail 全链路打通。")
    print("约束遵守：不修改已有核心模块；不输出投资建议、不自动决定买卖。")
    print("=" * 78)


if __name__ == "__main__":
    _result = run_demo()
    _print_summary(_result)
    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "portfolio_id": _result["portfolio_id"],
        "portfolio_risk_score": _result["portfolio"]["portfolio_risk_score"],
        "portfolio_risk_level": _result["portfolio"]["portfolio_risk_level"],
        "company_ranking": _result["portfolio"]["company_ranking"],
        "risk_distribution": _result["portfolio"]["risk_distribution"],
        "monitoring": {
            "theses_count": _result["monitoring"]["theses_count"],
            "alerts_count": _result["monitoring"]["alerts_count"],
            "alerts": _result["monitoring"]["alerts"],
        },
        "audit_trail": {
            "logs_count": _result["audit_trail"]["logs_count"],
        },
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
