"""Phase 23.11.6.2.1 — Prompt Pack 完整性冻结测试

覆盖：
- EVD-002 Block ID 一致性（含 block 4442，4442 是真正正文所在）
- Prompt Block 真实存在于 document_blocks
- reconstructed_text 来源可追踪（每个 Bundle 的 source_block_ids 对应 document_blocks.text 片段）
- STILL_NOT_FOUND 使用 Source Recovery Schema（不允许 MATCH_SINGLE_BLOCK/MATCH_MULTIPLE_BLOCKS）
- Prompt 无 Verdict 值泄漏
- Candidate Bundle 去重（无 reconstructed_text 完全相同的 Bundle）
- 导出文件与原文件 hash 一致

Run: cd backend && PYTHONPATH=. pytest tests/test_phase23_11_6_2_1_prompt_pack_freeze.py -v
"""
from __future__ import annotations

import glob
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

REBUILT_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "review_items_rebuilt.json"
NF_RECOVERY_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_not_found_recovery.json"
EVD002_AUDIT_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_1_evd002_block_audit.json"
PROMPT_INTEGRITY_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_1_prompt_integrity.json"
BUNDLE_DEDUP_PATH = BACKEND / "artifacts" / "gold_contract" / "phase23_11_6_2_1_bundle_dedup_audit.json"
DB_PATH = REPO_ROOT / "data" / "finproof.db"
PROMPT_PACK_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack"
EXPORT_DIR = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "export_for_user"
INDEX_PATH = REPO_ROOT / "data" / "gold_review" / "phase23_11_6_2" / "prompt_pack_index.md"


@pytest.fixture(scope="module")
def rebuilt_items() -> list[dict]:
    return json.loads(REBUILT_PATH.read_text(encoding="utf-8"))["items"]


