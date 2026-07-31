"""Phase 3.6 专项测试（第二批）：兄弟主张/去重/claim_group/继承/Provider 配置/记录/隔离。"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.services.claims.dedup import deduplicate
from app.services.claims.providers import (
    DocumentContext,
    HybridClaimExtractionProvider,
    LLMClaimExtractionProvider,
    MockClaimExtractionProvider,
    get_claim_provider,
)
from app.services.claims.rule_extractor import RuleBasedCandidateExtractor

from tests.test_phase35 import _block, _extract  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- 兄弟主张与去重 ----------

def test_sibling_absolute_and_growth_not_deduped():
    """同父句"绝对值 + 同比增长率"兄弟主张不被去重。"""
    text = "2025年上半年营业收入为2523.31亿元，同比增长15%。"
    result = _extract(text)
    assert len(result.candidates) == 2
    deduped = deduplicate(result.candidates)
    assert deduped.removed_count == 0  # 兄弟主张不合并
    assert len(deduped.unique) == 2


def test_synonym_absolute_claims_deduped():
    """同义绝对值主张（不同措辞、同指标+期间+数值）正确去重。"""
    a = _extract("2025年上半年营业收入为2523.31亿元。").candidates
    b = _extract("2025H1公司营收达到2523.31亿元。").candidates
    result = deduplicate(a + b)
    assert result.removed_count >= 1
    kept = [c for c in result.unique if c.reported_value == 2523.31]
    assert len(kept) == 1


def test_synonym_growth_claims_deduped():
    """同义增长率主张正确去重。"""
    a = _extract("公司2025年营业收入同比增长15%。").candidates
    b = _extract("2025年公司营收同比增加15%。").candidates
    result = deduplicate(a + b)
    growth = [c for c in result.unique if c.reported_value == 15]
    assert len(growth) <= 1


def test_claim_group_id_generated():
    """同一父句拆分出的子主张共享 claim_group_id，不同句子不同组。"""
    text = "公司2025年实现营业收入4564.52亿元，同比增长12.11%。\n\n归母净利润439.45亿元。"
    result = _extract(text)
    groups = {}
    for c in result.candidates:
        groups.setdefault(c.claim_group_id, []).append(c.metric_code)
    assert len(groups) >= 2  # 两个句子两个组
    s1 = next(g for g, v in groups.items() if "revenue" in v)
    assert any("yoy_growth" in (mc or "") for mc in groups[s1])  # 同组含兄弟


# ---------- 子主张继承 ----------

def test_child_inherits_parent_metric():
    result = _extract("归母净利润439.45亿元，同比增长38.02%。")
    growth = next(c for c in result.candidates if c.reported_value == 38.02)
    assert growth.metric_code == "yoy_growth_net_profit"


def test_child_inherits_parent_period():
    result = _extract("2025年上半年，公司营业总收入2523.31亿元，同比增长15.7%。")
    rev = next(c for c in result.candidates if c.metric_code == "total_operating_revenue")
    assert rev.period == "2025H1"


def test_child_carries_parent_sentence():
    result = _extract("公司2025年实现营业收入4564.52亿元，同比增长12.11%。")
    growth = next(c for c in result.candidates if c.reported_value == 12.11)
    assert growth.parent_sentence_text and "4564.52亿元" in growth.parent_sentence_text
    assert growth.clause_index == 1


# ---------- Provider 配置与记录 ----------

def test_provider_config_missing_fails():
    """真实 Provider 配置缺失时明确失败（Hybrid 前置校验 + LLM 调用失败）。"""
    ctx = DocumentContext(document_id=1, report_year=2025)
    with pytest.raises(AppError) as ei:
        HybridClaimExtractionProvider().extract_claims(ctx, [_block("公司收入100亿元")])
    assert ei.value.code == "LLM_NOT_CONFIGURED"


def test_no_mock_fallback_for_llm_mode():
    """llm 模式不会自动回退 Mock。"""
    provider = get_claim_provider("llm")
    assert not isinstance(provider, MockClaimExtractionProvider)


def test_model_and_prompt_and_token_recorded():
    """Provider 返回的模型名/Prompt 版本/Token 用量被记录。"""
    llm = LLMClaimExtractionProvider()
    calls = {"n": 0}

    def fake_call(messages):
        calls["n"] += 1
        return json.dumps({"claims": []}), {"prompt_tokens": 10, "completion_tokens": 5}

    llm._call_model = fake_call  # type: ignore[method-assign]
    ctx = DocumentContext(document_id=1, report_year=2025, prompt_version="v2")
    cfg = SimpleNamespace(
        claim_extraction_base_url="http://x", claim_extraction_model="test-model",
        claim_extraction_api_key="k", claim_extraction_timeout_seconds=60,
        claim_extraction_max_retries=0, claim_extraction_provider="openai_compatible",
        claim_extraction_prompt_version="v2",
    )
    llm.settings = cfg
    result = llm.extract_claims(ctx, [_block("公司收入100亿元")])
    assert result.model_name == "test-model"
    assert result.prompt_version == "v2"
    assert result.token_usage == {"prompt_tokens": 10, "completion_tokens": 5}


# ---------- 运行隔离与稳定性 ----------

def test_three_runs_isolated():
    """三次运行相互隔离（独立 run id，结果可重复）。"""
    from app.db import SessionLocal
    from app.services import claim_service as csvc
    from app.services import document_service as dsvc

    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s, filename="iso.md", data="# 标题\n\n公司2025年收入100亿元，同比增长10%。".encode(),
            document_role="REPORT_TO_VERIFY", company_name="测试", report_period="2025FY",
        )
        run_ids = set()
        for _ in range(3):
            run, _ = csvc.run_claim_extraction(s, doc.id, mode="mock", force=True)
            run_ids.add(run.id)
        assert len(run_ids) == 3


def test_stability_script_runs():
    """Stability 脚本可运行并生成产物。"""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "compute_stability.py"),
         "--runs", "11", "12"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-500:]
    out = REPO_ROOT / "artifacts" / "evaluations" / "claim_extraction" / "stability"
    assert (out / "stability_metrics.json").exists()
    assert (out / "report.md").exists()


# ---------- 开发集/盲测集隔离与不可覆盖 ----------

def test_dev_holdout_results_isolated():
    """开发集与盲测集评测产物目录隔离。"""
    dev = REPO_ROOT / "artifacts" / "evaluations" / "claim_extraction" / "12"
    hold = REPO_ROOT / "artifacts" / "evaluations" / "holdout" / "15"
    assert dev.exists() and hold.exists()
    dev_m = json.loads((dev / "metrics.json").read_text())
    hold_m = json.loads((hold / "metrics.json").read_text())
    assert dev_m["gold_claim_count"] == 26
    assert hold_m["gold_claim_count"] == 17


def test_first_holdout_result_not_overwritten():
    """盲测首次运行结果已永久保存、可读取（不覆盖策略）。"""
    metrics_path = REPO_ROOT / "artifacts" / "evaluations" / "holdout" / "15" / "metrics.json"
    assert metrics_path.exists()
    m = json.loads(metrics_path.read_text())
    assert m["mode"] == "rules"  # 首次运行模式被记录
    assert m["system_claim_count"] == 20


def test_raw_human_reviewed_isolation_docs():
    """Raw 与 Human-reviewed 分离约定落盘（盲测集 human_review.md 存在并声明）。"""
    doc = REPO_ROOT / "artifacts" / "evaluations" / "holdout" / "human_review.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    assert "Human-reviewed" in text and "严格分离" in text
