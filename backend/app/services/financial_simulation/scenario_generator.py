"""FinProof FinSim Scenario Generator（Phase 18，任务书 §2 §5）。

生成 5 类场景（Financial Misstatement / Business Overstatement / Growth Quality Problem /
Competitive Claim Verification / Risk Monitoring）× 3 难度（Easy / Medium / Hard）。

Hard 难度埋点隐藏风险（如收入增长正常但现金流恶化/应收增/库存增），测试 Agent
是否发现增长质量问题。

保持 Evidence First：场景埋点均含可被 Evidence Retrieval 检索到的关键词。
"""

from __future__ import annotations

from app.services.financial_simulation.schemas import (
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_MEDIUM,
    ExpectedFinding,
    SCENARIO_BUSINESS_OVERSTATEMENT,
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
    SCENARIO_FINANCIAL_MISSTATEMENT,
    SCENARIO_GROWTH_QUALITY_PROBLEM,
    SCENARIO_RISK_MONITORING,
    SimulationScenario,
)


# ---------------------------------------------------------------------------
# 场景生成器：5 类 × 3 难度
# ---------------------------------------------------------------------------
def make_scenario(
    scenario_id: str,
    scenario_type: str,
    company: str,
    industry: str,
    difficulty: str = DIFFICULTY_EASY,
) -> SimulationScenario:
    """按类型 + 难度生成场景。

    Hard 难度额外埋点隐藏风险（任务书 §5）。
    """
    builder = _BUILDERS.get(scenario_type)
    if builder is None:
        raise ValueError(f"未知场景类型: {scenario_type}")
    return builder(scenario_id, company, industry, difficulty)


# ---------------------------------------------------------------------------
# A. Financial Misstatement（财务错报）
# ---------------------------------------------------------------------------
def _build_financial_misstatement(sid: str, company: str, industry: str, difficulty: str) -> SimulationScenario:
    expected = [
        ExpectedFinding(
            finding_id="EF-A1", category="risk", finding_type="financial",
            text=f"{company} 海外收入同比增长 但 海外利润同比下滑",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-A2", category="logic", finding_type="financial",
            text="收入增长不等于利润贡献增长（结论过度跳跃）",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-A3", category="fact", finding_type="financial",
            text=f"{company} 营业收入 同比增长 净利润 同比",
            must_find=False,
        ),
    ]
    hidden = []
    if difficulty == DIFFICULTY_HARD:
        hidden = [
            "海外业务利润率低于整体（收入增但利润降）",
            "海外业务成本结构恶化导致利润贡献下降",
        ]
        expected.append(ExpectedFinding(
            finding_id="EF-A4", category="risk", finding_type="financial",
            text="海外业务利润率下降 成本结构恶化",
            must_find=True,
        ))
    return SimulationScenario(
        scenario_id=sid,
        scenario_type=SCENARIO_FINANCIAL_MISSTATEMENT,
        company=company,
        industry=industry,
        objective=f"核查 {company} 海外业务增长是否伴随利润同步增长，识别收入→利润的逻辑跳跃",
        available_documents=[{"document_id": f"{company}-2025年报", "period": "2025FY"}],
        hidden_risks=hidden,
        expected_findings=expected,
        difficulty=difficulty,
        task_query=f"{company} 海外收入增长 海外业务利润增长核心",
    )