@pytest.fixture(scope="module")
def nf_recovery() -> dict:
    return json.loads(NF_RECOVERY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def evd002_audit() -> dict:
    return json.loads(EVD002_AUDIT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prompt_integrity() -> dict:
    return json.loads(PROMPT_INTEGRITY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bundle_dedup() -> dict:
    return json.loads(BUNDLE_DEDUP_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 1. EVD-002 Block ID 一致性
# --------------------------------------------------------------------------


def test_evd002_contains_block_4442(rebuilt_items: list[dict]):
    """EVD-002 的候选 Bundle 必须含 block 4442（真正含营业总收入行 + 两个数字的正文所在）。"""
    evd002 = next(it for it in rebuilt_items if it["item_id"] == "EVD-002")
    all_bids: set[str] = set()
    for b in evd002.get("candidate_bundles", []):
        for bid in b.get("source_block_ids", []):
            all_bids.add(str(bid))
    assert "4442" in all_bids, f"EVD-002 候选 Bundle 必须含 block 4442，实际：{sorted(all_bids)}"


def test_evd002_block_4442_contains_revenue_numbers(evd002_audit: dict):
    """block 4442 应含营业总收入 + 458,502,407 + 409,084,266。"""
    blocks = evd002_audit["blocks_audit"]
    b4442 = next(b for b in blocks if b["block_id"] == 4442)
    kw = b4442["contains_keywords"]
    assert kw["营业总收入"] is True
    assert kw["458,502,407"] is True
    assert kw["409,084,266"] is True


def test_evd002_block_4443_is_different_row(evd002_audit: dict):
    """block 4443 应不含营业总收入行（它是 4442 下方相邻的利润表后续行项）。"""
    blocks = evd002_audit["blocks_audit"]
    b4443 = next(b for b in blocks if b["block_id"] == 4443)
    kw = b4443["contains_keywords"]
    # 4443 含 456,451,731（营业收入细分），但不含营业总收入行
    assert kw["营业总收入"] is False, "block 4443 不应含营业总收入行"
    assert kw["458,502,407"] is False, "block 4443 不应含营业总收入数字 458,502,407"


def test_evd002_no_block_index_id_confusion(evd002_audit: dict):
    """不存在 block_index 与数据库 id 混淆。"""
    j = evd002_audit["judgement"]
    assert j["block_id_index_confusion"] is False
    assert j["block_id_drift"] is False


# --------------------------------------------------------------------------
# 2. Prompt Block 真实存在 + 3. reconstructed_text 来源可追踪
# --------------------------------------------------------------------------


def test_all_bundle_blocks_exist_in_document_blocks(rebuilt_items: list[dict]):
    """每个 Bundle 的 source_block_ids 真实存在于 document_blocks 表。"""
    conn = sqlite3.connect(DB_PATH)
    all_bids = set()
    for it in rebuilt_items:
        for b in it.get("candidate_bundles", []):
            for bid in b.get("source_block_ids", []):
                all_bids.add(int(bid))
    placeholders = ",".join(["?"] * len(all_bids))
    rows = conn.execute(
        f"SELECT id FROM document_blocks WHERE id IN ({placeholders})", list(all_bids)
    ).fetchall()
    found = {r[0] for r in rows}
    conn.close()
    missing = all_bids - found
    assert not missing, f"Bundle 引用了不存在的 block_id：{sorted(missing)}"


def test_reconstructed_text_traceable_to_block_text(rebuilt_items: list[dict]):
    """每个 Bundle 的 reconstructed_text 应由其 source_block_ids 的 document_blocks.text 片段组成。

    检查方式：reconstructed_text 的非空行应能在某个 block 的 text 里找到。
    （允许 PyMuPDF 提取的正文与 db.text 有空白/换行差异，这里做字符级 Jaccard >= 0.5 检查）
    """
    conn = sqlite3.connect(DB_PATH)
    # 缓存 block.text
    bid_to_text: dict[int, str] = {}
    for it in rebuilt_items:
        for b in it.get("candidate_bundles", []):
            for bid in b.get("source_block_ids", []):
                bid_int = int(bid)
                if bid_int not in bid_to_text:
                    row = conn.execute(
                        "SELECT text FROM document_blocks WHERE id=?", (bid_int,)
                    ).fetchone()
                    bid_to_text[bid_int] = row[0] if row else ""
    conn.close()

    for it in rebuilt_items:
        for b in it.get("candidate_bundles", []):
            recon = (b.get("reconstructed_text") or "").strip()
            if not recon:
                continue
            bids = b.get("source_block_ids", [])
            # 拼 source block 的 db.text
            src_text = "\n".join((bid_to_text.get(int(bid), "") or "") for bid in bids).strip()
            if not src_text:
                continue
            # 字符级 Jaccard
            recon_chars = set(recon)
            src_chars = set(src_text)
            if not recon_chars or not src_chars:
                continue
            jaccard = len(recon_chars & src_chars) / len(recon_chars | src_chars)
            assert jaccard >= 0.5, (
                f"{it['item_id']} {b.get('candidate_group_id')}: "
                f"reconstructed_text 与 source block db.text 不一致 (jaccard={jaccard:.3f})"
            )


# --------------------------------------------------------------------------
# 4. STILL_NOT_FOUND 使用 Source Recovery Schema
# --------------------------------------------------------------------------


def test_still_not_found_prompts_use_source_recovery_schema(nf_recovery: dict):
    """4 条 STILL_NOT_FOUND 的 Prompt 必须含 SOURCE_RECOVERY_SCHEMA，
    不允许 MATCH_SINGLE_BLOCK / MATCH_MULTIPLE_BLOCKS 作为 decision 选项。
    """
    still_not_found_ids = [
        it["gold_evidence_id"] for it in nf_recovery["per_item"]
        if it["recovery_status"] == "STILL_NOT_FOUND"
    ]
    assert len(still_not_found_ids) == 4
    # 找对应的 prompt 文件
    for iid in still_not_found_ids:
        matches = list(PROMPT_PACK_DIR.glob(f"*_{iid}.md"))
        assert matches, f"{iid} 的 Prompt 文件不存在"
        content = matches[0].read_text(encoding="utf-8")
        # 必须含 Source Recovery Schema 关键字段
        assert "SOURCE_TEXT_LOCATED" in content, f"{iid} Prompt 缺 SOURCE_TEXT_LOCATED decision"
        assert "WRONG_PAGE" in content, f"{iid} Prompt 缺 WRONG_PAGE decision"
        assert "WRONG_DOCUMENT" in content, f"{iid} Prompt 缺 WRONG_DOCUMENT decision"
        # 必须含"不得强行选择 Block"约束
        assert "不得强行选择 Block" in content or "selected_block_ids 必须为空" in content, (
            f"{iid} Prompt 缺'不得强行选择 Block'约束"
        )


def test_paraphrase_prompts_use_paraphrase_review_schema(nf_recovery: dict):
    """6 条 PARAPHRASED_SOURCE_LOCATED 的 Prompt 必须含 Paraphrase Review Schema。"""
    paraphrase_ids = [
        it["gold_evidence_id"] for it in nf_recovery["per_item"]
        if it["recovery_status"] == "PARAPHRASED_SOURCE_LOCATED"
    ]
    assert len(paraphrase_ids) == 6
    for iid in paraphrase_ids:
        matches = list(PROMPT_PACK_DIR.glob(f"*_{iid}.md"))
        assert matches, f"{iid} 的 Prompt 文件不存在"
        content = matches[0].read_text(encoding="utf-8")
        assert "POSSIBLE_PARAPHRASE" in content, f"{iid} Prompt 缺 POSSIBLE_PARAPHRASE decision"
        assert "不得自动进入 Gold" in content, f"{iid} Prompt 缺'不得自动进入 Gold'约束"


def test_not_found_prompts_not_packaged_as_match(nf_recovery: dict):
    """NOT_FOUND 10 条的 Prompt 不应把 MATCH_SINGLE_BLOCK/MATCH_MULTIPLE_BLOCKS 作为 decision 选项。"""
    nf_ids = [it["gold_evidence_id"] for it in nf_recovery["per_item"]]
    for iid in nf_ids:
        matches = list(PROMPT_PACK_DIR.glob(f"*_{iid}.md"))
        assert matches, f"{iid} 的 Prompt 文件不存在"
        content = matches[0].read_text(encoding="utf-8")
        # Schema 的 decision 行不应含 MATCH_SINGLE_BLOCK / MATCH_MULTIPLE_BLOCKS
        # 找 decision 字段定义
        # 允许 MATCH_SINGLE_BLOCK 出现在"不允许"等否定语境，但 Schema 的 decision 枚举不应含
        # 简化：检查"decision": "MATCH_SINGLE_BLOCK" 这种 JSON Schema 枚举不应出现
        assert '"decision": "MATCH_SINGLE_BLOCK' not in content, (
            f"{iid} Prompt Schema 不应含 MATCH_SINGLE_BLOCK decision"
        )
        assert '"decision": "MATCH_MULTIPLE_BLOCKS' not in content, (
            f"{iid} Prompt Schema 不应含 MATCH_MULTIPLE_BLOCKS decision"
        )


# --------------------------------------------------------------------------
# 5. Prompt 无 Verdict 值泄漏
# --------------------------------------------------------------------------


LEAK_VERDICT_VALUES = ["SUPPORTED", "REFUTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "is_gold"]


def test_all_prompts_no_verdict_value_leak():
    """所有 42 个 Prompt 文件不含 verdict 值泄漏。"""
    files = list(PROMPT_PACK_DIR.glob("*.md"))
    assert len(files) == 42, f"expected 42 prompt files (32 + 10), got {len(files)}"
    for f in files:
        content = f.read_text(encoding="utf-8")
        for leak in LEAK_VERDICT_VALUES:
            assert leak not in content, f"{f.name} leaks verdict value '{leak}'"


# --------------------------------------------------------------------------
# 6. Candidate Bundle 去重
# --------------------------------------------------------------------------


def test_no_duplicate_bundles_in_rebuilt(rebuilt_items: list[dict]):
    """rebuilt 文件中每条 Evidence 的 Bundle 不应有 reconstructed_text 完全相同的重复。"""
    for it in rebuilt_items:
        bundles = it.get("candidate_bundles", [])
        recon_hashes = []
        for b in bundles:
            recon = (b.get("reconstructed_text") or "").strip()
            h = hashlib.sha256(recon.encode("utf-8")).hexdigest()
            recon_hashes.append(h)
        assert len(recon_hashes) == len(set(recon_hashes)), (
            f"{it['item_id']} 存在 reconstructed_text 完全相同的重复 Bundle"
        )


def test_bundle_dedup_audit_consistent(bundle_dedup: dict, rebuilt_items: list[dict]):
    """去重审计结果与 rebuilt 文件实际 Bundle 数量一致。"""
    actual_total = sum(len(it.get("candidate_bundles", [])) for it in rebuilt_items)
    assert bundle_dedup["total_bundles_after_dedup"] == actual_total, (
        f"dedup audit after={bundle_dedup['total_bundles_after_dedup']} "
        f"vs rebuilt actual={actual_total}"
    )
    # 去重后应为 159（原 160 - 1 EVD-022 重复）
    assert actual_total == 159, f"去重后 Bundle 总数应为 159，实际 {actual_total}"


# --------------------------------------------------------------------------
# 7. 导出文件与原文件 hash 一致
# --------------------------------------------------------------------------


def test_exported_files_hash_identical():
    """export_for_user/ 下的 001/002 文件 hash 与 prompt_pack/ 原文件一致。"""
    for iid in ("001_EVD-001", "002_EVD-002"):
        src = PROMPT_PACK_DIR / f"{iid}.md"
        exp = EXPORT_DIR / f"{iid}.md"
        assert src.exists() and exp.exists(), f"{iid}.md 不存在"
        src_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        exp_hash = hashlib.sha256(exp.read_bytes()).hexdigest()
        assert src_hash == exp_hash, f"{iid}.md hash 不一致：src={src_hash} exp={exp_hash}"


# --------------------------------------------------------------------------
# 8. Prompt Integrity 全 PASS
# --------------------------------------------------------------------------


def test_prompt_integrity_all_pass(prompt_integrity: dict):
    """32 条 Evidence Alignment 的 Prompt 完整性校验全部 PASS。"""
    assert prompt_integrity["total_files"] == 32
    assert prompt_integrity["pass_count"] == 32
    assert prompt_integrity["fail_count"] == 0


# --------------------------------------------------------------------------
# 9. 浏览索引分类正确
# --------------------------------------------------------------------------


def test_index_classification_correct():
    """prompt_pack_index.md 应含 4 种状态分类，且 SOURCE_RECOVERY_REQUIRED 4 条 + READY_FOR_PARAPHRASE_REVIEW 6 条。"""
    content = INDEX_PATH.read_text(encoding="utf-8")
    assert "READY_FOR_EVIDENCE_ALIGNMENT" in content
    assert "READY_FOR_PARAPHRASE_REVIEW" in content
    assert "SOURCE_RECOVERY_REQUIRED" in content
    assert "PROMPT_INTEGRITY_FAILED" in content
    # 6 条 paraphrase + 4 条 source recovery 应在 index 里出现
    assert "EVD-011" in content  # paraphrase
    assert "EVD-029" in content  # source recovery


# --------------------------------------------------------------------------
# 10. EVD-002 审计结论正确
# --------------------------------------------------------------------------


def test_evd002_audit_conclusion_correct(evd002_audit: dict):
    """EVD-002 审计结论应明确 4442 是真正正文所在，4443 是相邻行项。"""
    j = evd002_audit["judgement"]
    # block_4442_role 字段描述里含营业总收入 + 数字（不要求含"4442"字面词，因 role 描述的是语义）
    assert "营业总收入" in j["block_4442_role"]
    assert "458,502,407" in j["block_4442_role"]
    # block_4443_role 应明确是相邻行项的角色（描述里含"下方相邻"+"营业收入细分"等语义）
    assert "下方相邻" in j["block_4443_role"] or "相邻" in j["block_4443_role"]
    assert "营业收入细分" in j["block_4443_role"] or "非营业总收入" in j["block_4443_role"]
    assert j["same_table"] is True
    assert j["same_page"] is True
    assert "无需修改 EVD-002 Prompt" in j["action_required"]
