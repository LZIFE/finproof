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

# 单位 → 亿换算系数（含大额中文单位与常见外币近似）
_UNIT_TO_YI = {
    "亿": 1.0, "万": 1e-4, "千": 1e-5, "百": 1e-6, "元": 1e-8, "美元": 1e-8,
    "百万": 1e-2, "十亿": 10.0, "百亿": 100.0, "千亿": 1000.0, "万亿": 1e4,
    "人民币": 1e-8, "港元": 1.28e-8, "欧元": 1.09e-8, "日元": 6.9e-11, "英镑": 1.27e-8,
}
_TITLE_RE = re.compile(r"^(?:第\s*)?(\d+)\s*[章节]")
# 通用语境：这类短语（增长率、合计、泛动词）在文档中大量出现且数值天然不同
# （各业务线增长率不同、各表合计不同、各处"降低/节省"比例不同），不用于跨块数值一致性比较
_GENERIC_CONTEXTS = (
    "同比增长", "同比", "环比", "较上年", "合计", "总计", "小计", "增长", "下降",
    "降低", "提升", "提高", "节省", "节约", "超过", "突破", "达到", "高于", "低于",
    "增加", "减少", "上升", "下滑", "增幅", "降幅",
    # 注意：不包含「收入/利润/金额/余额」等核心指标词——「营业收入」含「收入」，
    # 若排除则核心财务指标将无法参与跨块一致性核验
    "销售", "期末", "期初", "本年", "上年", "本月", "本期", "上期", "未来",
)
# 残缺语境虚词结尾：语境以这些助词/介词/连词/方位结尾时，往往是截断的残片
# （如「研发中心和」「整为」「年度按」），无判别力，不做跨块数字一致性比较
_FRAGMENT_SUFFIXES = frozenset(
    "的为和于在从到按及与或中上下内外前后时均达有被把由向以当将已着了过"
)
# 组织通用词：语境含这些词（如「限公司」）时数值天然不同，不做跨块比较
_ORGANIZATION_WORDS = ("公司", "有限", "股份", "集团", "控股")


def _is_fragment_context(ctx: str) -> bool:
    """语境是否为残缺/无判别力片段（虚词结尾或含组织通用词）。"""
    c = (ctx or "").strip()
    if not c:
        return False
    if any(w in c for w in _ORGANIZATION_WORDS):
        return True
    return c[-1] in _FRAGMENT_SUFFIXES


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
    """引用目标是否在块文本中出现（含标题匹配，精确验证编号）。

    第 N 章/图 N-M/表 N-M/附录 X 需在块文本中找到对应编号形式，
    避免「引用第 3 章」被任意含数字的块误判为存在。
    """
    m = re.search(r"第\s*(\d+)\s*[章节]", ref)
    if m:
        return bool(_TITLE_RE.search(block_text) and m.group(1) in block_text)
    # 图/表带编号（图 2-1 / 表 3.2）
    m = re.search(r"(图|表)\s*(\d+)(?:[-.](\d+))?", ref)
    if m:
        kind, num, sub = m.group(1), m.group(2), m.group(3)
        if sub:
            return re.search(rf"{kind}\s*{num}[-.]{sub}", block_text) is not None
        return re.search(rf"{kind}\s*{num}(?:[-.]\d+)?", block_text) is not None
    if "附录" in ref:
        m = re.search(r"附录\s*([A-Z\d]+)", ref)
        return bool(m and re.search(rf"附录\s*{re.escape(m.group(1))}", block_text))
    if "上" in ref or "下" in ref:
        return True  # 见上/见下无法精确定位，视为存在
    return False


def _date_context_of(text: str, date: str) -> str:
    """日期在文本中的前置语境（日期前最多 20 字符）。"""
    idx = text.find(date)
    if idx < 0:
        return ""
    return text[max(0, idx - 20):idx].strip()


def _norm_text(text: str) -> str:
    """去空白归一化文本（块缓存用）。"""
    return re.sub(r"\s+", "", text or "")


def _ensure_block_cache(blocks: list[dict]) -> None:
    """为块字典补充预计算缓存（_norm/_charset/_numbers），幂等。

    性能优化：verify_pdf 有 5000+ 主张 × 5000+ 块，若每对都重新 re.sub
    全文本、重新 extract_numbers，耗时达分钟级；这里每块只算一次，
    后续所有主张复用。
    """
    from app.services.generic_verification.claim_extraction import extract_numbers

    for b in blocks:
        if "_norm" not in b:
            norm = _norm_text(b.get("text") or "")
            b["_norm"] = norm
            b["_charset"] = frozenset(norm)
        if "_numbers" not in b:
            b["_numbers"] = extract_numbers(b.get("text") or "")


