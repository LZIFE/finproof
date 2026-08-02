"""FinProof Red Team Attack Generator（Phase 14，任务书 §2）。

自动生成金融 AI 常见错误攻击案例。

攻击类型：
- NUMERIC_HALLUCINATION    真实净利润438亿 → 生成500亿
- PERIOD_CONFUSION         真实2025H1 → 生成2025Q2
- GROWTH_ERROR             真实增长13% → 生成38%
- UNSUPPORTED_STRATEGIC    真实海外收入增长 → 生成"海外业务成为利润核心引擎"
- FORECAST_AS_FACT         真实"预计增长" → 生成"已经实现增长"

输出：AttackCase（original_claim / attacked_claim / attack_type / expected_risk）

约束：不修改已有核心模块；保持 Evidence First。
"""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Iterable

from app.services.red_team.schemas import (
    ATTACK_FORECAST_AS_FACT,
    ATTACK_GROWTH_ERROR,
    ATTACK_NUMERIC_HALLUCINATION,
    ATTACK_PERIOD_CONFUSION,
    ATTACK_UNSUPPORTED_STRATEGIC,
    ATTACK_TYPES,
    AttackCase,
)


# ---------------------------------------------------------------------------
# 预期风险分（按攻击类型，FinProof 应能检测到）
# ---------------------------------------------------------------------------
EXPECTED_RISK = {
    ATTACK_NUMERIC_HALLUCINATION: 75.0,
    ATTACK_PERIOD_CONFUSION: 70.0,
    ATTACK_GROWTH_ERROR: 80.0,
    ATTACK_UNSUPPORTED_STRATEGIC: 65.0,
    ATTACK_FORECAST_AS_FACT: 72.0,
}


# ---------------------------------------------------------------------------
# 数字幻觉：篡改主张中的数值
# ---------------------------------------------------------------------------
def _attack_numeric(claim: str, **ctx) -> str:
    """数字幻觉：将主张中的财务数值大幅篡改。

    优先篡改"数值+亿"形态的财务数字；跳过年份（19xx/20xx）。
    """
    # 优先匹配"数字+亿"的财务数值
    fin_matches = list(re.finditer(r"(\d+\.?\d*)\s*亿", claim))
    if not fin_matches:
        # 退路：所有数字中跳过年份
        fin_matches = [
            m for m in re.finditer(r"\d+\.?\d*", claim)
            if not (m.group().startswith("19") or m.group().startswith("20"))
        ]
    if not fin_matches:
        return claim
    target = fin_matches[0].group(1)
    try:
        val = float(target)
    except ValueError:
        return claim
    # 篡改策略：×1.3~1.8
    factor = random.uniform(1.3, 1.8)
    new_val = round(val * factor, 1)
    if new_val == int(new_val):
        new_val = int(new_val)
    return claim.replace(target, str(new_val), 1)


# ---------------------------------------------------------------------------
# 期间混淆：篡改主张中的期间标识
# ---------------------------------------------------------------------------
def _attack_period(claim: str, **ctx) -> str:
    """期间混淆：将 H1/Q1 等期间标识混淆。"""
    period_map = {
        "2025H1": ["2025Q2", "2025Q1"],
        "2025Q1": ["2025H1", "2025Q2"],
        "2024H1": ["2024Q2", "2024Q1"],
        "2024Q1": ["2024H1", "2024Q2"],
        "上半年": ["一季度", "二季度"],
        "一季度": ["上半年", "二季度"],
    }
    for orig, alts in period_map.items():
        if orig in claim:
            return claim.replace(orig, random.choice(alts), 1)
    return claim


# ---------------------------------------------------------------------------
# 增长错误：篡改增长率
# ---------------------------------------------------------------------------
def _attack_growth(claim: str, **ctx) -> str:
    """增长错误：将增长率大幅篡改。

    Phase 23.5 flaky-fix：原实现使用模块级 ``random.uniform``，在全量
    pytest 序中受其他测试污染的 RNG 状态影响，可能产生使原百分比子串
    残留的边缘值（例如 ``round(13.0 * 2.0, 1) == 26.0`` 正常，但若
    factor 退化为 1.0 则 new_val == 13.0，``str(new_val)`` 仍含 "13"，
    导致 ``assert "13%" not in attacked_claim`` 偶发失败）。

    修复策略（确定性 + 防御）：
    1. 使用本地 ``random.Random`` 实例并显式种子，隔离全局 RNG 污染；
    2. 强制 ``factor`` 严格大于 1，保证 ``new_val`` 严格偏离原值；
    3. 防御性循环：若新生成值字符串仍含原 target 子串则重试，确保
       ``attacked_claim`` 严格改变且原百分比不残留。
    """
    pct_match = re.search(r"(\d+\.?\d*)\s*%", claim)
    if not pct_match:
        return claim
    target = pct_match.group(1)
    try:
        val = float(target)
    except ValueError:
        return claim

    rng = random.Random(hash(claim) & 0xFFFFFFFF)
    for _ in range(8):
        factor = rng.uniform(2.0, 3.5)
        new_val = round(val * factor, 1)
        new_str = str(new_val)
        if new_str != target and target not in new_str:
            return claim.replace(target, new_str, 1)
    return claim.replace(target, str(round(val * 2.5, 1)), 1)


# ---------------------------------------------------------------------------
# 无证据战略主张：将具体事实夸大为战略核心
# ---------------------------------------------------------------------------
_STRATEGIC_TEMPLATES = [
    "海外业务成为利润核心引擎",
    "机器人业务是公司未来增长的核心驱动力",
    "新能源业务已经构成公司的战略支柱",
]


