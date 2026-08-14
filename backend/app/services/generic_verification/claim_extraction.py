"""通用主张拆解规则层（领域无关）。

职责：标记候选块、提取数字/日期/交叉引用/实体、分类主张类型。
规则层不产出最终主张（最终结构化由 LLM 层完成）；无 LLM 时以规则结果 + is_mock 兜底。
"""

from __future__ import annotations

import re

# ---------- 正则 ----------
_NUM_UNIT_RE = re.compile(r"[-+]?\d[\d,，]*(?:\.\d+)?\s*([%％万亿千米吨克个件台套份家元]|美元|人民币)?")
_DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月|20\d{2}年")
# 裸年份（无单位），如 "2001 年" 中的 2001 —— 归类为日期/事实，不是可核验数字
_BARE_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
CROSS_REF_RE = re.compile(
    r"(?:第\s*\d+\s*[章节]|图\s*\d+(?:[-.]\d+)?|表\s*\d+(?:[-.]\d+)?|附录[A-Z\d]+|"
    r"见\s*上[文]?|见\s*下[文]?|"
    r"see\s+(?:chapter|figure|table|appendix)[^。；;\n]*|"
    r"参见\s*(?:第\s*\d+\s*[章节]|图\s*\d+|表\s*\d+|附录[A-Z\d]+))",
    re.IGNORECASE,
)

_CAUSAL_WORDS = ("导致", "推动", "主要由于", "主要系", "得益于", "带动", "because of", "due to", "resulted from")
_PREDICTION_WORDS = ("预计", "将", "计划", "预期", "展望", "forecast", "expect", "aim", "guidance")
_OPINION_WORDS = ("我们认为", "建议", "我们相信", "we believe", "we recommend")
_ENTITY_STOPWORDS = frozenset({
    "关于", "由于", "因此", "公司", "报告", "如下", "以上", "其中", "包括",
    "通过", "对于", "进行", "相关", "主要", "同时", "目前", "未来", "我们",
    "可以", "需要", "已经", "没有", "一个", "这个", "该", "的", "了", "和",
    "与", "及", "或", "在", "以", "从", "到", "被", "把", "为", "等",
    "项目", "信息",
})


def _strip_thousands(text: str) -> str:
    return text.replace(",", "").replace("，", "")


def extract_numbers(text: str) -> list[dict]:
    out: list[dict] = []
    for m in _NUM_UNIT_RE.finditer(text):
        raw = m.group(0)
        unit = (m.group(1) or "").strip() or None
        num_part = re.match(r"[-+]?\d[\d,，]*(?:\.\d+)?", raw).group(0)
        try:
            value = float(_strip_thousands(num_part))
        except ValueError:
            continue
        # 裸年份（如 2001）不是可核验数字，跳过（归类为日期/事实）
        if unit is None and _BARE_YEAR_RE.fullmatch(_strip_thousands(num_part)):
            continue
        ctx = text[max(0, m.start() - 20):m.start()].strip()
        out.append({"value": value, "unit": unit, "context": ctx})
    return out


def extract_dates(text: str) -> list[str]:
    return list(dict.fromkeys(_DATE_RE.findall(text)))


def extract_cross_refs(text: str) -> list[str]:
    return [m.group(0).strip() for m in CROSS_REF_RE.finditer(text)]


def classify_kind(text: str) -> str:
    if any(w in text for w in _PREDICTION_WORDS):
        return "PREDICTION"
    if any(w in text for w in _OPINION_WORDS):
        return "OPINION"
    if any(w in text for w in _CAUSAL_WORDS):
        return "CAUSAL"
    if extract_numbers(text):
        return "NUMERIC"
    if extract_cross_refs(text):
        return "REFERENCE"
    return "FACT"


def extract_entities(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    out: list[str] = []
    for w in words:
        if w in _ENTITY_STOPWORDS or w in out:
            continue
        # 停用词字符覆盖比例 ≥ 50%（如"本项目没有需要核验"）→ 非实体；
        # 长实体名（如"华为技术有限公司"）覆盖比例低，保留
        covered = sum(len(s) for s in _ENTITY_STOPWORDS if s in w)
        if covered / len(w) >= 0.5:
            continue
        out.append(w)
    return out


def mark_candidate_blocks(blocks: list) -> set[int]:
    marked: set[int] = set()
    for i, b in enumerate(blocks):
        text = b.get("text") or ""
        if b.get("block_type") == "heading":
            continue
        if (
            extract_numbers(text) or extract_dates(text) or extract_cross_refs(text)
            or bool(_BARE_YEAR_RE.search(text))
            or extract_entities(text)
            or any(w in text for w in _CAUSAL_WORDS + _PREDICTION_WORDS + _OPINION_WORDS)
        ):
            marked.add(i)
    return marked
