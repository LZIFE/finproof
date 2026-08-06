"""Phase 23.10 — Claim Query Planner：多 query 生成与候选贡献追踪。

将每个 Claim 解析为结构化查询计划，生成多个检索 query（禁止只用完整
claim sentence 做唯一 query）：

1. metric + value
2. metric + period
3. metric alias + normalized value
4. entity + metric + period
5. metric + unit + scope
6. table-oriented query（含表格关键词）
7. narrative-oriented query（含叙述关键词）

每个 query 记录其贡献的候选（candidate_contributions：query_id → block_ids），
供 Stage A 高召回与 Stage B reranker 使用。

用法：
    from app.services.evidence_retrieval.query_planner import QueryPlanner
    plan = QueryPlanner(claim).build()
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.verification.financial_value import extract_financial_values
from app.services.verification.metric_scope import METRIC_ALIASES, normalize_metric, query_expansion

# 表格化关键词（table-oriented query 注入）
_TABLE_KW = ("（千元）", "（元）", "（万元）", "（亿元）", "千元", "万元", "亿元", "年度", "本期", "上年同期", "增减")
# 叙述关键词（narrative-oriented query 注入）
_NARR_KW = ("同比增长", "同比下降", "增长", "下降", "实现", "主要系", "由于", "得益于", "推动", "带动")


@dataclass
class QueryItem:
    query_id: str
    kind: str
    query_text: str
    candidate_block_ids: list = field(default_factory=list)


@dataclass
class QueryPlan:
    claim_id: str
    entity: str
    metric: str
    metric_aliases: list
    value: float | None
    normalized_value: str
    period: str
    period_aliases: list
    unit: str
    scope: str
    claim_type: str
    direction: str
    keywords: list
    need: list = field(default_factory=list)
    queries: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "entity": self.entity, "metric": self.metric,
            "metric_aliases": self.metric_aliases[:10],
            "value": self.value, "normalized_value": self.normalized_value,
            "period": self.period, "period_aliases": self.period_aliases,
            "unit": self.unit, "scope": self.scope, "claim_type": self.claim_type,
            "direction": self.direction, "keywords": self.keywords[:12],
            "need": self.need,
            "queries": [
                {"query_id": q.query_id, "kind": q.kind, "query_text": q.query_text,
                 "candidate_block_ids": q.candidate_block_ids}
                for q in self.queries
            ],
        }


def _period_aliases(period: str) -> list[str]:
    """期间别名：2025FY → [2025年度, 2025年, 年度, 报告期]；2025H1 → [上半年, 半年度]；Qn → [第n季度, n季度]。"""
    p = str(period or "").upper()
    out: list[str] = []
    m = re.match(r"(\d{4})(FY|H1|Q[1-4])", p)
    if not m:
        return [p]
    year, seg = m.group(1), m.group(2)
    out.append(f"{year}年")
    if seg == "FY":
        out += [f"{year}年度", "年度", "报告期", "全年", "本年度"]
    elif seg == "H1":
        out += ["上半年", "半年度", f"{year}年上半年", "1-6月"]
    else:
        q = seg[1]
        out += [f"第{q}季度", f"{q}季度", f"{year}年第{q}季度"]
    return out


def _direction_of(text: str) -> str:
    if any(k in text for k in ("超过", "高于", "大于", "突破", "以上")):
        return ">="
    if any(k in text for k in ("低于", "小于", "以下", "不超过")):
        return "<="
    return "=="


class QueryPlanner:
    def __init__(self, claim: dict) -> None:
        self.claim = claim

    def build(self) -> QueryPlan:
        c = self.claim
        cid = c.get("claim_id") or c.get("claim_uid") or "?"
        entity = str(c.get("entity") or c.get("entity_name") or "").strip()
        metric = str(c.get("metric") or "").strip()
        metric_code = str(c.get("metric_code") or "").strip() or metric
        period = str(c.get("period") or "").strip()
        unit = str(c.get("unit") or "").strip()
        scope = str(c.get("scope") or "consolidated").strip()
        claim_type = str(c.get("claim_type") or "").upper()
        text = str(c.get("original_text") or c.get("source_text") or "").strip()
        value = c.get("value") if isinstance(c.get("value"), (int, float)) else None

        # 指标别名（含家族扩展）
        aliases = set(query_expansion(metric_code))
        aliases |= set(query_expansion(metric)) if metric else set()
        std, _conf = normalize_metric(metric_code or metric)
        if std and std in METRIC_ALIASES:
            aliases |= set(METRIC_ALIASES[std])
        aliases = {a for a in aliases if a}
        cn_aliases = [a for a in aliases if re.search(r"[\u4e00-\u9fff]", a)][:12]

        # 数字归一化（去千分位/单位换算为亿元级别展示）
        norm_str = ""
        if value is not None:
            if unit in ("亿元", "亿元"):
                norm_str = f"{value:g}亿"
            elif unit in ("%", "％"):
                norm_str = f"{value:g}%"
            else:
                norm_str = f"{value:g}"
        # 关键词（claim 原文内容词）
        keywords = [w for w in re.findall(r"[\u4e00-\u9fff]{2,6}", text) if w not in
                    ("公司", "集团", "我们", "报告", "期内", "实现", "同比", "增长", "下降", "达到", "超过", "根据", "发布")][:12]

        # Phase 23.14 Step 2：Claim-aware need 解析（value / previous_value / growth）
        need: list[str] = []
        if value is not None:
            need.append("value")
        # 上一期数值需求：含"上年同期/上期/同比/较上年/比上期/增长/下降"等比较词
        comp_words = ("上年同期", "上期", "同比", "较上年", "比上期", "去年同期", "相比上年", "增长", "下降", "增减")
        if any(w in text for w in comp_words):
            need.append("previous_value")
        # 增长率需求：含"同比/增长/下降/YoY/增速/增幅"
        growth_words = ("同比", "同比增长", "同比增长率", "增长幅度", "增速", "增幅", "YoY", "增长率", "增长")
        if any(w in text for w in growth_words):
            need.append("growth")
        need = list(dict.fromkeys(need))  # 去重保序

        queries: list[QueryItem] = []
        qid = 0

        def add(kind: str, parts: list[str]) -> None:
            nonlocal qid
            qid += 1
            qtext = " ".join(p for p in parts if p)
            queries.append(QueryItem(query_id=f"q{qid}", kind=kind, query_text=qtext))

        # 1) metric + value
        add("metric_value", [cn_aliases[0] if cn_aliases else metric, norm_str])
        # 2) metric + period
        add("metric_period", [cn_aliases[0] if cn_aliases else metric] + _period_aliases(period)[:2])
        # 3) metric alias + normalized value
        if len(cn_aliases) > 1:
            add("alias_value", [cn_aliases[1], norm_str])
        elif norm_str:
            add("alias_value", [cn_aliases[0] if cn_aliases else metric, norm_str])
        # 4) entity + metric + period
        add("entity_metric_period", [entity] + [cn_aliases[0] if cn_aliases else metric] + _period_aliases(period)[:1])
        # 5) metric + unit + scope
        add("metric_unit_scope", [cn_aliases[0] if cn_aliases else metric, unit, scope])
        # 6) table-oriented
        table_kw = [k for k in _TABLE_KW if k in text] or list(_TABLE_KW)[:3]
        add("table_oriented", [cn_aliases[0] if cn_aliases else metric] + table_kw[:3])
        # 7) narrative-oriented
        narr_kw = [k for k in _NARR_KW if k in text] or list(_NARR_KW)[:3]
        add("narrative_oriented", [cn_aliases[0] if cn_aliases else metric] + narr_kw[:3])

        return QueryPlan(
            claim_id=cid, entity=entity, metric=metric_code, metric_aliases=list(aliases)[:15],
            value=value, normalized_value=norm_str, period=period,
            period_aliases=_period_aliases(period), unit=unit, scope=scope,
            claim_type=claim_type, direction=_direction_of(text), keywords=keywords,
            need=need,
            queries=queries,
        )


__all__ = ["QueryPlanner", "QueryPlan", "QueryItem"]