def _ctx_matches_norm(key: str, norm: str, charset: frozenset) -> bool:
    """有序子序列匹配（基于预计算归一化文本与字符集，快速失败）。

    key 长度 < 2 时不匹配（与 _context_ctx_match 语义一致）。
    """
    if len(key) < 2:
        return False
    if not set(key) <= charset:
        return False
    pos = 0
    for ch in key:
        pos = norm.find(ch, pos)
        if pos < 0:
            return False
        pos += 1
    return True


def _context_ctx_match(ctx: str, block_text: str) -> bool:
    """语境是否在块文本中出现：按字符有序子序列匹配（≥2 字符）。

    用有序子序列而非连续子串，以兼容简称（如 claim 语境「营收」命中
    块文本「营业收入」——「营→收」在「营 业 收 入」中顺序出现）。
    """
    norm = _norm_text(block_text)
    return _ctx_matches_norm(_norm_text(ctx), norm, frozenset(norm))


def _same_context_slot(ctx: str, other_ctx: str) -> bool:
    """两个数字是否属于同一语义语境槽（任一方向子序列命中）。

    claim 语境「营收」与 other 语境「营业收入」→ 同一槽（简称兼容）；
    claim 语境「营业收入」与「同比增长」→ 不同槽（不比较）。
    任一侧语境缺失/过短（<2 字符）时无法判别 → 视为同槽，
    交由 values_compatible 直接决定（不得因语境为空而静默跳过比较）。
    """
    a = (ctx or "").strip()
    b = (other_ctx or "").strip()
    if len(a) < 2 or len(b) < 2:
        return True
    return _context_ctx_match(a, b) or _context_ctx_match(b, a)


def _quantity_comparable(unit_a: str | None, unit_b: str | None) -> bool:
    """两个数字是否属于同一数量类型（百分比 vs 绝对值不可比）。

    增长率 45% 与营收 99亿 是不同指标，数值不等不是矛盾，跳过比较，
    避免「百分比 vs 绝对值」的误报冲突。
    """
    a = (unit_a or "")
    b = (unit_b or "")
    a_pct = "%" in a or "％" in a
    b_pct = "%" in b or "％" in b
    return a_pct == b_pct


def _units_precise(unit_a: str | None, unit_b: str | None) -> bool:
    """两侧单位是否精确可比，避免把含糊/不对称单位的数字误判为矛盾。

    - 一侧有可换算单位另一侧没有（如 4585亿 vs 458502407 元/无单位）→ 不可比
    - 两侧都是不可换算计数单位且不同（如 600家 vs 32个）→ 不可比
    - 两侧均无单位（纯数字，语义含糊）→ 不可比
    """
    a = (unit_a or "").strip()
    b = (unit_b or "").strip()
    a_known = a in _UNIT_TO_YI
    b_known = b in _UNIT_TO_YI
    if a_known != b_known:
        return False
    if a_known and b_known:
        return True
    # 都不可换算：仅同单位才可比（家=家），不同单位（家 vs 个）或均无单位不可比
    return a == b and a != ""


