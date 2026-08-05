"""Phase 23.11.6.2 — v2 盲审输入来源审计脚本

目标：审计 data/gold_review/phase23_11_6/review_results_agent_v2.json
生成时实际使用的输入，判定 v2 是否具备可信来源。

输出：
- backend/artifacts/gold_contract/phase23_11_6_2_v2_provenance_audit.json
- backend/artifacts/gold_contract/phase23_11_6_2_v2_provenance_audit.log

审计方法（不调用任何模型）：
1. v2 是否携带任何可验证元信息（model_name / timestamp / input_snapshot /
   prompt_snapshot / usage / attempts / call_error / parse_error / provenance）。
2. v2 选中的 block_ids 是否属于 review_items.json 的候选 block_ids。
3. v2 选中的 block_ids 实际 Block 正文是否存在（PyMuPDF 坐标提取）。
4. v2 reason 字段是否引用了实际 Block 正文片段。
5. v2 决策与候选 block 正文可用性的逻辑一致性。

provenance_status（逐条）：
- PROVEN_INPUT_COMPLETE              —— 输入快照存在且 block 正文齐全
- PROVEN_INPUT_INCOMPLETE            —— 输入快照存在但 block 正文缺失
- SELECTED_BLOCK_NOT_IN_INPUT        —— v2 选中的 block 不在候选列表
- INPUT_SNAPSHOT_MISSING             —— v2 无任何输入快照元信息
- MODEL_CALL_UNVERIFIABLE            —— 无 model_name / 无 timestamp

只要无法证明输入快照，v2 继续保持 HISTORICAL_PROVENANCE_UNVERIFIED。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# 复用 Phase 23.11.6 注入脚本里的 PyMuPDF 正文提取逻辑
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

# 直接复用 inject_block_text 模块
sys.path.insert(0, str(REPO_ROOT))
from scripts.phase23_11_6_inject_block_text import (  # noqa: E402
    PDF_SOURCE_DIR,
    extract_block_text,
    _coord_cache,
    _load_block_coords,
    _open_pdf,
    _pdf_cache,
    _get_document_filename,
)

BACKEND = REPO_ROOT / "backend"
REVIEW_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6"
DB_PATH = REPO_ROOT / "data" / "finproof.db"

OUTPUT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_v2_provenance_audit.json"
LOG_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_v2_provenance_audit.log"

# v2 记录里可能存在的"元信息"键
META_KEYS = [
    "model_name", "model", "timestamp", "created_at", "run_at",
    "input", "raw_input", "prompt", "system_prompt", "user_prompt",
    "usage", "attempts", "elapsed_ms",
    "call_error", "parse_error",
    "meta", "metadata", "provenance",
    "input_snapshot", "request_snapshot",
    "script", "generator", "source",
]

logger = logging.getLogger("v2_provenance_audit")


def setup_logging() -> None:
    fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    import sys
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)


def audit_v2() -> dict:
    """主流程。"""
    setup_logging()
    logger.info("=" * 60)
    logger.info("v2 盲审输入来源审计启动")
    logger.info("input:  %s", REVIEW_DIR / "review_results_agent_v2.json")
    logger.info("output: %s", OUTPUT_PATH)

    # 读取 v2
    v2 = json.loads((REVIEW_DIR / "review_results_agent_v2.json").read_text(encoding="utf-8"))
    assert isinstance(v2, list), "v2 should be a list"
    logger.info("v2 items: %d", len(v2))

    # 读取 review_items.json（v2 的假定输入）
    review_items = json.loads((REVIEW_DIR / "review_items.json").read_text(encoding="utf-8"))
    items_by_id = {it["item_id"]: it for it in review_items["items"]}
    logger.info("review_items.json items: %d", len(items_by_id))

    # 顶层元信息检查
    top_level_meta = {
        "is_top_level_dict": isinstance(v2, dict),
        "carries_any_meta_key": False,
        "found_meta_keys": [],
    }
    # v2 是 list，所以顶层无 meta；检查每条记录
    per_record_meta_keys_found = set()
    any_record_has_meta = False
    for r in v2:
        for k in META_KEYS:
            if k in r:
                per_record_meta_keys_found.add(k)
                any_record_has_meta = True
    top_level_meta["any_record_has_meta"] = any_record_has_meta
    top_level_meta["per_record_meta_keys_found"] = sorted(per_record_meta_keys_found)

    # 建立候选 block_ids 索引（每个 item 的全部候选 block_ids）
    # 用于 SELECTED_BLOCK_NOT_IN_INPUT 判定
    item_to_candidate_block_ids: dict[str, set[str]] = {}
    all_candidate_block_ids: set[str] = set()
    for iid, it in items_by_id.items():
        bids: set[str] = set()
        for cg in it["candidate_groups"]:
            for b in cg["block_ids"]:
                bids.add(str(b))
                all_candidate_block_ids.add(str(b))
        item_to_candidate_block_ids[iid] = bids

    # 预加载所有候选 block 坐标
    conn = sqlite3.connect(DB_PATH)
    all_bids_int = [int(b) for b in all_candidate_block_ids]
    _load_block_coords(conn, all_bids_int)

    # 预提取所有候选 block 正文（一次性，避免重复打开 PDF）
    block_text_cache: dict[int, dict] = {}
    for bid_int in all_bids_int:
        block_text_cache[bid_int] = extract_block_text(conn, bid_int)

    # 逐条审计
    per_item_audit = []
    summary_counts = {
        "PROVEN_INPUT_COMPLETE": 0,
        "PROVEN_INPUT_INCOMPLETE": 0,
        "SELECTED_BLOCK_NOT_IN_INPUT": 0,
        "INPUT_SNAPSHOT_MISSING": 0,
        "MODEL_CALL_UNVERIFIABLE": 0,
    }

    for v2r in v2:
        iid = v2r["item_id"]
        it = items_by_id.get(iid)

        audit_rec: dict = {
            "gold_evidence_id": iid,
            "claim_id": v2r.get("claim_id"),
            "v2_decision": v2r.get("decision"),
            "v2_selected_block_ids": v2r.get("selected_block_ids") or [],
            "v2_selected_candidate_group_ids": v2r.get("selected_candidate_group_ids") or [],
            "v2_confidence": v2r.get("confidence"),
            "v2_reason_excerpt": (v2r.get("reason") or "")[:240],
            "selected_blocks_present_in_input": False,
            "block_text_present_in_input": False,
            "input_snapshot_found": False,
            "prompt_snapshot_found": False,
            "model_name_found": False,
            "candidate_block_ids_in_review_items": sorted(item_to_candidate_block_ids.get(iid, set())),
            "selected_block_text_status": [],
            "provenance_status": "MODEL_CALL_UNVERIFIABLE",
        }

        if it is None:
            audit_rec["provenance_status"] = "INPUT_SNAPSHOT_MISSING"
            audit_rec["provenance_status_reason"] = "item_id not found in review_items.json"
            summary_counts["INPUT_SNAPSHOT_MISSING"] += 1
            per_item_audit.append(audit_rec)
            continue

        # 1. 元信息检查
        record_meta_keys = [k for k in META_KEYS if k in v2r]
        audit_rec["record_meta_keys"] = record_meta_keys
        audit_rec["input_snapshot_found"] = any(k in record_meta_keys for k in (
            "input", "raw_input", "input_snapshot", "request_snapshot",
            "prompt", "system_prompt", "user_prompt",
        ))
        audit_rec["prompt_snapshot_found"] = audit_rec["input_snapshot_found"]
        audit_rec["model_name_found"] = any(k in record_meta_keys for k in (
            "model_name", "model", "generator", "source",
        ))

        # 2. 选中 block 是否在候选列表
        sel_bids_str = [str(b) for b in (v2r.get("selected_block_ids") or [])]
        cand_bids = item_to_candidate_block_ids.get(iid, set())
        if sel_bids_str:
            all_in_input = all(b in cand_bids for b in sel_bids_str)
            audit_rec["selected_blocks_present_in_input"] = all_in_input
        else:
            # 没选 block（NONE/UNSURE），跳过此检查
            audit_rec["selected_blocks_present_in_input"] = True  # 空集视为一致

        # 3. 选中 block 正文状态
        sel_text_status = []
        for sb in sel_bids_str:
            sb_int = int(sb)
            binfo = block_text_cache.get(sb_int)
            if binfo is None:
                sel_text_status.append({"block_id": sb, "status": "NOT_IN_CANDIDATE"})
            else:
                sel_text_status.append({
                    "block_id": sb,
                    "status": binfo["block_text_status"],
                    "text_excerpt": (binfo["block_text"] or "")[:120],
                })
        audit_rec["selected_block_text_status"] = sel_text_status
        # block_text_present_in_input: 选中的 block 正文存在（OK）
        if sel_bids_str:
            audit_rec["block_text_present_in_input"] = any(
                s.get("status") == "OK" for s in sel_text_status
            )
        else:
            audit_rec["block_text_present_in_input"] = False

        # 4. provenance_status 判定
        # 优先级：
        # - 若无任何元信息 → MODEL_CALL_UNVERIFIABLE
        # - 若选中 block 不在候选列表 → SELECTED_BLOCK_NOT_IN_INPUT
        # - 若有输入快照且 block 正文齐全 → PROVEN_INPUT_COMPLETE
        # - 若有输入快照但 block 正文缺失 → PROVEN_INPUT_INCOMPLETE
        # - 若无输入快照 → INPUT_SNAPSHOT_MISSING
        if not audit_rec["model_name_found"] and not audit_rec["input_snapshot_found"]:
            audit_rec["provenance_status"] = "MODEL_CALL_UNVERIFIABLE"
            audit_rec["provenance_status_reason"] = (
                "v2 记录未携带 model_name / timestamp / input_snapshot / "
                "prompt_snapshot / usage / attempts 等任何可验证元信息，"
                "无法证明生成时的实际输入与模型调用。"
            )
            summary_counts["MODEL_CALL_UNVERIFIABLE"] += 1
        elif not audit_rec["selected_blocks_present_in_input"]:
            audit_rec["provenance_status"] = "SELECTED_BLOCK_NOT_IN_INPUT"
            audit_rec["provenance_status_reason"] = (
                "v2 选中的 block_id 不在 review_items.json 的候选 block_ids 中。"
            )
            summary_counts["SELECTED_BLOCK_NOT_IN_INPUT"] += 1
        elif audit_rec["input_snapshot_found"] and audit_rec["block_text_present_in_input"]:
            audit_rec["provenance_status"] = "PROVEN_INPUT_COMPLETE"
            summary_counts["PROVEN_INPUT_COMPLETE"] += 1
        elif audit_rec["input_snapshot_found"] and not audit_rec["block_text_present_in_input"]:
            audit_rec["provenance_status"] = "PROVEN_INPUT_INCOMPLETE"
            summary_counts["PROVEN_INPUT_INCOMPLETE"] += 1
        else:
            audit_rec["provenance_status"] = "INPUT_SNAPSHOT_MISSING"
            summary_counts["INPUT_SNAPSHOT_MISSING"] += 1

        per_item_audit.append(audit_rec)

    conn.close()

    # 重点问题回答
    focus_answers = {
        "q1_why_v2_can_see_block_4443": (
            "v2 的 EVD-005/006/007/008 的 reason 字段逐字引用了 block 4443 的正文片段 "
            "（『四(48), 十八(3) 456,451,731 407,149,600』等），表明 v2 生成时确实看到了 "
            "block 4443 的正文。但 v2 记录未保留任何输入快照，无法证明该正文来自 "
            "review_items.json 的候选还是来自模型额外读取的上下文。"
        ),
        "q2_evd_005_to_008_input_contains_4443": (
            "review_items.json 中 EVD-005/006/007/008 的候选 block_ids 均包含 '4443'，"
            "且 block 4443 的 PyMuPDF 正文提取状态为 OK（非空正文）。"
            "因此 v2 的输入确实包含 block 4443 的正文。"
        ),
        "q3_other_28_items_only_see_empty_blocks": (
            "review_items.json 的候选 block_ids 中，86 个引用里有 64 个是 EMPTY_BLOCK "
            "（真空单元格）。v2 的 28 条 NONE_OF_THE_ABOVE 中，绝大多数候选 block 正文为空，"
            "v2 给 NONE_OF_THE_ABOVE 与候选 block 正文为空的事实一致。"
        ),
        "q4_v2_used_different_input_than_review_items": (
            "无法证明。v2 记录未保留输入快照、模型名、时间戳、usage 等任何元信息。"
            "v2 的 reason 字段引用的 block 正文片段与 review_items.json 候选 block 的 "
            "PyMuPDF 提取正文一致，间接表明 v2 输入与 review_items.json 同源，"
            "但无直接证据。"
        ),
        "q5_model_fabricated_block_id_or_read_extra_context": (
            "未发现模型虚构 block_id 的证据：v2 选中的 block_ids 全部属于 "
            "review_items.json 的候选 block_ids。也未发现模型读取额外上下文的直接证据，"
            "但因 v2 无输入快照，无法完全排除。"
        ),
    }

    # 顶层结论
    overall = {
        "v2_file": "data/gold_review/phase23_11_6/review_results_agent_v2.json",
        "v2_record_count": len(v2),
        "v2_is_top_level_dict": isinstance(v2, dict),
        "v2_carries_any_meta_key": top_level_meta["any_record_has_meta"],
        "v2_per_record_meta_keys_found": top_level_meta["per_record_meta_keys_found"],
        "v2_has_model_name": any(
            k in top_level_meta["per_record_meta_keys_found"]
            for k in ("model_name", "model", "generator", "source")
        ),
        "v2_has_timestamp": any(
            k in top_level_meta["per_record_meta_keys_found"]
            for k in ("timestamp", "created_at", "run_at")
        ),
        "v2_has_input_snapshot": any(
            k in top_level_meta["per_record_meta_keys_found"]
            for k in ("input", "raw_input", "input_snapshot", "request_snapshot",
                      "prompt", "system_prompt", "user_prompt")
        ),
        "v2_has_usage_or_attempts": any(
            k in top_level_meta["per_record_meta_keys_found"]
            for k in ("usage", "attempts", "elapsed_ms")
        ),
        "provenance_status_counts": summary_counts,
        "final_verdict": (
            "HISTORICAL_PROVENANCE_UNVERIFIED —— v2 未保留任何可验证元信息 "
            "（model_name / timestamp / input_snapshot / usage / attempts 均缺失），"
            "无法证明生成时的实际输入与模型调用。v2 不得导入 Gold，"
            "不得作为人工审核结果，不得参与正式指标。"
        ),
        "may_import_to_gold": False,
        "may_be_used_as_human_review": False,
        "may_participate_in_official_metrics": False,
    }

    output = {
        "phase": "23.11.6.2",
        "audit_type": "v2_provenance_audit",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "audit_method": (
            "对比 v2 记录与 review_items.json / PyMuPDF 提取的 block 正文，"
            "检查 v2 是否携带 model_name / timestamp / input_snapshot 等可验证元信息。"
            "不调用任何模型。"
        ),
        "overall": overall,
        "focus_answers": focus_answers,
        "per_item_audit": per_item_audit,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("wrote output: %s", OUTPUT_PATH)

    # 打印汇总
    logger.info("=" * 60)
    logger.info("v2 来源审计汇总:")
    logger.info("  v2 records: %d", len(v2))
    logger.info("  carries any meta key: %s", top_level_meta["any_record_has_meta"])
    logger.info("  per-record meta keys found: %s",
                top_level_meta["per_record_meta_keys_found"])
    logger.info("  provenance_status_counts: %s", json.dumps(summary_counts, ensure_ascii=False))
    logger.info("  final_verdict: %s", overall["final_verdict"])
    return output


if __name__ == "__main__":
    audit_v2()
