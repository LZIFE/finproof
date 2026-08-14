"""内部自洽核验引擎：同一文档内数字/交叉引用/合计一致性。

纯函数：输入 claim + 文档块列表，输出 VerificationOutcome。
"""

from __future__ import annotations

import re

from app.services.generic_verification.claim_extraction import (
    extract_cross_refs,
    extract_numbers,
)
from app.services.generic_verification.schemas import GenericClaim, VerificationOutcome
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)

VALUE_TOLERANCE = 0.01  # 相对误差 1%

# 单位 → 亿换算系数
_UNIT_TO_YI = {"亿": 1.0, "万": 1e-4, "千": 1e-5, "百": 1e-6, "元": 1e-8, "美元": 1e-8}
_TITLE_RE = re.compile(r"^(?:第\s*)?(\d+)\s*[章节]")


def numbers_equal(a: float, b: float, tol: float = VALUE_TOLERANCE) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) / max(abs(a), 1.0) <= tol


def values_compatible(claim_val: float, claim_unit: str | None,
                      block_val: float, block_unit: str | None) -> bool:
    cu = (claim_unit or "").strip()
    bu = (block_unit or "").strip()
    if "%" in cu or "%" in bu:
        return numbers_equal(claim_val, block_val)
    cy = _UNIT_TO_YI.get(cu)
    by = _UNIT_TO_YI.get(bu)
    if cy is not None and by is not None:
        return numbers_equal(claim_val * cy, block_val * by)
    if cy is None and by is None:
        return numbers_equal(claim_val, block_val)
    return False  # 一侧有可换算单位一侧没有 → 无法确认兼容


def _match_reference_target(ref: str, block_text: str) -> bool:
    """引用目标是否在块文本中出现（含标题匹配）。"""
    m = re.search(r"第\s*(\d+)\s*[章节]", ref)
    if m:
        return bool(_TITLE_RE.search(block_text) and m.group(1) in block_text)
    for marker in ("图", "表", "附录"):
        if marker in ref:
            return marker in block_text
    if "上" in ref or "下" in ref:
        return True  # 见上/见下无法精确定位，视为存在
    return False


def _context_ctx_match(ctx: str, block_text: str) -> bool:
    """语境是否在块文本中出现：按字符有序子序列匹配（≥2 字符）。

    用有序子序列而非连续子串，以兼容简称（如 claim 语境「营收」命中
    块文本「营业收入」——「营→收」在「营 业 收 入」中顺序出现）。
    """
    key = re.sub(r"\s+", "", ctx)
    if len(key) < 2:
        return False
    norm = re.sub(r"\s+", "", block_text)
    pos = 0
    for ch in key:
        pos = norm.find(ch, pos)
        if pos < 0:
            return False
        pos += 1
    return True


def verify_claim_internal(claim: GenericClaim, blocks: list[dict]) -> VerificationOutcome:
    """内部自洽核验。blocks: [{"index","text","page_number"}]。"""
    evidence: list[dict] = []

    # 1. 交叉引用核对
    for ref in claim.cross_refs:
        found = any(_match_reference_target(ref, (b.get("text") or "")) for b in blocks)
        if not found:
            return VerificationOutcome(
                claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.9,
                mode_used=["internal"], evidence=evidence,
                reason=f"交叉引用 {ref} 在文档中找不到对应章节/图表", error_type="REFERENCE_BROKEN",
            )

    # 2. 数字一致性
    if claim.numbers:
        for num in claim.numbers:
            ctx = (num.get("context") or "")
            for b in blocks:
                text = b.get("text") or ""
                if not _context_ctx_match(ctx, text):
                    continue
                for other in extract_numbers(text):
                    if other.get("context") == ctx:
                        continue
                    if not values_compatible(
                        num.get("value"), num.get("unit"),
                        other.get("value"), other.get("unit"),
                    ):
                        return VerificationOutcome(
                            claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.9,
                            mode_used=["internal"],
                            evidence=[{"text": text, "page_number": b.get("page_number")}],
                            reason=f"语境「{ctx}」数字不一致：{num.get('value')}{num.get('unit') or ''} "
                                   f"vs {other.get('value')}{other.get('unit') or ''}",
                            error_type="NUMERIC_CONFLICT",
                        )

    # 3. SUM 校验（合计行）
    if claim.claim_kind == "NUMERIC" and claim.numbers:
        for b in blocks:
            text = b.get("text") or ""
            if "合计" not in text and "总计" not in text:
                continue
            nums = extract_numbers(text)
            if len(nums) < 2:
                continue
            total = nums[-1]["value"]
            parts = [n["value"] for n in nums[:-1]]
            if parts and not numbers_equal(sum(parts), total):
                return VerificationOutcome(
                    claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.85,
                    mode_used=["internal"],
                    evidence=[{"text": text, "page_number": b.get("page_number")}],
                    reason=f"合计校验失败：组件 {parts} 之和 = {sum(parts)} != 合计 {total}",
                    error_type="SUM_MISMATCH",
                )

    # 4. 判定汇总
    if not claim.cross_refs and not claim.numbers:
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_INSUFFICIENT, confidence=0.5,
            mode_used=["internal"], evidence=evidence,
            reason="主张无交叉引用且无数字，无法在文档内自洽核验", error_type=None,
        )
    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.6,
        mode_used=["internal"], evidence=evidence,
        reason="文档内部一致", error_type=None,
    )