def verify_claim_internal(claim: GenericClaim, blocks: list[dict]) -> VerificationOutcome:
    """内部自洽核验。blocks: [{"index","text","page_number"}]。

    性能：先一次性预计算每块归一化文本/字符集/数字列表（_ensure_block_cache），
    后续所有主张复用，避免 5000+ 主张 × 5000+ 块的重复 re.sub 与数字提取。
    """
    _ensure_block_cache(blocks)
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

    # 1.5 日期/期间一致性：同一语境（事件/指标）在文档多处出现应一致
    #    例如 claim 写「发布于2024年3月15日」而另一块写「发布于2025年3月15日」→ 冲突
    #    注意：日期语境常以介词/动词结尾（如「发布于」「截至」「签订于」），
    #    不能用 _is_fragment_context（虚词结尾即排除）过滤，否则日期检查永不触发
    if claim.dates:
        from app.services.generic_verification.claim_extraction import extract_dates

        for d in claim.dates:
            dctx = _date_context_of(claim.source_text, d)
            if len(_norm_text(dctx)) < 2:
                continue  # 日期无有效语境，无法判别
            for b in blocks:
                if b.get("index") == claim.block_index:
                    continue
                if not _ctx_matches_norm(_norm_text(dctx), b["_norm"], b["_charset"]):
                    continue
                for other_d in extract_dates(b.get("text") or ""):
                    if other_d == d:
                        continue
                    return VerificationOutcome(
                        claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.85,
                        mode_used=["internal"],
                        evidence=[{"text": b.get("text") or "", "page_number": b.get("page_number")}],
                        reason=f"语境「{dctx}」日期不一致：{d} vs {other_d}",
                        error_type="DATE_CONFLICT",
                    )

    # 2. 数字一致性（仅单一数值主张做跨块比较；跳过主张自身源块）
    #    多数字主张（表格行：期末/期初/增长率并存）各数字语义槽天然不同，
    #    跨块比较必然误报，不做一致性判定。
    if claim.numbers and len(claim.numbers) == 1:
        for num in claim.numbers:
            ctx = (num.get("context") or "")
            ctx_short = len(re.sub(r"\s+", "", ctx)) < 2
            for b in blocks:
                # 主张自身源块内的并列数字（如表格期末/期初两列、同一句多个数字）
                # 不是独立证据，跳过，避免自比较误报
                if b.get("index") == claim.block_index:
                    continue
                if ctx_short:
                    # 语境为空/过短：以主张原文为参照，且仅限同页
                    if b.get("page_number") != claim.page_number:
                        continue
                elif not _ctx_matches_norm(_norm_text(ctx), b["_norm"], b["_charset"]):
                    continue
                for other in b["_numbers"]:
                    other_ctx = other.get("context") or ""
                    # 主张自身的数字（同值同单位同语境）不是独立证据，跳过
                    if (other_ctx == ctx
                            and other.get("value") == num.get("value")
                            and (other.get("unit") or "") == (num.get("unit") or "")):
                        continue
                    # 通用语境（增长率/合计等）数值天然不同，不做跨块一致性比较
                    if any(g in ctx for g in _GENERIC_CONTEXTS) or any(g in other_ctx for g in _GENERIC_CONTEXTS):
                        continue
                    # 残缺语境（虚词结尾/组织词，如「研发中心和」「整为」「限公司」）
                    # 无判别力，不做跨块数字一致性比较
                    if _is_fragment_context(ctx) or _is_fragment_context(other_ctx):
                        continue
                    if ctx_short:
                        # 空语境：other 语境必须出现在主张原文中，否则无法判别
                        if not other_ctx or not _context_ctx_match(other_ctx, claim.source_text):
                            continue
                    elif not _same_context_slot(ctx, other_ctx):
                        # 不同语境槽（如主张"营收"与块内"同比增长"百分比）不构成冲突
                        continue
                    # 数量类型不同（百分比 vs 绝对值）不可比，跳过（45% vs 99亿 不是矛盾）
                    if not _quantity_comparable(num.get("unit"), other.get("unit")):
                        continue
                    # 单位不对称/含糊（4585亿 vs 无单位、600家 vs 32个）不可比，跳过
                    if not _units_precise(num.get("unit"), other.get("unit")):
                        continue
                    if not values_compatible(
                        num.get("value"), num.get("unit"),
                        other.get("value"), other.get("unit"),
                    ):
                        return VerificationOutcome(
                            claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.9,
                            mode_used=["internal"],
                            evidence=[{"text": b.get("text") or "", "page_number": b.get("page_number")}],
                            reason=f"语境「{ctx or claim.source_text[:12]}」数字不一致：{num.get('value')}{num.get('unit') or ''} "
                                   f"vs {other.get('value')}{other.get('unit') or ''}",
                            error_type="NUMERIC_CONFLICT",
                        )

    # 3. SUM 校验（合计行）——仅当合计行含主张自身的数字且组件数量合理，排除百分比
    if claim.claim_kind == "NUMERIC" and len(claim.numbers) == 1:
        claim_num = claim.numbers[0]
        claim_ctxs = [(n.get("context") or "") for n in claim.numbers]
        for b in blocks:
            text = b.get("text") or ""
            if "合计" not in text and "总计" not in text:
                continue
            # 门控：合计行须含主张语境（不再用同页兜底，避免无关合计行误报）
            if not any(_ctx_matches_norm(_norm_text(c), b["_norm"], b["_charset"])
                       for c in claim_ctxs if c):
                continue
            # 排除百分比数字（ASCII % 与全角 ％ 都排除），避免计入组件/合计
            nums = [n for n in b["_numbers"]
                    if not any(c in (n.get("unit") or "") for c in ("%", "％"))]
            # 组件数量须合理（2~10）：整页几十个数字被误当组件求和是误报
            if not (2 <= len(nums) <= 10):
                continue
            total = nums[-1]["value"]
            # 主张数字必须等于该合计行的合计值（最后一个数字），
            # 否则（如「未来12个月」的 12 只是组件）该行不是主张所指的合计
            if not numbers_equal(total, claim_num.get("value")):
                continue
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
    if not claim.cross_refs and not claim.numbers and not claim.dates:
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_INSUFFICIENT, confidence=0.5,
            mode_used=["internal"], evidence=evidence,
            reason="主张无交叉引用、无数字且无日期，无法在文档内自洽核验", error_type=None,
        )
    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.6,
        mode_used=["internal"], evidence=evidence,
        reason="文档内部一致", error_type=None,
    )