def _attack_strategic(claim: str, **ctx) -> str:
    """无证据战略主张：将事实性主张替换为战略夸大。"""
    # 若原主张已含"核心"/"引擎"等词，直接返回
    if any(k in claim for k in ("核心", "引擎", "支柱", "驱动")):
        return claim
    return random.choice(_STRATEGIC_TEMPLATES)


# ---------------------------------------------------------------------------
# 预测当事实：将"预计"/"预期"改为"已经"/"实现"
# ---------------------------------------------------------------------------
def _attack_forecast_as_fact(claim: str, **ctx) -> str:
    """预测当事实：将预测语态改为已完成语态。"""
    replacements = [
        ("预计增长", "已经实现增长"),
        ("预期增长", "已经实现增长"),
        ("预计将增长", "已经实现增长"),
        ("有望增长", "已经实现增长"),
        ("预计", "已经实现"),
        ("预期", "已经实现"),
        ("将增长", "已增长"),
    ]
    for old, new in replacements:
        if old in claim:
            return claim.replace(old, new, 1)
    return claim


# ---------------------------------------------------------------------------
# 攻击函数注册表
# ---------------------------------------------------------------------------
_ATTACK_FUNCS = {
    ATTACK_NUMERIC_HALLUCINATION: _attack_numeric,
    ATTACK_PERIOD_CONFUSION: _attack_period,
    ATTACK_GROWTH_ERROR: _attack_growth,
    ATTACK_UNSUPPORTED_STRATEGIC: _attack_strategic,
    ATTACK_FORECAST_AS_FACT: _attack_forecast_as_fact,
}


# ---------------------------------------------------------------------------
# 单条攻击生成
# ---------------------------------------------------------------------------
def generate_attack(
    original_claim: str,
    attack_type: str,
    company: str = "",
    stock_code: str = "",
    case_id: str | None = None,
) -> AttackCase:
    """生成单条攻击案例。

    Args:
        original_claim: 真实主张文本
        attack_type: 攻击类型（ATTACK_TYPES）
        company: 关联公司
        stock_code: 股票代码
        case_id: 案例ID，若 None 自动生成

    Returns:
        AttackCase
    """
    if attack_type not in _ATTACK_FUNCS:
        raise ValueError(f"未知攻击类型: {attack_type}")

    attacked_claim = _ATTACK_FUNCS[attack_type](original_claim)

    # 提取数值/期间元数据
    original_value = _extract_number(original_claim)
    attacked_value = _extract_number(attacked_claim)
    period_original = _extract_period(original_claim)
    period_attacked = _extract_period(attacked_claim)
    metric = _extract_metric(original_claim)

    if case_id is None:
        case_id = f"ATC-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:16]}"

    return AttackCase(
        case_id=case_id,
        original_claim=original_claim,
        attacked_claim=attacked_claim,
        attack_type=attack_type,
        expected_risk=EXPECTED_RISK.get(attack_type, 60.0),
        company=company,
        stock_code=stock_code,
        metric=metric,
        original_value=original_value,
        attacked_value=attacked_value,
        period_original=period_original,
        period_attacked=period_attacked,
    )


# ---------------------------------------------------------------------------
# 批量攻击生成（任务书 §4：一次运行100条AI生成金融观点）
# ---------------------------------------------------------------------------
def generate_attacks(
    base_claims: list[dict],
    count_per_type: int = 20,
    seed: int = 42,
) -> list[AttackCase]:
    """批量生成攻击案例。

    Args:
        base_claims: 基础主张列表，每项 {"text", "company", "stock_code", "attack_types"}
        count_per_type: 每种攻击类型生成多少条
        seed: 随机种子（可复现）

    Returns:
        list[AttackCase]
    """
    rng = random.Random(seed)
    random.seed(seed)
    cases: list[AttackCase] = []
    case_counter = 0

    for base in base_claims:
        text = base.get("text", "")
        company = base.get("company", "")
        stock_code = base.get("stock_code", "")
        attack_types = base.get("attack_types", list(ATTACK_TYPES))

        for atk_type in attack_types:
            for _ in range(count_per_type):
                case_counter += 1
                case_id = f"ATC-{case_counter:05d}"
                try:
                    case = generate_attack(
                        original_claim=text,
                        attack_type=atk_type,
                        company=company,
                        stock_code=stock_code,
                        case_id=case_id,
                    )
                    cases.append(case)
                except Exception:  # noqa: BLE001
                    continue

    return cases


# ---------------------------------------------------------------------------
# 攻击分布统计
# ---------------------------------------------------------------------------
def attack_distribution(cases: list[AttackCase]) -> dict[str, int]:
    """统计攻击类型分布。"""
    dist: dict[str, int] = {}
    for c in cases:
        dist[c.attack_type] = dist.get(c.attack_type, 0) + 1
    return dist


# ---------------------------------------------------------------------------
# 内部：从文本提取数值/期间/指标
# ---------------------------------------------------------------------------
def _extract_number(text: str) -> float | None:
    match = re.search(r"(\d+\.?\d*)\s*亿", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    match = re.search(r"(\d+\.?\d*)\s*%", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    match = re.search(r"(\d+\.?\d*)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _extract_period(text: str) -> str:
    match = re.search(r"(2024|2025)(H1|Q1|Q2|Q3|Q4)", text)
    if match:
        return match.group(0)
    return ""


def _extract_metric(text: str) -> str:
    metrics = ["净利润", "营业收入", "毛利率", "海外收入", "营收", "海外业务"]
    for m in metrics:
        if m in text:
            return m
    return ""


__all__ = [
    "EXPECTED_RISK",
    "generate_attack",
    "generate_attacks",
    "attack_distribution",
]
