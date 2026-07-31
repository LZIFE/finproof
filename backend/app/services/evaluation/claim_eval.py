"""主张提取评测（Phase 3）：系统提取结果 vs gold_claims.json。

- 匹配信号：文本重叠 / 指标 / 数值 / 期间 / 主张类型
- 匹配状态：MATCHED / MISSED_GOLD / UNMATCHED_SYSTEM / AMBIGUOUS
- 指标：Precision / Recall / F1 / 高风险召回率 / 数字主张召回率 /
  语义主张召回率 / 字段准确率（数值/期间/指标）/ Schema 合法率 / 重复率 / 无效提取率
- 明确不做：SUPPORTED/REFUTED 等真假判定、数字计算正确性、证据页正确性
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# 金标准 claim_type → 系统枚举（近似兼容）
GOLD_TO_SYSTEM_TYPE = {
    "raw_number": {"ABSOLUTE_FINANCIAL_VALUE"},
    "calculated_financial_metric": {"GROWTH_RATE", "FINANCIAL_RATIO", "BUSINESS_SHARE"},
    "scope": {"ABSOLUTE_FINANCIAL_VALUE"},
    "business_fact": {"BUSINESS_FACT", "TREND"},
    "causality": {"CAUSAL_CLAIM"},
    "forecast": {"FORECAST"},
    "comparison": {"COMPARISON"},
}
SEMANTIC_GOLD_TYPES = {"business_fact", "causality", "forecast", "comparison"}

MATCH_THRESHOLD = 0.5
AMBIGUITY_EPSILON = 0.05

W_TEXT = 0.4
W_METRIC = 0.25
W_VALUE = 0.25
W_PERIOD = 0.15
W_TYPE = 0.1


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def period_compatible(gold_period: str | None, sys_period: str | None) -> bool:
    if not gold_period or not sys_period:
        return False
    if gold_period == sys_period:
        return True
    g = gold_period[:-2] if gold_period.endswith("FY") else gold_period
    s = sys_period[:-2] if sys_period.endswith("FY") else sys_period
    return g == s


def value_compatible(gold_value: float | None, sys_value: float | None) -> bool:
    if gold_value is None or sys_value is None:
        return False
    return abs(gold_value - sys_value) <= max(0.5, abs(gold_value) * 0.01)


def type_compatible(gold_type: str | None, sys_type: str | None) -> bool:
    if not gold_type or not sys_type:
        return False
    return sys_type in GOLD_TO_SYSTEM_TYPE.get(gold_type, set())


def metric_compatible(gold_metric: str | None, sys_metric: str | None) -> bool:
    if not gold_metric or not sys_metric:
        return False
    g, s = _norm(gold_metric), _norm(sys_metric)
    return g == s or g in s or s in g


def match_score(gold: dict, sys: dict) -> tuple[float, list[str]]:
    """计算一条系统主张与一条金标准主张的匹配分（0~1）。"""
    score = 0.0
    reasons: list[str] = []
    g_text, s_text = _norm(gold.get("original_text", "")), _norm(sys.get("source_text", ""))
    if g_text and s_text and (g_text in s_text or s_text in g_text or g_text == s_text):
        score += W_TEXT
        reasons.append("text_overlap")
    # 金标准 metric 存的是代码（如 revenue）；系统侧 metric_code 与之对齐，
    # 中文 metric 作为兜底（包含匹配）
    if metric_compatible(gold.get("metric"), sys.get("metric_code")) or metric_compatible(
        gold.get("metric"), sys.get("metric")
    ):
        score += W_METRIC
        reasons.append("metric")
    if value_compatible(gold.get("value"), sys.get("reported_value")):
        score += W_VALUE
        reasons.append("value")
    if period_compatible(gold.get("period"), sys.get("period")):
        score += W_PERIOD
        reasons.append("period")
    if type_compatible(gold.get("claim_type"), sys.get("claim_type")):
        score += W_TYPE
        reasons.append("type")
    return round(min(score, 1.0), 4), reasons


@dataclass
class MatchRecord:
    system_claim_id: int
    gold_claim_id: str | None
    match_score: float
    match_reasons: list[str]
    match_status: str


@dataclass
class EvalResult:
    records: list[MatchRecord] = field(default_factory=list)
    matched_gold_ids: set = field(default_factory=set)
    missed_gold: list[dict] = field(default_factory=list)
    unmatched_system: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)


def match_claims(system_claims: list[dict], gold_claims: list[dict]) -> EvalResult:
    """贪婪匹配 + 歧义标记（不强行自动选择）。"""
    assignments: dict[int, tuple[str, float, list[str]]] = {}
    ambiguous_sys: set[int] = set()

    for s in system_claims:
        scored = sorted(
            ((match_score(g, s)[0], g["claim_id"], match_score(g, s)[1]) for g in gold_claims),
            key=lambda x: -x[0],
        )
        if not scored:
            continue
        best = scored[0]
        second = scored[1] if len(scored) > 1 else (0.0, None, [])
        if best[0] >= MATCH_THRESHOLD:
            if second[0] >= MATCH_THRESHOLD and (best[0] - second[0]) < AMBIGUITY_EPSILON:
                ambiguous_sys.add(s["id"])
            else:
                assignments[s["id"]] = (best[1], best[0], best[2])

    gold_to_sys: dict[str, list[tuple[int, float]]] = {}
    for sid, (gid, sc, _reasons) in assignments.items():
        gold_to_sys.setdefault(gid, []).append((sid, sc))

    used_gold: set[str] = set()
    ambiguous_pairs: set[tuple[int, str]] = set()
    best_per_gold: dict[str, int] = {}
    for gid, cands in gold_to_sys.items():
        cands.sort(key=lambda x: -x[1])
        if len(cands) > 1 and (cands[0][1] - cands[1][1]) < AMBIGUITY_EPSILON:
            for sid, _sc in cands:
                ambiguous_pairs.add((sid, gid))
        else:
            used_gold.add(gid)
            best_per_gold[gid] = cands[0][0]  # 每个金标准只保留最佳系统主张

    result = EvalResult()
    for s in system_claims:
        sid = s["id"]
        if sid in ambiguous_sys:
            result.records.append(MatchRecord(sid, None, 0.0, [], "AMBIGUOUS"))
            result.ambiguous.append(s)
            continue
        if sid in assignments:
            gid, sc, reasons = assignments[sid]
            if (sid, gid) in ambiguous_pairs:
                result.records.append(MatchRecord(sid, gid, sc, reasons, "AMBIGUOUS"))
                result.ambiguous.append(s)
                continue
            # 仅"该金标准的最佳系统主张"计为 MATCHED；其余重复匹配计为 UNMATCHED_SYSTEM
            if gid in used_gold and best_per_gold.get(gid) == sid:
                result.records.append(MatchRecord(sid, gid, sc, reasons, "MATCHED"))
                result.matched_gold_ids.add(gid)
                continue
        result.records.append(MatchRecord(sid, None, 0.0, [], "UNMATCHED_SYSTEM"))
        result.unmatched_system.append(s)

    result.missed_gold = [
        g for g in gold_claims if g["claim_id"] not in result.matched_gold_ids
    ]
    return result


def compute_metrics(
    run: dict,
    result: EvalResult,
    gold_claims: list[dict],
    system_claims: list[dict],
) -> dict:
    """计算全部评测指标（运行级 + 匹配级）。"""
    total_system = len(system_claims)
    total_gold = len(gold_claims)
    matched = len(result.matched_gold_ids)
    precision = matched / total_system if total_system else 0.0
    recall = matched / total_gold if total_gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    matched_gold = [g for g in gold_claims if g["claim_id"] in result.matched_gold_ids]
    gold_by_id = {g["claim_id"]: g for g in gold_claims}
    sys_by_id = {s["id"]: s for s in system_claims}
    pairs = [
        (gold_by_id[r.gold_claim_id], sys_by_id[r.system_claim_id])
        for r in result.records
        if r.match_status == "MATCHED" and r.gold_claim_id in gold_by_id
    ]

    high_risk_gold = [
        g for g in gold_claims if str(g.get("risk_level", "")).upper() in ("HIGH", "CRITICAL")
    ]
    numeric_gold = [g for g in gold_claims if g.get("value") is not None]
    semantic_gold = [g for g in gold_claims if g.get("claim_type") in SEMANTIC_GOLD_TYPES]

    def _recall(subset: list[dict]) -> float:
        if not subset:
            return 0.0
        hit = sum(1 for g in subset if g["claim_id"] in result.matched_gold_ids)
        return hit / len(subset)

    def _accuracy(cond) -> float:
        if not pairs:
            return 0.0
        return sum(1 for g, s in pairs if cond(g, s)) / len(pairs)

    candidate_count = int(run.get("candidate_claim_count") or 0)
    schema_valid = int(run.get("schema_valid_count") or 0)
    duplicates = int(run.get("duplicate_removed_count") or 0)
    schema_validity = schema_valid / candidate_count if candidate_count else 0.0
    duplicate_rate = duplicates / candidate_count if candidate_count else 0.0
    unsupported_rate = len(result.unmatched_system) / total_system if total_system else 0.0

    return {
        "mode": run.get("mode"),
        "provider": run.get("provider"),
        "model_name": run.get("model_name"),
        "prompt_version": run.get("prompt_version"),
        "run_id": run.get("id"),
        "system_claim_count": total_system,
        "gold_claim_count": total_gold,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "high_risk_recall": round(_recall(high_risk_gold), 4),
        "numeric_claim_recall": round(_recall(numeric_gold), 4),
        "semantic_claim_recall": round(_recall(semantic_gold), 4),
        "exact_value_accuracy": round(_accuracy(lambda g, s: value_compatible(g.get("value"), s.get("reported_value"))), 4),
        "period_accuracy": round(_accuracy(lambda g, s: period_compatible(g.get("period"), s.get("period"))), 4),
        "metric_accuracy": round(
            _accuracy(
                lambda g, s: metric_compatible(g.get("metric"), s.get("metric_code"))
                or metric_compatible(g.get("metric"), s.get("metric"))
            ),
            4,
        ),
        "schema_validity_rate": round(schema_validity, 4),
        "duplicate_rate": round(duplicate_rate, 4),
        "unsupported_extraction_rate": round(unsupported_rate, 4),
        "ambiguous_count": len(result.ambiguous),
        "matched_count": matched,
        "missed_gold_count": len(result.missed_gold),
        "unmatched_system_count": len(result.unmatched_system),
    }


def build_report(metrics: dict, result: EvalResult, gold_claims: list[dict]) -> str:
    lines = [
        "# 主张提取评测报告",
        "",
        f"- 提取模式：`{metrics['mode']}`（Provider: {metrics['provider']}，模型: {metrics.get('model_name') or '无（Mock）'}）",
        f"- Prompt 版本：{metrics['prompt_version']}",
        f"- 系统主张数量：{metrics['system_claim_count']}；金标准主张数量：{metrics['gold_claim_count']}",
        "",
        "## 核心指标",
        "",
        "| 指标 | 数值 |",
        "| ---- | ---- |",
        f"| Precision | {metrics['precision']} |",
        f"| Recall | {metrics['recall']} |",
        f"| F1 | {metrics['f1']} |",
        f"| 高风险主张召回率 | {metrics['high_risk_recall']} |",
        f"| 数字主张召回率 | {metrics['numeric_claim_recall']} |",
        f"| 语义主张召回率 | {metrics['semantic_claim_recall']} |",
        f"| 数值识别准确率 | {metrics['exact_value_accuracy']} |",
        f"| 期间识别准确率 | {metrics['period_accuracy']} |",
        f"| 指标识别准确率 | {metrics['metric_accuracy']} |",
        f"| Schema 合法率 | {metrics['schema_validity_rate']} |",
        f"| 重复率 | {metrics['duplicate_rate']} |",
        f"| 无效提取率 | {metrics['unsupported_extraction_rate']} |",
        f"| 歧义匹配数 | {metrics['ambiguous_count']} |",
        "",
        "## 主要遗漏（MISSED_GOLD）",
        "",
    ]
    for g in result.missed_gold:
        lines.append(f"- {g['claim_id']} [{g['claim_type']}] {g['original_text']}")
    lines += ["", "## 主要误提取（UNMATCHED_SYSTEM）", ""]
    for s in result.unmatched_system[:20]:
        lines.append(f"- ({s.get('claim_type')}) {s.get('source_text', '')[:60]}")
    if len(result.unmatched_system) > 20:
        lines.append(f"- ……（其余 {len(result.unmatched_system) - 20} 条略）")
    lines += ["", "## 改进建议", ""]
    if metrics["semantic_claim_recall"] < 0.5:
        lines.append("- 语义类主张（业务事实/因果/预测）召回不足，建议规则补充信号词或接入真实 LLM。")
    if metrics["unsupported_extraction_rate"] > 0.3:
        lines.append("- 无效提取偏高，建议收紧候选过滤（无数字且无指标的子句）。")
    if metrics["period_accuracy"] < 0.8:
        lines.append("- 期间识别准确率偏低，建议加强期间上下文继承与年份推断。")
    lines.append("")
    return "\n".join(lines)


def write_artifacts(out_dir: Path, metrics: dict, result: EvalResult, report_md: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    def _dump(name: str, payload) -> None:
        (out_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    _dump("metrics.json", metrics)
    matched = [
        {
            "system_claim_id": r.system_claim_id,
            "gold_claim_id": r.gold_claim_id,
            "match_score": r.match_score,
            "match_reasons": r.match_reasons,
            "match_status": r.match_status,
        }
        for r in result.records
        if r.match_status == "MATCHED"
    ]
    _dump("matched_claims.json", matched)
    _dump("missed_gold_claims.json", result.missed_gold)
    _dump("unmatched_system_claims.json", result.unmatched_system)
    _dump("ambiguous_matches.json", result.ambiguous)
    (out_dir / "report.md").write_text(report_md, encoding="utf-8")
