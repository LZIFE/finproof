#!/usr/bin/env python3
"""AI 辅助模式导入：将 AI agent（当前模型）生成的 claims JSON 入库为一次 extraction run。

模型输出为真实推理结果（非 Mock、非规则）；model_name 记录实际模型。

用法：
  backend/.venv/bin/python scripts/ai_assisted_extraction.py \\
    --claims artifacts/ai_runs/dev_run1.json --document-id 4 --force

claims JSON 结构：
  {
    "model": "deepseek-v4-flash (AtomCode)",
    "prompt_version": "v2",
    "leakage_risk": "developer-memory (documented)",
    "claims": [ { ...ClaimCreate 兼容字段... } ]
  }
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services import claim_service as csvc  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 辅助主张导入")
    ap.add_argument("--claims", required=True, help="AI 生成的 claims JSON 文件")
    ap.add_argument("--document-id", type=int, required=True, help="REPORT_TO_VERIFY 文档 id")
    ap.add_argument("--force", action="store_true", help="强制新建运行")
    args = ap.parse_args()

    data = json.loads(Path(args.claims).read_text(encoding="utf-8"))
    if not isinstance(data.get("claims"), list) or not data["claims"]:
        print("[错误] claims 必须为非空数组")
        return 1

    init_db()
    with SessionLocal() as s:
        run, created = csvc.run_ai_extraction(
            s,
            args.document_id,
            data["claims"],
            model_name=data.get("model", "ai-agent"),
            prompt_version=data.get("prompt_version", "v2"),
            force=args.force,
        )
        print(
            f"run_id={run.id} mode={run.mode} provider={run.provider} "
            f"model={run.model_name} prompt={run.prompt_version} "
            f"status={run.status} candidates={run.candidate_claim_count} "
            f"saved={run.extracted_claim_count} schema_valid={run.schema_valid_count} "
            f"duplicates={run.duplicate_removed_count} created={created}"
        )
        if run.status == "FAILED":
            print(f"[错误] {run.error_code}: {run.error_message}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
