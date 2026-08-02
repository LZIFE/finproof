"""Phase 14 · Demo — FinProof Red Team & Financial AI Reliability Lab。

任务书 §7 Demo 要求：
- 案例：AI 生成美的投资报告，包含：
  1. 错误利润增长率
  2. 虚假海外利润贡献
  3. 预测当事实

流程：
  生成攻击（5 类金融 AI 错误）
    ↓ Hallucination Detector
  FinProof 检测（Evidence First）
    ↓ Risk 评分
  生成可靠性报告（FinProof Reliability Score）

运行：
    cd backend
    python -m scripts.phase14_demo
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
from app.models.red_team import (  # noqa: E402
    RedTeamCaseRow,
    RedTeamResultRow,
    RedTeamRunRow,
)
from app.services.red_team import (  # noqa: E402
    attack_distribution,
    detect_hallucination,
    generate_attack,
    generate_attacks,
    run_stress_test,
)
from app.services.red_team.schemas import (  # noqa: E402
    ATTACK_FORECAST_AS_FACT,
    ATTACK_GROWTH_ERROR,
    ATTACK_NUMERIC_HALLUCINATION,
    ATTACK_PERIOD_CONFUSION,
    ATTACK_UNSUPPORTED_STRATEGIC,
    ATTACK_LABELS,
)


# ---------------------------------------------------------------------------
# Demo 基础主张（任务书 §7：AI 生成美的投资报告）
# ---------------------------------------------------------------------------
DEMO_BASE_CLAIMS = [
    {
        "text": "2024年净利润438亿",
        "company": "美的集团",
        "stock_code": "000333",
        "attack_types": [ATTACK_NUMERIC_HALLUCINATION],
    },
    {
        "text": "2025H1海外收入增长13%",
        "company": "美的集团",
        "stock_code": "000333",
        "attack_types": [ATTACK_PERIOD_CONFUSION, ATTACK_GROWTH_ERROR],
    },
    {
        "text": "预计2025年净利润将增长20%",
        "company": "美的集团",
        "stock_code": "000333",
        "attack_types": [ATTACK_FORECAST_AS_FACT],
    },
    {
        "text": "海外收入增长",
        "company": "美的集团",
        "stock_code": "000333",
        "attack_types": [ATTACK_UNSUPPORTED_STRATEGIC],
    },
]


def _clean(session) -> None:
    """清理旧 demo 数据。"""
    for Row in (RedTeamResultRow, RedTeamCaseRow, RedTeamRunRow):
        session.query(Row).delete()
    session.commit()


def run_demo() -> dict:
    init_db()
    result: dict = {}

    with SessionLocal() as s:
        _clean(s)

        # =======================================================
        # ① 生成攻击（任务书 §7：3 类错误）
        # =======================================================
        print("\n[1/4] Attack Generator：生成金融 AI 常见错误攻击…")
        print("  基础主张（AI 生成美的投资报告）：")
        for bc in DEMO_BASE_CLAIMS:
            types = ", ".join(ATTACK_LABELS.get(t, t) for t in bc["attack_types"])
            print(f"    · {bc['text']}（攻击：{types}）")

        cases = generate_attacks(DEMO_BASE_CLAIMS, count_per_type=5, seed=42)
        dist = attack_distribution(cases)

        print(f"\n  共生成 {len(cases)} 条攻击案例")
        print("  攻击类型分布：")
        for atk, n in dist.items():
            print(f"    · {ATTACK_LABELS.get(atk, atk)}：{n} 条")

        result["attack_generation"] = {
            "total_cases": len(cases),
            "attack_distribution": dist,
        }

        # =======================================================
        # ② Hallucination Detection（Evidence First）
        # =======================================================
        print("\n[2/4] Hallucination Detector：FinProof 检测金融 AI 幻觉…")
        detected_count = 0
        for case in cases[:6]:  # 展示前 6 条
            r = detect_hallucination(case)
            status = "✓ 检测到" if r.detected else "✗ 未检测"
            print(
                f"    · {case.case_id} | {ATTACK_LABELS.get(case.attack_type, case.attack_type)} | "
                f"{status} | {r.error_type} | 风险 {r.risk_score}"
            )
            if r.detected:
                detected_count += 1

        result["detection_sample"] = {
            "shown": 6,
            "detected_in_sample": detected_count,
        }

        # =======================================================
        # ③ 压力测试 + Reliability Score
        # =======================================================
        print("\n[3/4] Stress Testing Engine：运行压力测试 + 计算 Reliability Score…")
        run = run_stress_test(
            s,
            base_claims=DEMO_BASE_CLAIMS,
            count_per_type=5,
            seed=42,
        )

        rs = run.reliability_score
        print(f"\n  Run ID           : {run.run_id}")
        print(f"  Total Cases      : {run.total_cases}")
        print(f"  Detection Acc    : {run.metrics.detection_accuracy}")
        print(f"  Recall           : {run.metrics.recall}")
        print(f"  FinProof Score   : {rs.finproof_score}/100（等级 {rs.grade}）")
        print("  维度得分：")
        for d in rs.dimensions:
            print(f"    · {d.name:<22} {d.score:>6.1f}  (权重 {d.weight})")
        print(f"\n  可靠性摘要：{rs.summary}")

        result["stress_test"] = run.to_dict()

        # =======================================================
        # ④ Demo 案例：3 类错误的具体回放（任务书 §7）
        # =======================================================
        print("\n[4/4] Demo 案例回放（任务书 §7：3 类错误）…")
        demo_cases = [
            ("错误利润增长率", ATTACK_NUMERIC_HALLUCINATION, "2024年净利润438亿"),
            ("虚假海外利润贡献", ATTACK_UNSUPPORTED_STRATEGIC, "海外收入增长"),
            ("预测当事实", ATTACK_FORECAST_AS_FACT, "预计2025年净利润将增长20%"),
        ]
        replays = []
        for label, atk_type, original in demo_cases:
            case = generate_attack(original, atk_type, "美的集团", "000333")
            detection = detect_hallucination(case)
            replay = {
                "error_class": label,
                "attack_type": atk_type,
                "original_claim": case.original_claim,
                "attacked_claim": case.attacked_claim,
                "detected": detection.detected,
                "error_type": detection.error_type,
                "risk_score": detection.risk_score,
            }
            replays.append(replay)
            print(f"\n  ▶ {label}（{ATTACK_LABELS.get(atk_type, atk_type)}）")
            print(f"    原始主张 : {case.original_claim}")
            print(f"    攻击后   : {case.attacked_claim}")
            print(f"    检测     : {'✓ 检测到' if detection.detected else '✗ 未检测'}")
            print(f"    错误类型 : {detection.error_type}")
            print(f"    风险分   : {detection.risk_score}")

        result["demo_replays"] = replays

    return result


def _print_summary(result: dict) -> None:
    print("\n" + "=" * 78)
    print("FinProof Phase 14 · Red Team & Financial AI Reliability Lab — Demo Summary")
    print("=" * 78)

    ag = result["attack_generation"]
    print(f"\n[Attack Generation] 共生成 {ag['total_cases']} 条攻击案例")
    for atk, n in ag["attack_distribution"].items():
        print(f"  · {ATTACK_LABELS.get(atk, atk)}：{n} 条")

    st = result["stress_test"]
    rs = st["reliability_score"]
    print(f"\n[Stress Test] {st['run_id']}")
    print(f"  Total Cases       : {st['total_cases']}")
    print(f"  Detection Accuracy: {st['metrics']['detection_accuracy']}")
    print(f"  Recall            : {st['metrics']['recall']}")
    print(f"  FinProof Score    : {rs['finproof_score']}/100（等级 {rs['grade']}）")

    print("\n[Demo Replays] 3 类错误回放（任务书 §7）")
    for rp in result["demo_replays"]:
        status = "✓" if rp["detected"] else "✗"
        print(f"  {status} {rp['error_class']} → {rp['error_type']}（风险 {rp['risk_score']}）")

    print("\n" + "=" * 78)
    print("Demo 完成：从'检测 AI 错误'升级为'主动测试金融 AI 系统可靠性'。")
    print("约束遵守：不生成投资建议；不自动交易；不修改已有核心验证模块。")
    print("=" * 78)


if __name__ == "__main__":
    _result = run_demo()
    _print_summary(_result)
    print("\n--- JSON Output (excerpt) ---")
    excerpt = {
        "total_cases": _result["stress_test"]["total_cases"],
        "detection_accuracy": _result["stress_test"]["metrics"]["detection_accuracy"],
        "finproof_score": _result["stress_test"]["reliability_score"]["finproof_score"],
        "grade": _result["stress_test"]["reliability_score"]["grade"],
        "attack_distribution": _result["attack_generation"]["attack_distribution"],
        "demo_replays": [
            {"error_class": rp["error_class"], "detected": rp["detected"], "error_type": rp["error_type"]}
            for rp in _result["demo_replays"]
        ],
    }
    print(json.dumps(excerpt, ensure_ascii=False, indent=2))