# ---------------------------------------------------------------------------
# B. Business Overstatement（业务夸大）
# ---------------------------------------------------------------------------
def _build_business_overstatement(sid: str, company: str, industry: str, difficulty: str) -> SimulationScenario:
    expected = [
        ExpectedFinding(
            finding_id="EF-B1", category="logic", finding_type="business",
            text=f"{company} 市场份额领先 不等于 长期竞争优势（隐含假设）",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-B2", category="fact", finding_type="business",
            text=f"{company} 市场份额 排名",
            must_find=False,
        ),
    ]
    hidden = []
    if difficulty == DIFFICULTY_HARD:
        hidden = [
            "竞争格局稳定性未披露",
            "技术迭代风险未披露",
            "客户黏性证据缺失",
        ]
        expected.append(ExpectedFinding(
            finding_id="EF-B3", category="logic", finding_type="business",
            text="竞争格局稳定性 技术迭代 客户黏性 未披露",
            must_find=True,
        ))
    return SimulationScenario(
        scenario_id=sid,
        scenario_type=SCENARIO_BUSINESS_OVERSTATEMENT,
        company=company,
        industry=industry,
        objective=f"验证 {company} 市场份额领先 是否可推出长期竞争优势，识别隐含假设",
        available_documents=[{"document_id": f"{company}-行业研报", "period": "2025"}],
        hidden_risks=hidden,
        expected_findings=expected,
        difficulty=difficulty,
        task_query=f"{company} 市场份额领先 长期竞争优势",
    )


# ---------------------------------------------------------------------------
# C. Growth Quality Problem（增长质量问题，任务书 §5 Hard 范例）
# ---------------------------------------------------------------------------
def _build_growth_quality(sid: str, company: str, industry: str, difficulty: str) -> SimulationScenario:
    expected = [
        ExpectedFinding(
            finding_id="EF-C1", category="fact", finding_type="growth",
            text=f"{company} 营业收入 同比增长",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-C2", category="risk", finding_type="growth",
            text="经营现金流 同比下降 应收账款 同比上升",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-C3", category="logic", finding_type="growth",
            text="营收增长不等于经营质量改善（增长质量低）",
            must_find=True,
        ),
    ]
    hidden = []
    if difficulty in (DIFFICULTY_HARD, DIFFICULTY_MEDIUM):
        hidden = [
            "库存增加 存货 同比上升",
            "毛利率下降",
        ]
        expected.append(ExpectedFinding(
            finding_id="EF-C4", category="risk", finding_type="growth",
            text="存货 同比上升 毛利率 下降",
            must_find=(difficulty == DIFFICULTY_HARD),
        ))
    return SimulationScenario(
        scenario_id=sid,
        scenario_type=SCENARIO_GROWTH_QUALITY_PROBLEM,
        company=company,
        industry=industry,
        objective=f"评估 {company} 增长质量：营收增长是否伴随现金流/应收/存货/毛利率同步改善",
        available_documents=[{"document_id": f"{company}-2025年报", "period": "2025FY"}],
        hidden_risks=hidden,
        expected_findings=expected,
        difficulty=difficulty,
        task_query=f"{company} 营收增长 经营质量改善",
    )


# ---------------------------------------------------------------------------
# D. Competitive Claim Verification（竞争主张验证）
# ---------------------------------------------------------------------------
def _build_competitive_claim(sid: str, company: str, industry: str, difficulty: str) -> SimulationScenario:
    expected = [
        ExpectedFinding(
            finding_id="EF-D1", category="fact", finding_type="competitive",
            text=f"{company} 竞争对手 市场份额 排名",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-D2", category="logic", finding_type="competitive",
            text="公司自述不能单独证明行业领先（需独立证据）",
            must_find=True,
        ),
    ]
    hidden = []
    if difficulty == DIFFICULTY_HARD:
        hidden = ["竞争对手份额数据未披露", "行业排名来源缺失"]
        expected.append(ExpectedFinding(
            finding_id="EF-D3", category="risk", finding_type="competitive",
            text="竞争对手份额数据 排名来源 未披露",
            must_find=True,
        ))
    return SimulationScenario(
        scenario_id=sid,
        scenario_type=SCENARIO_COMPETITIVE_CLAIM_VERIFICATION,
        company=company,
        industry=industry,
        objective=f"验证 {company} 行业领先主张：需独立证据，公司自述不足以证明",
        available_documents=[{"document_id": f"{company}-行业研报", "period": "2025"}],
        hidden_risks=hidden,
        expected_findings=expected,
        difficulty=difficulty,
        task_query=f"{company} 行业领先 竞争对手 市场份额",
    )


