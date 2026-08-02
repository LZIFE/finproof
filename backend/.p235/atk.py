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