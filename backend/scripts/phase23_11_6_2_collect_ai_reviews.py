"""Phase 23.11.6.2 — AI 审核结果收集脚本

用户每完成一条 ChatGPT 审核，把 JSON 结果写入 JSONL。
本脚本校验并收集 AI 审核 JSON 到统一 JSONL 文件。

校验规则：
- Gold Evidence ID 存在（在 review_items_rebuilt.json 中）
- decision 合法（MATCH_SINGLE_BLOCK | MATCH_MULTIPLE_BLOCKS | NONE_OF_THE_ABOVE | UNSURE）
- Block ID 属于该候选
- MATCH_SINGLE_BLOCK 只能选择一个 Block
- MATCH_MULTIPLE_BLOCKS 至少选择两个 Block
- NONE / UNSURE 不能选择 Block
- confidence 范围合法 [0, 1]
- estimated_coverage 范围合法 [0, 1]
- 不重复写入（同一 gold_evidence_id 只能有一条）
- AI 结果不能直接导入 Gold

AI 审核结果状态只能是：
`AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION`

用法：
  cd backend && PYTHONPATH=. python scripts/phase23_11_6_2_collect_ai_reviews.py --input <json_or_jsonl> [--dry-run]

输入可以是单个 JSON 文件、JSONL 文件，或一个 JSON 数组。
每条 JSON 必须包含字段：
  gold_evidence_id, decision, selected_block_ids, selected_candidate_group_ids,
  evidence_complete, confidence, estimated_coverage, reason, ...

输出追加到：
  data/gold_review/phase23_11_6_2/ai_review_results.jsonl

每条写入的记录会附带：
  _meta: {
    collected_at, original_status, validation_status, validation_errors,
    ai_review_status: "AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION",
    may_import_to_gold: false
  }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent

REBUILT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "review_items_rebuilt.json"
JSONL_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "ai_review_results.jsonl"

VALID_DECISIONS = {
    "MATCH_SINGLE_BLOCK",
    "MATCH_MULTIPLE_BLOCKS",
    "NONE_OF_THE_ABOVE",
    "UNSURE",
}
VALID_FIELD_CHECK_VALUES = {"MATCH", "MISMATCH", "UNKNOWN"}
REQUIRED_TOP_KEYS = {
    "gold_evidence_id",
    "decision",
    "selected_block_ids",
    "selected_candidate_group_ids",
    "evidence_complete",
    "confidence",
    "estimated_coverage",
}
AI_REVIEW_STATUS = "AI_REVIEW_SUGGESTION_PENDING_HUMAN_CONFIRMATION"


def load_rebuilt_items() -> dict:
    """加载 rebuilt items，返回 {item_id: {candidate_block_ids: set, candidate_group_ids: set}}"""
    data = json.loads(REBUILT_PATH.read_text(encoding="utf-8"))
    index = {}
    for it in data["items"]:
        bids: set[str] = set()
        gids: set[str] = set()
        for b in it.get("candidate_bundles", []):
            for bid in b.get("source_block_ids", []):
                bids.add(str(bid))
            g = b.get("candidate_group_id")
            if g:
                gids.add(g)
        index[it["item_id"]] = {
            "candidate_block_ids": bids,
            "candidate_group_ids": gids,
        }
    return index


def load_existing_jsonl() -> dict:
    """加载已存在的 JSONL，返回 {gold_evidence_id: record}"""
    existing: dict[str, dict] = {}
    if JSONL_PATH.exists():
        for line in JSONL_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                gid = rec.get("gold_evidence_id")
                if gid:
                    existing[gid] = rec
            except json.JSONDecodeError:
                continue
    return existing


def validate_record(record: dict, rebuilt_index: dict) -> tuple[list[str], dict]:
    """校验单条 AI 审核记录。

    返回 (errors, normalized_record)
    """
    errors: list[str] = []

    # 必填字段存在
    for k in REQUIRED_TOP_KEYS:
        if k not in record:
            errors.append(f"missing required key: {k}")

    gid = record.get("gold_evidence_id")
    if gid is None:
        return errors, record

    # Gold Evidence ID 存在
    if gid not in rebuilt_index:
        errors.append(f"gold_evidence_id '{gid}' not found in review_items_rebuilt.json")
        return errors, record

    cand = rebuilt_index[gid]
    cand_bids = cand["candidate_block_ids"]
    cand_gids = cand["candidate_group_ids"]

    # decision 合法
    decision = record.get("decision")
    if decision not in VALID_DECISIONS:
        errors.append(f"invalid decision '{decision}', must be one of {sorted(VALID_DECISIONS)}")

    # Block ID 属于该候选
    sel_bids = [str(b) for b in (record.get("selected_block_ids") or [])]
    for bid in sel_bids:
        if bid not in cand_bids:
            errors.append(f"selected_block_id '{bid}' not in candidate block ids of {gid}")

    # selected_candidate_group_ids 属于该候选
    sel_gids = [str(g) for g in (record.get("selected_candidate_group_ids") or [])]
    for g in sel_gids:
        if g not in cand_gids:
            errors.append(f"selected_candidate_group_id '{g}' not in candidate group ids of {gid}")

    # decision 与 selected_block_ids 一致性
    if decision == "MATCH_SINGLE_BLOCK":
        if len(sel_bids) != 1:
            errors.append("MATCH_SINGLE_BLOCK must select exactly one block")
    elif decision == "MATCH_MULTIPLE_BLOCKS":
        if len(sel_bids) < 2:
            errors.append("MATCH_MULTIPLE_BLOCKS must select at least two blocks")
    elif decision in ("NONE_OF_THE_ABOVE", "UNSURE"):
        if sel_bids:
            errors.append(f"{decision} must not select any block (got {sel_bids})")

    # confidence 范围 [0, 1]
    conf = record.get("confidence")
    try:
        conf_f = float(conf)
        if conf_f < 0 or conf_f > 1:
            errors.append(f"confidence {conf_f} out of [0, 1]")
    except (TypeError, ValueError):
        errors.append(f"confidence '{conf}' is not a number")

    # estimated_coverage 范围 [0, 1]
    ec = record.get("estimated_coverage")
    try:
        ec_f = float(ec)
        if ec_f < 0 or ec_f > 1:
            errors.append(f"estimated_coverage {ec_f} out of [0, 1]")
    except (TypeError, ValueError):
        errors.append(f"estimated_coverage '{ec}' is not a number")

    # evidence_complete 与 estimated_coverage 一致性
    if ec is not None:
        try:
            ec_f = float(ec)
            if ec_f < 0.95 and record.get("evidence_complete") is True:
                errors.append(
                    f"evidence_complete=true but estimated_coverage={ec_f} < 0.95"
                )
        except (TypeError, ValueError):
            pass

    # field_checks 合法值
    fc = record.get("field_checks") or {}
    for k in ("company", "metric", "period", "value", "unit", "scope", "table_structure"):
        v = fc.get(k)
        if v is not None and v not in VALID_FIELD_CHECK_VALUES:
            errors.append(f"field_checks.{k}='{v}' must be one of {sorted(VALID_FIELD_CHECK_VALUES)}")

    # 标记 AI 结果状态
    record["_meta"] = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "ai_review_status": AI_REVIEW_STATUS,
        "may_import_to_gold": False,
        "validation_status": "VALID" if not errors else "INVALID",
        "validation_errors": errors,
    }

    return errors, record


def collect(input_path: str, dry_run: bool = False) -> dict:
    """主流程：校验并收集 AI 审核记录。"""
    rebuilt_index = load_rebuilt_items()
    existing = load_existing_jsonl()

    # 读取输入
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")

    raw = src.read_text(encoding="utf-8").strip()

    # 解析输入：可能是单条 JSON、JSON 数组、或 JSONL
    records: list[dict] = []
    if raw.startswith("["):
        records = json.loads(raw)
    elif raw.startswith("{"):
        records = [json.loads(raw)]
    else:
        # JSONL：每行一条
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    stats = {
        "input": str(src),
        "total_input_records": len(records),
        "valid": 0,
        "invalid": 0,
        "duplicate_skipped": 0,
        "written": 0,
        "errors": [],
    }

    to_write: list[dict] = []
    for i, rec in enumerate(records):
        errs, normalized = validate_record(rec, rebuilt_index)
        if errs:
            stats["invalid"] += 1
            stats["errors"].append({
                "index": i,
                "gold_evidence_id": rec.get("gold_evidence_id"),
                "errors": errs,
            })
            continue

        gid = normalized.get("gold_evidence_id")
        # 重复检查（已存在 + 本次已加入）
        if gid in existing:
            stats["duplicate_skipped"] += 1
            stats["errors"].append({
                "index": i,
                "gold_evidence_id": gid,
                "errors": [f"duplicate gold_evidence_id '{gid}' already in JSONL"],
            })
            continue
        if any(w.get("gold_evidence_id") == gid for w in to_write):
            stats["duplicate_skipped"] += 1
            stats["errors"].append({
                "index": i,
                "gold_evidence_id": gid,
                "errors": [f"duplicate gold_evidence_id '{gid}' in this input batch"],
            })
            continue

        stats["valid"] += 1
        to_write.append(normalized)
        existing[gid] = normalized  # 防止本批次内重复

    # 写入 JSONL（追加模式）
    if to_write and not dry_run:
        JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(JSONL_PATH, "a", encoding="utf-8") as f:
            for rec in to_write:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        stats["written"] = len(to_write)

    # 如果 JSONL 不存在且 dry_run，初始化空文件
    if dry_run and not JSONL_PATH.exists():
        JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSONL_PATH.write_text("", encoding="utf-8")

    return stats


def init_empty_jsonl() -> None:
    """初始化 ai_review_results.jsonl 为空文件。"""
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not JSONL_PATH.exists() or JSONL_PATH.stat().st_size == 0:
        JSONL_PATH.write_text("", encoding="utf-8")
        print(f"Initialized empty: {JSONL_PATH}")
    else:
        print(f"Already exists (non-empty): {JSONL_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect AI review JSON results into ai_review_results.jsonl"
    )
    parser.add_argument("--input", help="path to JSON / JSONL / JSON array file")
    parser.add_argument("--dry-run", action="store_true", help="validate only, do not write")
    parser.add_argument("--init", action="store_true", help="initialize empty JSONL file")
    args = parser.parse_args()

    if args.init:
        init_empty_jsonl()
        return 0

    if not args.input:
        parser.error("--input is required (or use --init)")

    stats = collect(args.input, dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["invalid"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