# ---------------------------------------------------------------------------
# E. Risk Monitoring（风险监控）
# ---------------------------------------------------------------------------
def _build_risk_monitoring(sid: str, company: str, industry: str, difficulty: str) -> SimulationScenario:
    expected = [
        ExpectedFinding(
            finding_id="EF-E1", category="risk", finding_type="risk",
            text=f"{company} 海外业务 利润 同比下滑（风险信号）",
            must_find=True,
        ),
        ExpectedFinding(
            finding_id="EF-E2", category="contradiction", finding_type="risk",
            text="claim 与事实冲突：海外利润增长 vs 滑下",
            must_find=True,
        ),
    ]
    hidden = []
    if difficulty == DIFFICULTY_HARD:
        hidden = ["历史观点与最新披露冲突", "同一报告前后口径不一致"]
        expected.append(ExpectedFinding(
            finding_id="EF-E3", category="contradiction", finding_type="risk",
            text="历史观点 最新披露 冲突",
            must_find=True,
        ))
    return SimulationScenario(
        scenario_id=sid,
        scenario_type=SCENARIO_RISK_MONITORING,
        company=company,
        industry=industry,
        objective=f"监控 {company} 海外业务风险：识别利润下滑信号与 claim-事实冲突",
        available_documents=[{"document_id": f"{company}-2025年报", "period": "2025FY"}],
        hidden_risks=hidden,
        expected_findings=expected,
        difficulty=difficulty,
        task_query=f"{company} 海外业务利润增长",
    )


_BUILDERS = {
    SCENARIO_FINANCIAL_MISSTATEMENT: _build_financial_misstatement,
    SCENARIO_BUSINESS_OVERSTATEMENT: _build_business_overstatement,
    SCENARIO_GROWTH_QUALITY_PROBLEM: _build_growth_quality,
    SCENARIO_COMPETITIVE_CLAIM_VERIFICATION: _build_competitive_claim,
    SCENARIO_RISK_MONITORING: _build_risk_monitoring,
}


# ---------------------------------------------------------------------------
# 场景库：批量生成
# ---------------------------------------------------------------------------
def list_scenario_types() -> list[str]:
    return list(_BUILDERS.keys())


def build_scenario_catalog(
    company: str = "测试公司",
    industry: str = "家电",
) -> list[SimulationScenario]:
    """生成 5 类 × 3 难度 = 15 场景的目录。"""
    catalog: list[SimulationScenario] = []
    for st in _BUILDERS:
        for diff in (DIFFICULTY_EASY, DIFFICULTY_MEDIUM, DIFFICULTY_HARD):
            sid = f"SCEN-{st[0]}-{diff[0]}"
            catalog.append(make_scenario(sid, st, company, industry, diff))
    return catalog


# ---------------------------------------------------------------------------
# Demo 3 场景（任务书 §7）
# ---------------------------------------------------------------------------
def make_demo_scenarios() -> list[SimulationScenario]:
    """Demo 3 场景：美的海外增长逻辑 / 宁德时代竞争优势 / 五粮液增长质量。"""
    return [
        make_scenario("SCEN-DEMO-1", SCENARIO_FINANCIAL_MISSTATEMENT, "美的集团", "家电", DIFFICULTY_HARD),
        make_scenario("SCEN-DEMO-2", SCENARIO_COMPETITIVE_CLAIM_VERIFICATION, "宁德时代", "新能源", DIFFICULTY_MEDIUM),
        make_scenario("SCEN-DEMO-3", SCENARIO_GROWTH_QUALITY_PROBLEM, "五粮液", "白酒", DIFFICULTY_HARD),
    ]


__all__ = [
    "make_scenario",
    "list_scenario_types",
    "build_scenario_catalog",
    "make_demo_scenarios",
]
