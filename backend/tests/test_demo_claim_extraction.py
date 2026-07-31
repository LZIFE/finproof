"""Phase 3 集成测试：ai_report_with_errors.md 全链路（注册→提取→入库→API→评测）。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import create_app
from app.models import Claim, Document
from app.services import claim_service as csvc
from app.services import document_service as dsvc
from app.services.evaluation import claim_eval

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "data" / "demo" / "reports" / "ai_report_with_errors.md"
GOLD_PATH = REPO_ROOT / "data" / "demo" / "annotations" / "gold_claims.json"


@pytest.fixture()
def report_doc_id():
    data = REPORT_PATH.read_bytes()
    with SessionLocal() as s:
        doc, _ = dsvc.register_document(
            s, filename=REPORT_PATH.name, data=data,
            document_role="REPORT_TO_VERIFY", company_name="美的集团",
            stock_code="000333", report_period="2025FY",
        )
        return doc.id


def test_full_pipeline_extraction(report_doc_id):
    """能够创建提取运行、读取文本块、主张可追溯、结果入库。"""
    with SessionLocal() as s:
        run, created = csvc.run_claim_extraction(s, report_doc_id, mode="mock", force=False)
        assert created and run.status == "COMPLETED"
        assert run.extracted_claim_count > 20
        claims = s.query(Claim).filter(Claim.extraction_run_id == run.id).all()
        assert len(claims) == run.extracted_claim_count
        assert all(c.source_block_id is not None for c in claims)  # 每条主张可追溯到原始块
        assert all(c.document_id == report_doc_id for c in claims)
        assert run.schema_valid_count >= run.extracted_claim_count


def test_claims_via_api(report_doc_id):
    """API 能返回主张列表与详情。"""
    with TestClient(create_app()) as client:
        r = client.post(
            f"/api/v1/documents/{report_doc_id}/claim-extractions",
            json={"mode": "mock", "force": False},
        )
        assert r.status_code == 201
        assert r.json()["status"] == "COMPLETED"
        r2 = client.get(f"/api/v1/documents/{report_doc_id}/claims?page_size=100")
        assert r2.status_code == 200
        assert r2.json()["total"] > 20
        claim = r2.json()["claims"][0]
        r3 = client.get(f"/api/v1/claims/{claim['id']}")
        assert r3.status_code == 200
        assert r3.json()["source_block_id"] is not None
        assert r3.json()["source_text"]


def test_evaluation_runs_on_real_data(report_doc_id, tmp_path):
    """评测脚本（模块级）能在真实提取结果上运行并生成产物。"""
    with SessionLocal() as s:
        run, _ = csvc.run_claim_extraction(s, report_doc_id, mode="mock", force=True)
        claims = s.query(Claim).filter(Claim.extraction_run_id == run.id).all()
        system = [
            {
                "id": c.id,
                "source_text": c.source_text,
                "claim_type": c.claim_type,
                "metric": c.metric,
                "metric_code": c.metric_code,
                "reported_value": c.reported_value,
                "period": c.period,
            }
            for c in claims
        ]
        run_dict = {
            "id": run.id, "mode": "mock", "provider": "mock", "model_name": None,
            "prompt_version": "v1", "candidate_claim_count": run.candidate_claim_count,
            "schema_valid_count": run.schema_valid_count,
            "duplicate_removed_count": run.duplicate_removed_count,
        }
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))["claims"]
    result = claim_eval.match_claims(system, gold)
    metrics = claim_eval.compute_metrics(run_dict, result, gold, system)
    assert metrics["recall"] >= 0.5
    assert metrics["schema_validity_rate"] == 1.0
    report = claim_eval.build_report(metrics, result, gold)
    claim_eval.write_artifacts(tmp_path, metrics, result, report)
    assert (tmp_path / "metrics.json").exists()
    assert (tmp_path / "matched_claims.json").exists()
    assert (tmp_path / "missed_gold_claims.json").exists()
    assert (tmp_path / "report.md").exists()


def test_mock_distinct_from_llm(report_doc_id):
    """Mock 结果与 LLM 结果严格区分（is_mock / extraction_method）。"""
    import json as _json

    from app.services.claim_service import _get_document_blocks, _report_year_of
    from app.services.claims.providers import (
        DocumentContext,
        LLMClaimExtractionProvider,
        MockClaimExtractionProvider,
    )

    with SessionLocal() as s:
        doc = s.get(Document, report_doc_id)
        blocks = _get_document_blocks(s, report_doc_id)
        ctx = DocumentContext(
            document_id=report_doc_id, company_name=doc.company_name,
            stock_code=doc.stock_code, report_year=_report_year_of(doc),
            prompt_version="v1",
        )

    mock_res = MockClaimExtractionProvider().extract_claims(ctx, blocks)
    assert mock_res.is_mock is True
    assert mock_res.provider == "mock"
    assert all(d["extraction_method"] == "MOCK" for d in mock_res.claim_dicts)

    llm = LLMClaimExtractionProvider()

    def fake_call(messages):
        return _json.dumps({"claims": []}), None

    llm._call_model = fake_call  # type: ignore[method-assign]
    llm_res = llm.extract_claims(ctx, blocks)
    assert llm_res.is_mock is False
    assert llm_res.provider == "openai_compatible"
