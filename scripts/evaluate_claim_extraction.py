#!/usr/bin/env python3
"""主张提取评测（Phase 3）。

用法：
  backend/.venv/bin/python scripts/evaluate_claim_extraction.py \
      [--run-id <run_id>] [--document-id <id>] [--mode mock] [--force]

行为：
- 未指定 run-id 时取该文档最新 COMPLETED 运行；无运行或 --force 时先执行一次提取
- 系统主张与 data/demo/annotations/gold_claims.json 匹配并计算指标
- 产物写入 artifacts/evaluations/claim_extraction/<run_id>/（metrics.json /
  matched_claims.json / missed_gold_claims.json / unmatched_system_claims.json /
  ambiguous_matches.json / report.md）
- 明确区分 Mock / 规则 / LLM 结果（metrics.json 中记录 mode/provider/model）
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import json  # noqa: E402

from app.core.logging import setup_logging  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Claim, ExtractionRun  # noqa: E402
from app.services import claim_service  # noqa: E402
from app.services.evaluation import claim_eval  # noqa: E402

setup_logging()

GOLD_PATH = REPO_ROOT / "data" / "demo" / "annotations" / "gold_claims.json"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "evaluations" / "claim_extraction"


def load_gold() -> list[dict]:
    data = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    return data["claims"]


def main() -> int:
    ap = argparse.ArgumentParser(description="主张提取评测")
    ap.add_argument("--document-id", type=int, default=None, help="待核验文档 id（默认查询 REPORT_TO_VERIFY）")
    ap.add_argument("--run-id", type=int, default=None, help="指定提取运行 id")
    ap.add_argument("--mode", default="mock", choices=["mock", "rules", "llm"])
    ap.add_argument("--force", action="store_true", help="强制新建提取运行")
    args = ap.parse_args()

    init_db()
    with SessionLocal() as session:
        if args.run_id is None:
            if args.document_id is None:
                from app.models import Document

                doc = (
                    session.query(Document)
                    .filter(Document.document_role == "REPORT_TO_VERIFY")
                    .first()
                )
                if doc is None:
                    print("[错误] 未找到 REPORT_TO_VERIFY 文档，请先导入演示数据")
                    return 1
                document_id = doc.id
            else:
                document_id = args.document_id
            run = (
                session.query(ExtractionRun)
                .filter(ExtractionRun.document_id == document_id)
                .order_by(ExtractionRun.id.desc())
                .first()
            )
            if run is None or args.force:
                run, _ = claim_service.run_claim_extraction(
                    session, document_id, mode=args.mode, force=args.force
                )
        else:
            run = claim_service.get_run_or_404(session, args.run_id)
            document_id = run.document_id

        rows = (
            session.query(Claim)
            .filter(Claim.extraction_run_id == run.id)
            .order_by(Claim.id)
            .all()
        )
        system_claims = [
            {
                "id": c.id,
                "claim_uid": c.claim_uid,
                "source_text": c.source_text,
                "normalized_claim": c.normalized_claim,
                "parent_sentence_text": c.parent_sentence_text,
                "claim_type": c.claim_type,
                "metric": c.metric,
                "metric_code": c.metric_code,
                "reported_value": c.reported_value,
                "unit": c.unit,
                "period": c.period,
                "comparison_period": c.comparison_period,
                "claim_nature": c.claim_nature,
                "entity_name": c.entity_name,
                "risk_level": c.risk_level,
            }
            for c in rows
        ]
        run_dict = {
            "id": run.id,
            "mode": run.mode,
            "provider": run.provider,
            "model_name": run.model_name,
            "prompt_version": run.prompt_version,
            "candidate_claim_count": run.candidate_claim_count,
            "schema_valid_count": run.schema_valid_count,
            "duplicate_removed_count": run.duplicate_removed_count,
        }

    gold = load_gold()
    result = claim_eval.match_claims(system_claims, gold)
    metrics = claim_eval.compute_metrics(run_dict, result, gold, system_claims)
    report_md = claim_eval.build_report(metrics, result, gold)
    out_dir = ARTIFACT_ROOT / str(run.id)
    claim_eval.write_artifacts(out_dir, metrics, result, report_md)

    # 去重分析产物
    if getattr(run, "dedup_analysis_json", None):
        (out_dir / "dedup_analysis.json").write_text(run.dedup_analysis_json, encoding="utf-8")
        print(f"去重分析产物: {out_dir / 'dedup_analysis.json'}")

    print(f"== 评测完成 run_id={run.id} ==")
    print(f"模式={metrics['mode']} provider={metrics['provider']} model={metrics.get('model_name') or '无(Mock)'} prompt={metrics['prompt_version']}")
    print(f"系统主张 {metrics['system_claim_count']} | 金标准 {metrics['gold_claim_count']} | 匹配 {metrics['matched_count']} | 遗漏 {metrics['missed_gold_count']} | 无效 {metrics['unmatched_system_count']} | 歧义 {metrics['ambiguous_count']}")
    print(f"Precision={metrics['precision']} Recall={metrics['recall']} F1={metrics['f1']}")
    print(f"高风险召回={metrics['high_risk_recall']} 数字召回={metrics['numeric_claim_recall']} 语义召回={metrics['semantic_claim_recall']}")
    print(f"数值准确={metrics['exact_value_accuracy']} 期间准确={metrics['period_accuracy']} 指标准确={metrics['metric_accuracy']}")
    print(f"Schema合法率={metrics['schema_validity_rate']} 重复率={metrics['duplicate_rate']} 无效提取率={metrics['unsupported_extraction_rate']}")
    print(f"产物目录: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
