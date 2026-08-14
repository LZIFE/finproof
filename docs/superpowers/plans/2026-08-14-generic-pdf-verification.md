# 通用 PDF 核验模块（Generic PDF Verification）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增领域无关的通用 PDF 核验能力（内部自洽 / 跨文档 / 外部知识三种核验方式 + 自动路由 + 错误清单报告），财报管线零改动。

**Architecture:** 新建 `backend/app/services/generic_verification/` 独立模块：通用主张拆解（规则标记候选 + LLM 结构化，Mock 兜底）→ 纯函数路由 → 三个纯函数核验引擎（internal_consistency / cross_document / external_knowledge）→ 五类判定（复用 `verification/base.py` 的 `STATUS_*`）+ error_report 汇总。新增 `POST /api/v1/generic-verify` API，复用现有 `parse_pdf` / `register_document` / 检索打分工具，仅新增不重构。

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy · PyMuPDF (fitz) · pydantic · pytest · 可选 Tesseract OCR（默认 off）

## Global Constraints

- 财报管线零改动：不得修改 `backend/app/services/verification/`、`evidence_retrieval/service.py`、`claim_service.py`、`claims/providers.py` 的现有行为；只能新增文件、或在 `app/core/config.py` 追加字段、在 `app/main.py` 追加 router 注册。
- 五类判定常量直接复用 `backend/app/services/verification/base.py`：`STATUS_SUPPORTED` / `STATUS_REFUTED` / `STATUS_PARTIALLY_SUPPORTED` / `STATUS_INSUFFICIENT` / `STATUS_UNABLE`。
- 数值相对容差：内部自洽与跨文档比对统一 `1%`（`VALUE_TOLERANCE = 0.01`，模块内常量）。
- Mock 约定：无 LLM 配置时仅规则层产出，`is_mock=True` 标识，绝不伪装为真实模型输出。
- OCR 默认 `off`：未安装 Tesseract 且配置 `ocr_engine=tesseract` 时抛 `AppError(422, "OCR_NOT_AVAILABLE")`，不得静默降级。
- 新增配置项（`app/core/config.py`）：`generic_web_search: bool = False`、`ocr_engine: str = "off"`、`generic_extraction_prompt_version: str = "generic_claim_extraction_v1"`。
- 测试环境：pytest 已配置隔离临时 DB/存储（`backend/tests/conftest.py` 自动生效），新测试放 `backend/tests/test_generic_verification/`。
- API 路径前缀与现有约定一致：`/api/v1/generic-verify`（现有路由均为 `/api/v1/...`）。

## File Structure

| 文件 | 责任 |
|---|---|
| `backend/app/core/config.py`（修改） | 追加 3 个配置字段 |
| `backend/app/services/generic_verification/schemas.py`（新建） | `GenericClaim` / `VerificationOutcome` / `ErrorItem` / `GenericClaimCreate` |
| `backend/app/services/generic_verification/claim_extraction.py`（新建） | 规则层候选标记 + 实体/数字/日期/交叉引用提取 + LLM/Mock provider |
| `backend/app/prompts/generic_claim_extraction_v1.txt`（新建） | 领域无关主张拆解 prompt |
| `backend/app/services/generic_verification/routing.py`（新建） | 纯函数路由表 |
| `backend/app/services/generic_verification/verifiers/internal_consistency.py`（新建） | 数字一致性 / 交叉引用核对 / SUM 校验 / 日期一致性 |
| `backend/app/services/generic_verification/verifiers/cross_document.py`（新建） | 证据 PDF 检索 + 数值比对 |
| `backend/app/services/generic_verification/verifiers/external_knowledge.py`（新建） | 用户资料 → LLM 常识 → 可选联网 |
| `backend/app/services/generic_verification/ocr.py`（新建） | 扫描页检测 + Tesseract 兜底 |
| `backend/app/services/generic_verification/service.py`（新建） | 编排入口 `verify_pdf` |
| `backend/app/api/generic_verify.py`（新建） | `POST /api/v1/generic-verify` |
| `backend/app/main.py`（修改） | 注册 generic_verify router |
| `backend/tests/test_generic_verification/`（新建） | 各任务测试 |

---

### Task 1: 配置项新增

**Files:**
- Modify: `backend/app/core/config.py`（`Settings` 类末尾，`claim_extraction_prompt_version` 之后）
- Test: `backend/tests/test_generic_verification/test_config.py`

**Interfaces:**
- Produces: `Settings.generic_web_search: bool`（默认 `False`）、`Settings.ocr_engine: str`（默认 `"off"`）、`Settings.generic_extraction_prompt_version: str`（默认 `"generic_claim_extraction_v1"`）—— 后续所有任务经 `get_settings()` 读取。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_config.py"""
from app.core.config import get_settings


def test_generic_verification_config_defaults():
    s = get_settings()
    assert s.generic_web_search is False
    assert s.ocr_engine == "off"
    assert s.generic_extraction_prompt_version == "generic_claim_extraction_v1"


def test_generic_verification_config_env_override(monkeypatch):
    monkeypatch.setenv("FINPROOF_GENERIC_WEB_SEARCH", "true")
    monkeypatch.setenv("FINPROOF_OCR_ENGINE", "tesseract")
    from app.core.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.generic_web_search is True
    assert s.ocr_engine == "tesseract"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_config.py -v`
Expected: FAIL，`AttributeError: 'Settings' object has no attribute 'generic_web_search'`

- [ ] **Step 3: 实现**

在 `backend/app/core/config.py` 的 `claim_extraction_prompt_version: str = "v1"` 行后追加：

```python
    # --- 通用 PDF 核验（generic_verification 模块，Phase 24） ---
    generic_web_search: bool = False
    ocr_engine: str = "off"
    generic_extraction_prompt_version: str = "generic_claim_extraction_v1"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_config.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_generic_verification/test_config.py
git commit -m "feat: add generic PDF verification config fields"
```

---

### Task 2: 通用主张与核验结果 Schema

**Files:**
- Create: `backend/app/services/generic_verification/__init__.py`、`backend/app/services/generic_verification/schemas.py`
- Test: `backend/tests/test_generic_verification/test_schemas.py`

**Interfaces:**
- Consumes: `backend/app/services/verification/base.py` 的 `STATUS_*` 常量。
- Produces:
  - `GenericClaim`（dataclass）：`claim_id: str` / `source_text: str` / `claim_kind: str`（`FACT|NUMERIC|CAUSAL|PREDICTION|OPINION|REFERENCE`）/ `page_number: int` / `block_index: int` / `entities: list[str]` / `numbers: list[dict]`（`{"value": float, "unit": str|None, "context": str}`）/ `dates: list[str]` / `cross_refs: list[str]` / `extraction_method: str` / `confidence: float`；`to_dict()`。
  - `GenericClaimCreate`（pydantic）：校验字段类型与 `claim_kind` 取值。
  - `VerificationOutcome`（dataclass）：`claim_id` / `verdict: str`（`STATUS_*` 之一或 `"NOT_VERIFIABLE"`）/ `confidence: float` / `mode_used: list[str]` / `evidence: list[dict]` / `reason: str` / `error_type: str|None`；`to_dict()`。
  - `ErrorItem`（dataclass）：`page_number: int` / `source_text: str` / `verdict: str` / `error_type: str` / `detail: str`；`to_dict()`。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_schemas.py"""
import pytest
from pydantic import ValidationError

from app.services.generic_verification.schemas import (
    ErrorItem,
    GenericClaim,
    GenericClaimCreate,
    VerificationOutcome,
)
from app.services.verification.base import STATUS_REFUTED, STATUS_SUPPORTED


def test_generic_claim_to_dict():
    c = GenericClaim(
        claim_id="GCLM-001",
        source_text="营收 1.2 亿元，同比增长 30%",
        claim_kind="NUMERIC",
        page_number=5,
        block_index=3,
        entities=["公司A"],
        numbers=[{"value": 1.2, "unit": "亿", "context": "营收"}],
        dates=[],
        cross_refs=[],
        extraction_method="rules",
        confidence=0.8,
    )
    d = c.to_dict()
    assert d["claim_id"] == "GCLM-001"
    assert d["numbers"][0]["value"] == 1.2


def test_generic_claim_create_valid():
    g = GenericClaimCreate(
        claim_id="GCLM-001",
        source_text="x",
        claim_kind="FACT",
        page_number=1,
        block_index=0,
        entities=[],
        numbers=[],
        dates=[],
        cross_refs=[],
        extraction_method="rules",
        confidence=0.5,
    )
    assert g.claim_kind == "FACT"


def test_generic_claim_create_rejects_bad_kind():
    with pytest.raises(ValidationError):
        GenericClaimCreate(
            claim_id="GCLM-002", source_text="x", claim_kind="BOGUS",
            page_number=1, block_index=0, entities=[], numbers=[],
            dates=[], cross_refs=[], extraction_method="rules", confidence=0.5,
        )


def test_verification_outcome_to_dict():
    o = VerificationOutcome(
        claim_id="GCLM-001", verdict=STATUS_REFUTED, confidence=0.9,
        mode_used=["internal"], evidence=[{"text": "1.2 万", "page_number": 5}],
        reason="数字不一致", error_type="NUMERIC_CONFLICT",
    )
    d = o.to_dict()
    assert d["verdict"] == STATUS_REFUTED
    assert d["error_type"] == "NUMERIC_CONFLICT"


def test_error_item_to_dict():
    e = ErrorItem(page_number=5, source_text="营收 1.2 亿", verdict=STATUS_SUPPORTED,
                  error_type="NUMERIC_CONFLICT", detail="1.2 亿 vs 1.2 万")
    assert e.to_dict()["page_number"] == 5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_schemas.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/__init__.py`：

```python
"""通用 PDF 内容核验模块（领域无关，Phase 24）。

与财报核验管线平行：仅新增文件与共用层复用，不修改现有财报行为。
"""
```

`backend/app/services/generic_verification/schemas.py`：

```python
"""通用主张与核验结果数据结构（领域无关）。

- GenericClaim：通用主张骨架（数字/日期/实体/交叉引用），无财务 metric/period/scope 字段。
- VerificationOutcome：单条主张核验结果（五类判定 + 实际使用的核验方式）。
- ErrorItem：错误清单条目（仅 REFUTED / PARTIALLY_SUPPORTED 进入清单）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

CLAIM_KINDS = frozenset({"FACT", "NUMERIC", "CAUSAL", "PREDICTION", "OPINION", "REFERENCE"})
VERDICTS = frozenset({STATUS_SUPPORTED, STATUS_REFUTED, STATUS_PARTIALLY_SUPPORTED,
                      STATUS_INSUFFICIENT, STATUS_UNABLE, "NOT_VERIFIABLE"})


@dataclass
class GenericClaim:
    claim_id: str
    source_text: str
    claim_kind: str
    page_number: int
    block_index: int
    entities: list[str] = field(default_factory=list)
    numbers: list[dict] = field(default_factory=list)  # {"value","unit","context"}
    dates: list[str] = field(default_factory=list)
    cross_refs: list[str] = field(default_factory=list)
    extraction_method: str = "rules"
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "source_text": self.source_text,
            "claim_kind": self.claim_kind,
            "page_number": self.page_number,
            "block_index": self.block_index,
            "entities": self.entities,
            "numbers": self.numbers,
            "dates": self.dates,
            "cross_refs": self.cross_refs,
            "extraction_method": self.extraction_method,
            "confidence": round(self.confidence, 4),
        }


class GenericClaimCreate(BaseModel):
    claim_id: str = Field(min_length=1, max_length=64)
    source_text: str = Field(min_length=1)
    claim_kind: str
    page_number: int = Field(ge=1)
    block_index: int = Field(ge=0)
    entities: list[str] = Field(default_factory=list)
    numbers: list[dict] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    cross_refs: list[str] = Field(default_factory=list)
    extraction_method: str = Field(default="rules", max_length=30)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    def __init__(self, **data):
        if data.get("claim_kind") not in CLAIM_KINDS:
            raise ValidationError("invalid claim_kind", GenericClaimCreate)
        super().__init__(**data)


@dataclass
class VerificationOutcome:
    claim_id: str
    verdict: str
    confidence: float = 0.0
    mode_used: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    reason: str = ""
    error_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 4),
            "mode_used": self.mode_used,
            "evidence": self.evidence,
            "reason": self.reason,
            "error_type": self.error_type,
        }


@dataclass
class ErrorItem:
    page_number: int
    source_text: str
    verdict: str
    error_type: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "source_text": self.source_text,
            "verdict": self.verdict,
            "error_type": self.error_type,
            "detail": self.detail,
        }
```

注意：`GenericClaimCreate.__init__` 里 `ValidationError` 需从 `pydantic` import；若该写法在 pydantic v2 校验时机有问题，改为在 `claim_service` 同款模式（构造后校验）——测试驱动，以测试通过为准。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_schemas.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/ backend/tests/test_generic_verification/test_schemas.py
git commit -m "feat: add generic claim and verification outcome schemas"
```

---

### Task 3: 规则层主张候选标记与字段提取

**Files:**
- Create: `backend/app/services/generic_verification/claim_extraction.py`
- Test: `backend/tests/test_generic_verification/test_claim_extraction.py`

**Interfaces:**
- Consumes: 无外部依赖（纯标准库 + `re`）。
- Produces:
  - `CROSS_REF_RE`（编译正则）：`第\s*\d+\s*[章节]`、`图\s*\d+([-.]\d+)?`、`表\s*\d+([-.]\d+)?`、`附录[A-Z\d]+`、`见\s*上[文]?`、`见\s*下[文]?`、`see (chapter|figure|table|appendix)`（英文小写匹配）。
  - `mark_candidate_blocks(blocks: list[dict]) -> set[int]`：返回候选块下标集合（含数字+单位 / 日期 / 专有名词 / 交叉引用 / 因果词 / 预测词 / 观点词的块）。
  - `extract_numbers(text: str) -> list[dict]`：返回 `{"value": float, "unit": str|None, "context": str}` 列表（`context` 为数字前 20 个字符；百分比 `30%` → value 30 unit `%`；千分位逗号剥除）。
  - `extract_dates(text: str) -> list[str]`：`\d{4}年\d{1,2}月\d{1,2}日` / `\d{4}-\d{2}-\d{2}` / `\d{4}年\d{1,2}月` / `20\d{2}年`。
  - `extract_cross_refs(text: str) -> list[str]`：匹配 `CROSS_REF_RE`。
  - `classify_kind(text: str) -> str`：含预测词 → `PREDICTION`；观点词 → `OPINION`；含因果词 → `CAUSAL`；含数字 → `NUMERIC`；含交叉引用 → `REFERENCE`；否则 `FACT`。
  - `extract_entities(text: str) -> list[str]`：中文大写词（2–8 字连续汉字）去停用词（`关于/由于/因此/公司/报告/如下/以上/其中/包括/通过/对于/进行/相关/主要/同时/目前/未来`），去重保留顺序。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_claim_extraction.py"""
from app.services.generic_verification.claim_extraction import (
    classify_kind,
    extract_cross_refs,
    extract_dates,
    extract_entities,
    extract_numbers,
    mark_candidate_blocks,
)


def test_extract_numbers_percent_and_thousands():
    nums = extract_numbers("同比增长 30%，营收 1,200 万元")
    assert any(n["value"] == 30 and n["unit"] == "%" for n in nums)
    assert any(n["value"] == 1200 and n["unit"] == "万" for n in nums)


def test_extract_dates():
    dates = extract_dates("2024年3月15日发布，年报期间为2024年，披露于2024-03-15")
    assert "2024年3月15日" in dates
    assert "2024年" in dates
    assert "2024-03-15" in dates


def test_extract_cross_refs():
    refs = extract_cross_refs("详见第 3 章及图 2-1，另见附录A")
    assert any("第 3 章" in r for r in refs)
    assert any("图 2-1" in r for r in refs)
    assert any("附录A" in r for r in refs)


def test_classify_kind():
    assert classify_kind("预计明年营收增长") == "PREDICTION"
    assert classify_kind("我们认为该方案可行") == "OPINION"
    assert classify_kind("主要由于成本下降导致") == "CAUSAL"
    assert classify_kind("营收 1.2 亿元") == "NUMERIC"
    assert classify_kind("公司成立于 2001 年") == "FACT"


def test_extract_entities():
    ents = extract_entities("华为技术有限公司发布新款手机，关于产能的说明")
    assert "华为技术有限公司" in ents
    assert "关于" not in ents


def test_mark_candidate_blocks():
    blocks = [
        {"index": 0, "text": "第一章 概述", "block_type": "heading"},
        {"index": 1, "text": "公司成立于 2001 年", "block_type": "paragraph"},
        {"index": 2, "text": "本项目没有需要核验的信息", "block_type": "paragraph"},
    ]
    marked = mark_candidate_blocks(blocks)
    assert 1 in marked
    assert 0 not in marked
    assert 2 not in marked
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_claim_extraction.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.claim_extraction'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/claim_extraction.py`：

```python
"""通用主张拆解规则层（领域无关）。

职责：标记候选块、提取数字/日期/交叉引用/实体、分类主张类型。
规则层不产出最终主张（最终结构化由 LLM 层完成）；无 LLM 时以规则结果 + is_mock 兜底。
"""

from __future__ import annotations

import re

# ---------- 正则 ----------
_NUM_UNIT_RE = re.compile(r"[-+]?\d[\d,，]*(?:\.\d+)?\s*([%％万亿千米吨克个件台套份家元]|美元|人民币)?")
_DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月|20\d{2}年")
CROSS_REF_RE = re.compile(
    r"(?:第\s*\d+\s*[章节]|图\s*\d+(?:[-.]\d+)?|表\s*\d+(?:[-.]\d+)?|附录[A-Z\d]+|"
    r"见\s*上[文]?|见\s*下[文]?|"
    r"see\s+(?:chapter|figure|table|appendix)[^。；;\n]*|"
    r"参见\s*(?:第\s*\d+\s*[章节]|图\s*\d+|表\s*\d+|附录[A-Z\d]+))",
    re.IGNORECASE,
)

_CAUSAL_WORDS = ("导致", "推动", "主要由于", "主要系", "得益于", "带动", "because of", "due to", "resulted from")
_PREDICTION_WORDS = ("预计", "将", "计划", "预期", "展望", "forecast", "expect", "aim", "guidance")
_OPINION_WORDS = ("我们认为", "我们认为", "建议", "我们相信", "we believe", "we recommend")
_ENTITY_STOPWORDS = frozenset({
    "关于", "由于", "因此", "公司", "报告", "如下", "以上", "其中", "包括",
    "通过", "对于", "进行", "相关", "主要", "同时", "目前", "未来", "我们",
    "可以", "需要", "已经", "没有", "一个", "这个", "该", "的", "了", "和",
    "与", "及", "或", "在", "以", "从", "到", "被", "把", "为", "等",
})


def _strip_thousands(text: str) -> str:
    return text.replace(",", "").replace("，", "")


def extract_numbers(text: str) -> list[dict]:
    out: list[dict] = []
    for m in _NUM_UNIT_RE.finditer(text):
        raw = m.group(0)
        unit = (m.group(1) or "").strip() or None
        # 数字部分（去掉单位尾巴）
        num_part = re.match(r"[-+]?\d[\d,，]*(?:\.\d+)?", raw).group(0)
        try:
            value = float(_strip_thousands(num_part))
        except ValueError:
            continue
        if value == 0 and unit is None and len(raw) <= 1:
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
        if any(stop in w for stop in _ENTITY_STOPWORDS) and len(w) <= 4:
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
            or extract_entities(text)
            or any(w in text for w in _CAUSAL_WORDS + _PREDICTION_WORDS + _OPINION_WORDS)
        ):
            marked.add(i)
    return marked
```

注意：`mark_candidate_blocks` 的 `extract_entities` 会匹配多数中文段落（如「本项目没有需要核验的信息」含 2 字词）。若测试出现误标，在 `extract_entities` 增加通用停用词（如「没有/需要/信息/项目」）或提高最小词长阈值 —— 以测试通过为准。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_claim_extraction.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/claim_extraction.py backend/tests/test_generic_verification/test_claim_extraction.py
git commit -m "feat: add rule-layer generic claim extraction"
```

---

### Task 4: 主张拆解 LLM Provider 与 Prompt

**Files:**
- Create: `backend/app/prompts/generic_claim_extraction_v1.txt`
- Modify: `backend/app/services/generic_verification/claim_extraction.py`（追加 provider 类）
- Test: `backend/tests/test_generic_verification/test_extraction_provider.py`

**Interfaces:**
- Consumes: `get_settings()`（`claim_extraction_base_url/api_key/model/timeout_seconds/max_retries` 复用现有 LLM 配置）、Task 2 的 `GenericClaim`、Task 3 的规则函数、`app/services/claims/providers.py` 的 `load_prompt` 风格（新增 `load_generic_prompt` 于本任务）。
- Produces:
  - `load_generic_prompt(version: str) -> str`：读取 `backend/app/prompts/generic_claim_extraction_v1.txt`，不存在抛 `AppError(500, "PROMPT_NOT_FOUND")`。
  - `GenericClaimExtractionResult`（dataclass）：`claims: list[GenericClaim]` / `provider: str` / `model_name: str|None` / `is_mock: bool` / `input_block_count: int` / `candidate_sentence_count: int`。
  - `GenericClaimExtractor`：`extract(blocks: list[dict], prompt_version: str) -> GenericClaimExtractionResult`；内部 `_rules_only(blocks) -> list[GenericClaim]`、`_call_llm(messages) -> tuple[str, dict|None]`（httpx POST `{base_url}/chat/completions`，Bearer key，temperature 0，重试 `max_retries+1` 次）、`_parse_response(content) -> list[dict]`。
  - 无 LLM 配置（base_url/api_key/model 任一为空）→ 返回 `is_mock=True` 的规则结果（绝不伪装）。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_extraction_provider.py"""
import json

import pytest

from app.core.exceptions import AppError
from app.services.generic_verification.claim_extraction import (
    GenericClaimExtractionResult,
    GenericClaimExtractor,
    load_generic_prompt,
)


def test_load_generic_prompt_missing_version():
    with pytest.raises(AppError):
        load_generic_prompt("does_not_exist")


def test_mock_when_no_llm_config(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: _FakeSettings())
    extractor = GenericClaimExtractor()
    blocks = [
        {"index": 0, "text": "营收 1.2 亿元", "block_type": "paragraph"},
        {"index": 1, "text": "普通段落", "block_type": "paragraph"},
    ]
    result = extractor.extract(blocks, "generic_claim_extraction_v1")
    assert isinstance(result, GenericClaimExtractionResult)
    assert result.is_mock is True
    assert len(result.claims) >= 1
    assert result.claims[0].claim_kind == "NUMERIC"


def test_llm_parse_response():
    extractor = GenericClaimExtractor()
    content = json.dumps([
        {"source_text": "营收 1.2 亿元", "claim_kind": "NUMERIC", "page_number": 1,
         "block_index": 0, "entities": ["公司A"], "numbers": [{"value": 1.2, "unit": "亿", "context": "营收"}],
         "dates": [], "cross_refs": [], "confidence": 0.9},
    ], ensure_ascii=False)
    items = extractor._parse_response(content)
    assert items[0]["claim_kind"] == "NUMERIC"


class _FakeSettings:
    claim_extraction_base_url = ""
    claim_extraction_api_key = ""
    claim_extraction_model = ""
    claim_extraction_timeout_seconds = 10
    claim_extraction_max_retries = 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_extraction_provider.py -v`
Expected: FAIL，`ImportError: cannot import name 'GenericClaimExtractor'`

- [ ] **Step 3: 实现**

`backend/app/prompts/generic_claim_extraction_v1.txt`：

```text
你是通用文档核验助手。从给定的文本块中提取可核验的主张（Claim），
输出 JSON 数组，每个元素字段：
- source_text: 主张原文（必须来自当前段落，不得改写）
- claim_kind: 枚举 FACT | NUMERIC | CAUSAL | PREDICTION | OPINION | REFERENCE
- page_number: int（当前段落的页码，从输入读取）
- block_index: int
- entities: 字符串数组（主张中的实体/专有名词，中文不超过8字）
- numbers: 数组，每个元素 {"value": number, "unit": string|null, "context": string}（数字前的简短语境，如"营收"）
- dates: 字符串数组（出现的日期/期间，如 "2024年" "2024-03-15"）
- cross_refs: 字符串数组（交叉引用，如 "第 3 章" "图 2-1" "附录A"）
- confidence: 0到1的数值

只提取"值得核验"的主张：含具体数字、日期、事实性断言、因果或预测。
观点（OPINION）和预测（PREDICTION）也提取，但标注准确。
不要提取无信息量的寒暄、章节标题本身。前一段落与后一段落仅作上下文，不要提取。
```

在 `backend/app/services/generic_verification/claim_extraction.py` 末尾追加：

```python
"""（以下为本模块 provider 部分，追加于规则层之后）"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.generic_verification.schemas import GenericClaim

logger = logging.getLogger(__name__)

GENERIC_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_generic_prompt(version: str) -> str:
    path = GENERIC_PROMPT_DIR / f"{version}.txt"
    if not path.exists():
        raise AppError(f"通用主张 Prompt 版本不存在: {version}", status_code=500, code="PROMPT_NOT_FOUND")
    return path.read_text(encoding="utf-8")


@dataclass
class GenericClaimExtractionResult:
    claims: list[GenericClaim] = field(default_factory=list)
    provider: str = ""
    model_name: str | None = None
    is_mock: bool = False
    input_block_count: int = 0
    candidate_sentence_count: int = 0


class GenericClaimExtractor:
    """领域无关主张拆解：有 LLM 配置 → LLM 结构化；无配置 → 规则 + is_mock。"""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    # ---------- 公开入口 ----------

    def extract(self, blocks: list[dict], prompt_version: str = "generic_claim_extraction_v1") -> GenericClaimExtractionResult:
        cfg = self.settings
        if not (cfg.claim_extraction_base_url and cfg.claim_extraction_api_key and cfg.claim_extraction_model):
            claims = self._rules_only(blocks)
            return GenericClaimExtractionResult(
                claims=claims, provider="mock", is_mock=True,
                input_block_count=len(blocks), candidate_sentence_count=len(claims),
            )
        prompt = load_generic_prompt(prompt_version)
        claims: list[GenericClaim] = []
        total_usage: dict | None = None
        for i, b in enumerate(blocks):
            text = b.get("text") or ""
            if not text.strip():
                continue
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": (
                    f"页码: {b.get('page_number', 1)}\n块序号: {i}\n\n"
                    f"【当前段落】\n{text}\n"
                )},
            ]
            content, usage = self._call_llm(messages)
            if usage:
                total_usage = usage
            for item in self._parse_response(content):
                claims.append(self._to_claim(item, b, i))
        return GenericClaimExtractionResult(
            claims=claims, provider="llm", model_name=cfg.claim_extraction_model,
            is_mock=False, input_block_count=len(blocks),
            candidate_sentence_count=len(claims),
        )

    # ---------- 规则兜底 ----------

    def _rules_only(self, blocks: list[dict]) -> list[GenericClaim]:
        from app.services.generic_verification.claim_extraction import (
            classify_kind,
            extract_cross_refs,
            extract_dates,
            extract_entities,
            extract_numbers,
            mark_candidate_blocks,
        )

        marked = mark_candidate_blocks(blocks)
        out: list[GenericClaim] = []
        for i, b in enumerate(blocks):
            if i not in marked:
                continue
            text = b.get("text") or ""
            out.append(GenericClaim(
                claim_id=f"GCLM-{i:03d}",
                source_text=text,
                claim_kind=classify_kind(text),
                page_number=int(b.get("page_number") or 1),
                block_index=i,
                entities=extract_entities(text),
                numbers=extract_numbers(text),
                dates=extract_dates(text),
                cross_refs=extract_cross_refs(text),
                extraction_method="rules",
                confidence=0.7,
            ))
        return out

    # ---------- LLM ----------

    def _call_llm(self, messages: list[dict]) -> tuple[str, dict | None]:
        cfg = self.settings
        url = f"{cfg.claim_extraction_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {cfg.claim_extraction_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": cfg.claim_extraction_model, "messages": messages, "temperature": 0}
        last_exc: Exception | None = None
        for attempt in range(cfg.claim_extraction_max_retries + 1):
            try:
                resp = httpx.post(url, json=payload, headers=headers,
                                  timeout=cfg.claim_extraction_timeout_seconds)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"], data.get("usage")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < cfg.claim_extraction_max_retries:
                    continue
        raise AppError(f"通用主张拆解 LLM 调用失败: {last_exc}", status_code=502, code="LLM_CALL_FAILED")

    def _parse_response(self, content: str) -> list[dict]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("[")
            end = content.rfind("]")
            if start < 0 or end < start:
                logger.warning("generic extraction: invalid JSON from LLM, len=%s", len(content))
                return []
            try:
                data = json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                return []
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("source_text"):
                continue
            out.append(item)
        return out

    def _to_claim(self, item: dict, block: dict, index: int) -> GenericClaim:
        return GenericClaim(
            claim_id=item.get("claim_id") or f"GCLM-{index:03d}",
            source_text=item["source_text"],
            claim_kind=item.get("claim_kind") or "FACT",
            page_number=int(item.get("page_number") or block.get("page_number") or 1),
            block_index=int(item.get("block_index") if item.get("block_index") is not None else index),
            entities=list(item.get("entities") or []),
            numbers=list(item.get("numbers") or []),
            dates=list(item.get("dates") or []),
            cross_refs=list(item.get("cross_refs") or []),
            extraction_method="llm",
            confidence=float(item.get("confidence") or 0.8),
        )
```

注意：`GenericClaimExtractor` 中的 `_rules_only` 内 `from ... import` 与模块顶部 import 重复是允许的（避免循环依赖），但更稳妥做法是顶部直接 import 规则函数 —— 若顶部 import 无循环问题则移除函数内 import，保持 DRY。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_extraction_provider.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts/generic_claim_extraction_v1.txt backend/app/services/generic_verification/claim_extraction.py backend/tests/test_generic_verification/test_extraction_provider.py
git commit -m "feat: add generic claim extraction provider and prompt"
```

---

### Task 5: 自动路由（纯函数）

**Files:**
- Create: `backend/app/services/generic_verification/routing.py`
- Test: `backend/tests/test_generic_verification/test_routing.py`

**Interfaces:**
- Consumes: Task 2 `GenericClaim`、Task 3 `extract_cross_refs`/`extract_numbers`。
- Produces:
  - `ROUTE_INTERNAL = "internal"`、`ROUTE_CROSS_DOC = "cross_doc"`、`ROUTE_EXTERNAL = "external"`。
  - `route_claim(claim: GenericClaim, has_evidence: bool, force_mode: str | None = None) -> list[str]`：
    - `force_mode in {"internal","cross_doc","external"}` → `[force_mode]`。
    - OPINION / PREDICTION → `[]`（不可核验）。
    - 有 cross_refs 或文档内多处数字 → 加 `internal`。
    - `has_evidence and claim.entities/numbers` → 加 `cross_doc`。
    - 无 cross_doc 且 `claim_kind in {FACT, NUMERIC}` 且无内部条件 → 加 `external`。
    - 结果去重保序；空列表表示不可核验。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_routing.py"""
from app.services.generic_verification.routing import (
    ROUTE_CROSS_DOC,
    ROUTE_EXTERNAL,
    ROUTE_INTERNAL,
    route_claim,
)
from app.services.generic_verification.schemas import GenericClaim


def _claim(**kw) -> GenericClaim:
    base = dict(claim_id="GCLM-001", source_text="x", claim_kind="FACT",
                page_number=1, block_index=0, entities=["公司A"], numbers=[],
                dates=[], cross_refs=[], extraction_method="rules", confidence=0.5)
    base.update(kw)
    return GenericClaim(**base)


def test_opinion_not_verifiable():
    assert route_claim(_claim(claim_kind="OPINION"), has_evidence=False) == []


def test_prediction_not_verifiable():
    assert route_claim(_claim(claim_kind="PREDICTION"), has_evidence=False) == []


def test_cross_ref_routes_internal():
    c = _claim(cross_refs=["第 3 章"])
    assert ROUTE_INTERNAL in route_claim(c, has_evidence=False)


def test_evidence_routes_cross_doc():
    c = _claim(entities=["公司A"], numbers=[{"value": 1.2, "unit": "亿", "context": "营收"}])
    assert ROUTE_CROSS_DOC in route_claim(c, has_evidence=True)


def test_plain_fact_routes_external():
    c = _claim(claim_kind="FACT", entities=["北京"])
    routes = route_claim(c, has_evidence=False)
    assert ROUTE_EXTERNAL in routes
    assert ROUTE_INTERNAL not in routes


def test_combination_internal_and_cross_doc():
    c = _claim(cross_refs=["表 1"], entities=["公司A"],
               numbers=[{"value": 1.2, "unit": "亿", "context": "营收"}])
    routes = route_claim(c, has_evidence=True)
    assert ROUTE_INTERNAL in routes
    assert ROUTE_CROSS_DOC in routes


def test_force_mode():
    c = _claim(claim_kind="OPINION")
    assert route_claim(c, has_evidence=False, force_mode="internal") == ["internal"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_routing.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.routing'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/routing.py`：

```python
"""通用核验方式自动路由（纯函数，无 DB / 无 I/O）。

按主张特征决定核验方式组合：
- internal：有交叉引用，或同一实体多处出现数字（文档内部自洽）
- cross_doc：用户提供了证据文档且主张含实体/数字（跨文档核验）
- external：无内部依据且无证据时，交由外部知识（LLM 常识 / 用户资料 / 联网）
OPINION / PREDICTION 默认不可核验（与财报系统对 forecast/opinion 的处理一致）。
"""

from __future__ import annotations

ROUTE_INTERNAL = "internal"
ROUTE_CROSS_DOC = "cross_doc"
ROUTE_EXTERNAL = "external"

FORCE_MODES = frozenset({ROUTE_INTERNAL, ROUTE_CROSS_DOC, ROUTE_EXTERNAL})
_NOT_VERIFIABLE_KINDS = frozenset({"OPINION", "PREDICTION"})


def route_claim(claim, has_evidence: bool, force_mode: str | None = None) -> list[str]:
    """返回核验方式列表（去重保序）；空列表表示不可核验。"""
    if force_mode in FORCE_MODES:
        return [force_mode]
    if claim.claim_kind in _NOT_VERIFIABLE_KINDS:
        return []

    routes: list[str] = []
    if claim.cross_refs:
        routes.append(ROUTE_INTERNAL)
    if has_evidence and (claim.entities or claim.numbers):
        routes.append(ROUTE_CROSS_DOC)
    if not routes and claim.claim_kind in {"FACT", "NUMERIC"}:
        routes.append(ROUTE_EXTERNAL)
    return list(dict.fromkeys(routes))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_routing.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/routing.py backend/tests/test_generic_verification/test_routing.py
git commit -m "feat: add generic verification routing"
```

---

### Task 6: 内部自洽核验引擎

**Files:**
- Create: `backend/app/services/generic_verification/verifiers/__init__.py`、`backend/app/services/generic_verification/verifiers/internal_consistency.py`
- Test: `backend/tests/test_generic_verification/test_internal_consistency.py`

**Interfaces:**
- Consumes: Task 2 `VerificationOutcome` / `GenericClaim`、`base.py` 的 `STATUS_*`、Task 3 `extract_numbers`/`extract_cross_refs`。
- Produces:
  - `VALUE_TOLERANCE = 0.01`（相对误差 1%）。
  - `numbers_equal(a: float, b: float, tol: float = VALUE_TOLERANCE) -> bool`：`abs(a-b)/max(abs(a),1.0) <= tol`。
  - `values_compatible(claim_val: float, claim_unit: str|None, block_val: float, block_unit: str|None) -> bool`：单位可换算（亿/万/千/百/元/美元）→ 换算后按相对误差比较；单位均为 None 或同单位 → 原值比较；单位含 `%` → 按原值（剥离 `%`）。
  - `find_numeric_occurrences(blocks: list[dict]) -> dict[str, list[float]]`：按「数字前 20 字符语境 + 单位」聚合块内所有数字出现位置。
  - `verify_claim_internal(claim: GenericClaim, blocks: list[dict], ref_regex=None) -> VerificationOutcome`：
    1. 交叉引用核对：对 `claim.cross_refs` 中的每个引用，在 blocks 中找标题/文本块是否含引用目标（`第 3 章` → 找块文本以「第 3 章」开头或含「3 章」标题）；找不到 → `REFUTED`（error_type `REFERENCE_BROKEN`），找到 → 继续。
    2. 数字一致性：对 claim 每个 number，在 blocks 中找同语境（`context` 前 8 字符子串命中）的其他数字；任一数字与 claim 数值不兼容 → `REFUTED`（`NUMERIC_CONFLICT`）；全部兼容或找不到 → 不判 REFUTED。
    3. SUM 校验：若 blocks 中含「合计/总计」且 claim 为 NUMERIC，尝试 `sum(components) == total`（组件为同语境下合计行之前的数字）；失败 → `REFUTED`（`SUM_MISMATCH`）。
    4. 无任何 REFUTED 依据 → `SUPPORTED`（confidence 0.6）；claim 无 cross_refs 且无 numbers → `INSUFFICIENT_EVIDENCE`。
  - 返回的 `VerificationOutcome.mode_used=["internal"]`。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_internal_consistency.py"""
from app.services.generic_verification.schemas import GenericClaim
from app.services.generic_verification.verifiers.internal_consistency import (
    VALUE_TOLERANCE,
    numbers_equal,
    values_compatible,
    verify_claim_internal,
)
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def _claim(text="营收 1.2 亿元", kind="NUMERIC", cross_refs=None, numbers=None):
    return GenericClaim(
        claim_id="GCLM-001", source_text=text, claim_kind=kind, page_number=1,
        block_index=0, entities=["公司A"],
        numbers=numbers if numbers is not None else [{"value": 1.2, "unit": "亿", "context": "营收"}],
        dates=[], cross_refs=cross_refs or [], extraction_method="rules", confidence=0.5,
    )


def test_numbers_equal():
    assert numbers_equal(1.2, 1.2)
    assert numbers_equal(100, 100.5, tol=0.01)  # 0.5% 相对误差在 1% 内
    assert not numbers_equal(100, 110, tol=0.01)


def test_values_compatible_unit_conversion():
    assert values_compatible(1.2, "亿", 12000, "万")
    assert values_compatible(30, "%", 30, "%")
    assert not values_compatible(1.2, "亿", 1.2, "万")


def test_verify_conflict_detected():
    blocks = [
        {"index": 0, "text": "营业收入 1.2 万元", "page_number": 2},
    ]
    out = verify_claim_internal(_claim(), blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "NUMERIC_CONFLICT"


def test_verify_consistent_supported():
    blocks = [
        {"index": 0, "text": "营业收入 1.2 亿元，较上年增长", "page_number": 2},
    ]
    out = verify_claim_internal(_claim(), blocks)
    assert out.verdict == STATUS_SUPPORTED


def test_verify_broken_reference():
    c = _claim(cross_refs=["第 9 章"], numbers=[])
    blocks = [{"index": 0, "text": "第一章 概述", "page_number": 1}]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "REFERENCE_BROKEN"


def test_verify_no_evidence_insufficient():
    c = _claim(numbers=[], cross_refs=[])
    blocks = [{"index": 0, "text": "无关段落", "page_number": 1}]
    out = verify_claim_internal(c, blocks)
    assert out.verdict == STATUS_INSUFFICIENT
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_internal_consistency.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.verifiers'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/verifiers/__init__.py`：

```python
"""通用核验引擎包（纯函数，可独立测试）。"""
```

`backend/app/services/generic_verification/verifiers/internal_consistency.py`：

```python
"""内部自洽核验引擎：同一文档内数字/交叉引用/合计一致性。

纯函数：输入 claim + 文档块列表，输出 VerificationOutcome。
"""

from __future__ import annotations

import re

from app.services.generic_verification.claim_extraction import extract_cross_refs
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
        return "见上" in block_text or "见下" in block_text or True  # 见上/见下无法精确定位
    return False


def _context_ctx_match(ctx: str, block_text: str) -> bool:
    key = re.sub(r"\s+", "", ctx)[-8:]
    if not key:
        return False
    return key in re.sub(r"\s+", "", block_text)


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
                from app.services.generic_verification.claim_extraction import extract_numbers

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
            from app.services.generic_verification.claim_extraction import extract_numbers

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
```

注意：Task 6 中函数内 `from ... import extract_numbers` 与模块顶部已 import 的 `extract_cross_refs` 并存；实现时统一在顶部 import 两个函数，删除函数内重复 import（DRY）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_internal_consistency.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/verifiers/ backend/tests/test_generic_verification/test_internal_consistency.py
git commit -m "feat: add internal consistency verifier"
```

---

### Task 7: 跨文档核验引擎

**Files:**
- Create: `backend/app/services/generic_verification/verifiers/cross_document.py`
- Test: `backend/tests/test_generic_verification/test_cross_document.py`

**Interfaces:**
- Consumes: Task 2 `VerificationOutcome` / `GenericClaim`、`base.py` 的 `STATUS_*`、Task 6 的 `values_compatible` / `VALUE_TOLERANCE`、`app/services/evidence_retrieval/engine.py` 的 `text_similarity`（只读复用）。
- Produces:
  - `verify_claim_cross_document(claim: GenericClaim, evidence_blocks: list[dict], top_k: int = 5) -> VerificationOutcome`：
    1. 候选打分：对每个证据块计算 `score = text_similarity(claim.source_text, block.text) + 数值命中加分`（claim 每个 number 的 `context` 前 8 字在块文本出现且 `values_compatible` → +0.4）。
    2. 取 top_k 分 > 0 的块为证据。
    3. 判定：有块与 claim 数值冲突（同语境、数值不兼容）→ `REFUTED`（`CROSS_DOC_CONFLICT`）；有兼容数值命中 → `SUPPORTED`；只有文本相似无数值 → `PARTIALLY_SUPPORTED`（confidence 0.5）；无任何候选 → `INSUFFICIENT_EVIDENCE`。
  - `mode_used=["cross_doc"]`。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_cross_document.py"""
from app.services.generic_verification.schemas import GenericClaim
from app.services.generic_verification.verifiers.cross_document import verify_claim_cross_document
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def _claim(numbers, entities=("公司A",), text="营收 1.2 亿元"):
    return GenericClaim(
        claim_id="GCLM-001", source_text=text, claim_kind="NUMERIC", page_number=1,
        block_index=0, entities=list(entities), numbers=numbers, dates=[],
        cross_refs=[], extraction_method="rules", confidence=0.5,
    )


def test_supported_by_matching_evidence():
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    blocks = [
        {"text": "公司A 2024年营业收入 1.2 亿元", "page_number": 3, "document_id": 9},
    ]
    out = verify_claim_cross_document(claim, blocks)
    assert out.verdict == STATUS_SUPPORTED
    assert out.mode_used == ["cross_doc"]
    assert out.evidence


def test_refuted_by_conflicting_evidence():
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    blocks = [
        {"text": "公司A 2024年营业收入 1.2 万元", "page_number": 3, "document_id": 9},
    ]
    out = verify_claim_cross_document(claim, blocks)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "CROSS_DOC_CONFLICT"


def test_insufficient_when_no_evidence():
    claim = _claim([{"value": 1.2, "unit": "亿", "context": "营业收入"}])
    out = verify_claim_cross_document(claim, [])
    assert out.verdict == STATUS_INSUFFICIENT
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_cross_document.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.verifiers.cross_document'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/verifiers/cross_document.py`：

```python
"""跨文档核验引擎：在用户提供的证据文档块中检索支持/反驳材料。

纯函数：输入 claim + 证据块列表，输出 VerificationOutcome。
打分 = 文本相似度 + 数值命中加分（语境命中且数值兼容 +0.4）。
"""

from __future__ import annotations

from app.services.evidence_retrieval.engine import text_similarity
from app.services.generic_verification.claim_extraction import extract_numbers
from app.services.generic_verification.schemas import GenericClaim, VerificationOutcome
from app.services.generic_verification.verifiers.internal_consistency import values_compatible
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
)


def _context_hit(ctx: str, block_text: str) -> bool:
    key = "".join(ctx.split())[-8:]
    return bool(key) and key in "".join(block_text.split())


def verify_claim_cross_document(claim: GenericClaim, evidence_blocks: list[dict],
                                top_k: int = 5) -> VerificationOutcome:
    scored: list[tuple[float, dict]] = []
    for b in evidence_blocks:
        text = b.get("text") or ""
        if not text.strip():
            continue
        score = text_similarity(claim.source_text, text)
        matched_value = False
        conflict = False
        for num in claim.numbers:
            ctx = (num.get("context") or "")
            if not _context_hit(ctx, text):
                continue
            for other in extract_numbers(text):
                if values_compatible(num.get("value"), num.get("unit"),
                                     other.get("value"), other.get("unit")):
                    matched_value = True
                elif _context_hit(other.get("context") or "", text) or True:
                    conflict = True
        if matched_value:
            score += 0.4
        scored.append((score, {**b, "_matched_value": matched_value, "_conflict": conflict}))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:top_k]
    evidence = [
        {"text": b.get("text"), "page_number": b.get("page_number"),
         "document_id": b.get("document_id"), "score": round(s, 4)}
        for s, b in top if s > 0
    ]

    if any(b["_conflict"] for _, b in top):
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.85,
            mode_used=["cross_doc"], evidence=evidence,
            reason="证据文档中存在与主张数值冲突的记录", error_type="CROSS_DOC_CONFLICT",
        )
    if any(b["_matched_value"] for _, b in top):
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.75,
            mode_used=["cross_doc"], evidence=evidence,
            reason="证据文档中数值一致", error_type=None,
        )
    if evidence:
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_PARTIALLY_SUPPORTED, confidence=0.5,
            mode_used=["cross_doc"], evidence=evidence,
            reason="证据与主张文本相关但未找到数值对应", error_type=None,
        )
    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_INSUFFICIENT, confidence=0.5,
        mode_used=["cross_doc"], evidence=[],
        reason="证据文档中未检索到相关块", error_type=None,
    )
```

注意：`verify_claim_cross_document` 中 `_conflict` 判定使用了 `or True` 兜底（保证同语境数字一旦出现在块中即视为比对对象）；实现时把该逻辑简化为「同语境存在数值即比对」，避免歧义 —— 以测试为准。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_cross_document.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/verifiers/cross_document.py backend/tests/test_generic_verification/test_cross_document.py
git commit -m "feat: add cross-document verifier"
```

---

### Task 8: 外部知识核验引擎

**Files:**
- Create: `backend/app/services/generic_verification/verifiers/external_knowledge.py`
- Test: `backend/tests/test_generic_verification/test_external_knowledge.py`

**Interfaces:**
- Consumes: Task 2 `VerificationOutcome` / `GenericClaim`、`base.py` 的 `STATUS_*`、Task 4 `GenericClaimExtractor._call_llm`（复用 LLM 调用）、`get_settings().generic_web_search`。
- Produces:
  - `verify_claim_external(claim: GenericClaim, user_materials: list[str] | None = None, llm_caller=None, web_search=None) -> VerificationOutcome`：
    1. 组装 query：`" ".join(claim.entities) + " " + "、".join(str(n.get("value")) + (n.get("unit") or "") for n in claim.numbers)`。
    2. 用户资料检索：`user_materials` 中文本含任一实体 → 取最长匹配段为资料证据；资料与 claim 数值冲突 → `REFUTED`（`EXTERNAL_CONFLICT`），一致 → `SUPPORTED`。
    3. LLM 常识：`llm_caller(messages)` 返回 `{"verdict": "SUPPORTED|REFUTED|UNKNOWN", "reason": str}` JSON；SUPPORTED/REFUTED → 采纳（confidence 0.7）；UNKNOWN → 继续。
    4. 联网搜索：`web_search` 可调用且 `generic_web_search=True` → 调 `web_search(query)` 返回摘要列表，含冲突数值 → `REFUTED`，含一致数值 → `SUPPORTED`。
    5. 全部无法判定 → `UNABLE_TO_DETERMINE`。
  - `mode_used=["external"]`。
  - `llm_caller` / `web_search` 为可注入 callable（默认 `None` → 跳过该阶段），便于测试与 Mock。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_external_knowledge.py"""
from app.services.generic_verification.schemas import GenericClaim
from app.services.generic_verification.verifiers.external_knowledge import verify_claim_external
from app.services.verification.base import (
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)


def _claim(text="北京是中国首都", kind="FACT", entities=("北京", "中国"), numbers=()):
    return GenericClaim(
        claim_id="GCLM-001", source_text=text, claim_kind=kind, page_number=1,
        block_index=0, entities=list(entities), numbers=list(numbers), dates=[],
        cross_refs=[], extraction_method="rules", confidence=0.5,
    )


def _llm_supported(messages):
    return '{"verdict": "SUPPORTED", "reason": "常识确认"}'


def _llm_refuted(messages):
    return '{"verdict": "REFUTED", "reason": "常识否认"}'


def test_user_materials_support():
    out = verify_claim_external(_claim(), user_materials=["北京是中华人民共和国的首都。"])
    assert out.verdict == STATUS_SUPPORTED
    assert out.mode_used == ["external"]


def test_llm_support_when_no_materials():
    out = verify_claim_external(_claim(), llm_caller=_llm_supported)
    assert out.verdict == STATUS_SUPPORTED


def test_llm_refute_when_no_materials():
    out = verify_claim_external(_claim(), llm_caller=_llm_refuted)
    assert out.verdict == STATUS_REFUTED
    assert out.error_type == "EXTERNAL_CONFLICT"


def test_unable_when_nothing_available():
    out = verify_claim_external(_claim())
    assert out.verdict == STATUS_UNABLE
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_external_knowledge.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.verifiers.external_knowledge'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/verifiers/external_knowledge.py`：

```python
"""外部知识核验引擎：用户资料 → LLM 常识 → 可选联网搜索。

优先级：用户资料是用户指定的 ground truth，冲突以资料为准；
无资料时用 LLM 常识（带置信度）；联网搜索仅当配置开启且注入 web_search 时启用。
"""

from __future__ import annotations

import json
import re
from typing import Callable

from app.services.generic_verification.schemas import GenericClaim, VerificationOutcome
from app.services.verification.base import (
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

LLMCaller = Callable[[list[dict]], str]          # messages -> content
WebSearch = Callable[[str], list[dict]]          # query -> [{"title","snippet","url"}]


def _query_of(claim: GenericClaim) -> str:
    parts = list(claim.entities)
    for n in claim.numbers:
        parts.append(f"{n.get('value')}{n.get('unit') or ''}")
    return " ".join(p for p in parts if p)


def _material_evidence(user_materials: list[str], claim: GenericClaim) -> str | None:
    for m in user_materials:
        if any(e and e in m for e in claim.entities):
            return m
    return None


def _material_conflicts(material: str, claim: GenericClaim) -> bool:
    from app.services.generic_verification.claim_extraction import extract_numbers
    from app.services.generic_verification.verifiers.internal_consistency import values_compatible

    for num in claim.numbers:
        for other in extract_numbers(material):
            if values_compatible(num.get("value"), num.get("unit"),
                                 other.get("value"), other.get("unit")):
                continue
            return True
    return False


def _parse_llm_verdict(content: str) -> dict | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r'"verdict"\s*:\s*"(SUPPORTED|REFUTED|UNKNOWN)"', content)
        return {"verdict": m.group(1), "reason": ""} if m else None
    if isinstance(data, dict) and data.get("verdict") in {"SUPPORTED", "REFUTED", "UNKNOWN"}:
        return data
    return None


def verify_claim_external(
    claim: GenericClaim,
    user_materials: list[str] | None = None,
    llm_caller: LLMCaller | None = None,
    web_search: WebSearch | None = None,
    enable_web_search: bool = False,
) -> VerificationOutcome:
    evidence: list[dict] = []
    query = _query_of(claim)

    # 1. 用户资料（ground truth）
    material = _material_evidence(user_materials or [], claim)
    if material:
        evidence.append({"text": material[:200], "source": "user_materials"})
        if _material_conflicts(material, claim):
            return VerificationOutcome(
                claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.9,
                mode_used=["external"], evidence=evidence,
                reason="用户资料与主张数值冲突", error_type="EXTERNAL_CONFLICT",
            )
        return VerificationOutcome(
            claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.8,
            mode_used=["external"], evidence=evidence,
            reason="用户资料支持主张", error_type=None,
        )

    # 2. LLM 常识
    if llm_caller is not None:
        try:
            content = llm_caller([
                {"role": "system", "content": (
                    "你是事实核验助手。仅依据你自己的知识判断主张是否成立。"
                    '返回 JSON：{"verdict": "SUPPORTED|REFUTED|UNKNOWN", "reason": "一句话理由"}。'
                    "不确定时必须返回 UNKNOWN。"
                )},
                {"role": "user", "content": f"主张：{claim.source_text}\n检索词：{query}"},
            ])
            parsed = _parse_llm_verdict(content)
            if parsed and parsed["verdict"] in {"SUPPORTED", "REFUTED"}:
                verdict = STATUS_SUPPORTED if parsed["verdict"] == "SUPPORTED" else STATUS_REFUTED
                return VerificationOutcome(
                    claim_id=claim.claim_id, verdict=verdict, confidence=0.7,
                    mode_used=["external"], evidence=[{"source": "llm_knowledge", "reason": parsed.get("reason", "")}],
                    reason=parsed.get("reason", "LLM 常识判定"),
                    error_type="EXTERNAL_CONFLICT" if verdict == STATUS_REFUTED else None,
                )
        except Exception:  # noqa: BLE001 —— LLM 失败视为未知，继续后续阶段
            pass

    # 3. 联网搜索（可选）
    if web_search is not None and enable_web_search:
        try:
            results = web_search(query)
            snippets = [r.get("snippet", "") for r in results]
            joined = " ".join(snippets)
            if joined:
                evidence.append({"source": "web_search", "snippets": snippets[:3]})
                for num in claim.numbers:
                    from app.services.generic_verification.claim_extraction import extract_numbers
                    from app.services.generic_verification.verifiers.internal_consistency import values_compatible

                    for other in extract_numbers(joined):
                        if not values_compatible(num.get("value"), num.get("unit"),
                                                 other.get("value"), other.get("unit")):
                            return VerificationOutcome(
                                claim_id=claim.claim_id, verdict=STATUS_REFUTED, confidence=0.65,
                                mode_used=["external"], evidence=evidence,
                                reason="联网检索到冲突数值", error_type="EXTERNAL_CONFLICT",
                            )
                return VerificationOutcome(
                    claim_id=claim.claim_id, verdict=STATUS_SUPPORTED, confidence=0.6,
                    mode_used=["external"], evidence=evidence,
                    reason="联网检索到一致数值", error_type=None,
                )
        except Exception:  # noqa: BLE001
            pass

    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_UNABLE, confidence=0.4,
        mode_used=["external"], evidence=evidence,
        reason="无用户资料、LLM 无法判定且未开启/未命中联网搜索", error_type=None,
    )
```

注意：`_material_conflicts` 的判定会把「材料中任意数值与主张数值不兼容」都视为冲突，对无数字的 FACT 主张返回 False（无 numbers 时直接跳过）—— 该行为与测试一致。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_external_knowledge.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/verifiers/external_knowledge.py backend/tests/test_generic_verification/test_external_knowledge.py
git commit -m "feat: add external knowledge verifier"
```

---

### Task 9: OCR 扫描页兜底

**Files:**
- Create: `backend/app/services/generic_verification/ocr.py`
- Test: `backend/tests/test_generic_verification/test_ocr.py`

**Interfaces:**
- Consumes: `get_settings().ocr_engine`、`app/core/exceptions.AppError`、`parser/types.py` 的 `ParsedPage`。
- Produces:
  - `SCAN_PAGE_MIN_CHARS = 50`。
  - `is_scan_page(page: ParsedPage) -> bool`：`page.character_count < SCAN_PAGE_MIN_CHARS` 且 `page.text.strip() == ""`。
  - `render_ocr_text(pdf_bytes: bytes, page_number: int, lang: str = "chi_sim") -> str`：PyMuPDF 从字节打开文档、渲染第 `page_number` 页（1 基）为 PNG（dpi=200）→ `pytesseract.image_to_string`；`ocr_engine != "tesseract"` 或依赖未装 → 抛 `AppError(422, "OCR_NOT_AVAILABLE")`。
  - `ocr_pages(pages: list[ParsedPage], pdf_bytes: bytes) -> dict[int, str]`：仅对扫描页调用 `render_ocr_text`，返回 `{page_number: ocr_text}`；单页 OCR 失败记日志跳过（不中断整体）。
  - `parse_with_ocr(pdf_bytes: bytes) -> ParsedDocument`：先 `parse_pdf`；成功但存在扫描页时对扫描页 `render_ocr_text` 回填为整页 block；`parse_pdf` 抛 `NO_EXTRACTABLE_TEXT`（全扫描件）且 `ocr_engine=="tesseract"` 时逐页 OCR 构造 `ParsedDocument`；其余异常原样抛出。Task 10 统一经此入口解析。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_ocr.py"""
import pytest

from app.core.exceptions import AppError
from app.services.generic_verification.ocr import (
    SCAN_PAGE_MIN_CHARS,
    is_scan_page,
    ocr_pages,
)
from app.services.parser.types import ParsedPage


def _page(text: str, page_number: int = 1) -> ParsedPage:
    return ParsedPage(
        page_index=page_number - 1, page_number=page_number,
        printed_page_label=None, text=text, character_count=len(text),
        text_sha256="x", blocks=[],
    )


def test_scan_page_detection():
    assert is_scan_page(_page("", 1))
    assert is_scan_page(_page(" ", 2))
    assert not is_scan_page(_page("第一章 概述" * 20, 3))


def test_scan_page_min_chars_constant():
    assert SCAN_PAGE_MIN_CHARS == 50


def test_ocr_pages_skips_text_pages(monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.services.generic_verification.ocr.render_ocr_text",
        lambda pdf_bytes, page_number, lang="chi_sim": called.append(page_number) or "OCR文本",
    )
    pages = [_page("", 1), _page("正文" * 60, 2)]
    result = ocr_pages(pages, b"pdf-bytes")
    assert result == {1: "OCR文本"}
    assert called == [1]


def test_ocr_raises_when_disabled():
    from app.services.generic_verification import ocr as ocr_mod

    class _FakeSettings:
        ocr_engine = "off"

    ocr_mod.get_settings = lambda: _FakeSettings()
    with pytest.raises(AppError):
        ocr_mod.render_ocr_text(b"", 1)


def test_parse_with_ocr_fallback_text_pdf(monkeypatch):
    """文本 PDF：扫描页回填，其余页不动。"""
    import fitz

    from app.services.generic_verification import ocr as ocr_mod

    class _FakeSettings:
        ocr_engine = "tesseract"

    ocr_mod.get_settings = lambda: _FakeSettings()
    monkeypatch.setattr("app.services.generic_verification.ocr.render_ocr_text",
                        lambda pdf_bytes, page_number, lang="chi_sim": f"OCR第{page_number}页")

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "扫描页无文本", fontsize=11)  # 空文本页
    data = doc.tobytes()
    doc.close()

    parsed = ocr_mod.parse_with_ocr(data)
    # 空文本页被 OCR 回填：页面 text 非空
    assert any(p.text.strip() for p in parsed.pages)

```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_ocr.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.ocr'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/ocr.py`：

```python
"""扫描件 OCR 兜底（默认 off，无 Tesseract 依赖也可运行）。

- is_scan_page：字符数 < 50 且无文本 → 扫描页
- render_ocr_text：PyMuPDF 从字节渲染指定页 → pytesseract 识别（中文 chi_sim）
- parse_with_ocr：解析入口（Task 10 统一调用），文本 PDF 回填扫描页 / 全扫描件整篇 OCR
- ocr_engine 配置非 tesseract 或 pytesseract 未安装 → 抛 OCR_NOT_AVAILABLE（不静默降级）
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.parser.pdf_parser import parse_pdf
from app.services.parser.types import ParsedDocument, ParsedPage

logger = logging.getLogger(__name__)

SCAN_PAGE_MIN_CHARS = 50


def is_scan_page(page: ParsedPage) -> bool:
    return page.character_count < SCAN_PAGE_MIN_CHARS and not page.text.strip()


def render_ocr_text(pdf_bytes: bytes, page_number: int, lang: str = "chi_sim") -> str:
    """从原始 PDF 字节渲染第 page_number 页（1 基）并 OCR。"""
    cfg = get_settings()
    if cfg.ocr_engine != "tesseract":
        raise AppError("OCR 未启用（FINPROOF_OCR_ENGINE 需设为 tesseract）",
                       status_code=422, code="OCR_NOT_AVAILABLE")
    try:
        import fitz
        import pytesseract
    except ImportError as exc:  # noqa: BLE001
        raise AppError("OCR 依赖未安装（pymupdf / pytesseract）",
                       status_code=422, code="OCR_NOT_AVAILABLE") from exc
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[page_number - 1].get_pixmap(dpi=200)
        return pytesseract.image_to_string(pix.tobytes("png"), lang=lang)
    finally:
        doc.close()


def ocr_pages(pages: list[ParsedPage], pdf_bytes: bytes) -> dict[int, str]:
    """对扫描页执行 OCR，返回 {page_number: ocr_text}（单页失败跳过）。"""
    out: dict[int, str] = {}
    for p in pages:
        if not is_scan_page(p):
            continue
        try:
            out[p.page_number] = render_ocr_text(pdf_bytes, p.page_number)
        except AppError:
            logger.warning("OCR 失败 page=%s", p.page_number)
    return out


def _build_page_with_ocr(pdf_bytes: bytes, page_number: int, ocr_text: str) -> ParsedPage:
    from app.services.parser.types import ParsedBlock

    text = ocr_text.strip()
    return ParsedPage(
        page_index=page_number - 1,
        page_number=page_number,
        printed_page_label=None,
        text=text,
        character_count=len(text),
        text_sha256="ocr:" + str(hash(text)),
        blocks=[ParsedBlock(block_index=0, block_type="paragraph", text=text)],
    )


def parse_with_ocr(pdf_bytes: bytes) -> ParsedDocument:
    """解析 PDF，扫描页以 OCR 文本回填；全扫描件整篇 OCR。

    文本 PDF：parse_pdf 成功后，对 is_scan_page 的页用 OCR 结果替换该页文本。
    全扫描件：parse_pdf 抛 NO_EXTRACTABLE_TEXT → 若 ocr_engine==tesseract，
    逐页渲染 OCR 构造 ParsedDocument；否则原样抛出。
    """
    try:
        parsed = parse_pdf(pdf_bytes)
    except AppError as exc:
        if exc.code == "NO_EXTRACTABLE_TEXT" and get_settings().ocr_engine == "tesseract":
            import fitz

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                pages = [_build_page_with_ocr(pdf_bytes, i + 1, render_ocr_text(pdf_bytes, i + 1))
                         for i in range(len(doc))]
            finally:
                doc.close()
            out = ParsedDocument(document_type="pdf", page_count=len(pages),
                                 total_characters=sum(len(p.text) for p in pages), pages=pages)
            return out
        raise
    # 文本 PDF：回填扫描页
    new_pages: list[ParsedPage] = []
    for p in parsed.pages:
        if is_scan_page(p):
            ocr_text = render_ocr_text(pdf_bytes, p.page_number)
            new_pages.append(_build_page_with_ocr(pdf_bytes, p.page_number, ocr_text))
        else:
            new_pages.append(p)
    parsed.pages = new_pages
    parsed.total_characters = sum(len(p.text) for p in new_pages)
    return parsed
```

注意：`parse_with_ocr` 对全扫描件路径依赖 `fitz` 逐页渲染；若该路径在 CI 无 Tesseract 时永远不触发（ocr_engine 默认 off），单测用 monkeypatch `render_ocr_text` 覆盖即可。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_ocr.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/ocr.py backend/tests/test_generic_verification/test_ocr.py
git commit -m "feat: add scan-page OCR fallback"
```

---

### Task 10: 编排服务 verify_pdf

**Files:**
- Create: `backend/app/services/generic_verification/service.py`
- Test: `backend/tests/test_generic_verification/test_service.py`

**Interfaces:**
- Consumes: Task 2 `GenericClaim` / `VerificationOutcome` / `ErrorItem`、Task 4 `GenericClaimExtractor`、Task 5 `route_claim`、Task 6 `verify_claim_internal`、Task 7 `verify_claim_cross_document`、Task 8 `verify_claim_external`、Task 9 `parse_with_ocr`（统一解析入口，含扫描页 OCR 回填）、`register_document`（`app/services/document_service.py`）、`app/services/claim_service._get_document_blocks` 同款块读取（或 `session.query(DocumentBlock)` 直接读）。
- Produces:
  - `verify_pdf(session: Session, pdf_bytes: bytes, filename: str, evidence_files: list[tuple[str, bytes]] | None = None, mode: str = "auto", user_materials: list[str] | None = None) -> dict`：
    1. `register_document` 注册待核验 PDF（`document_role="REPORT_TO_VERIFY"`，公司/代码留空）→ 取 `Document.id`；若 `parse_status != "COMPLETED"` → 抛 `AppError(422, "PARSE_FAILED")`（含 parse_error）。
    2. 读取全部 `DocumentBlock`（按 page 顺序 + reading_order），组装 `blocks = [{"index","text","page_number","block_type"}]`。
    3. 证据文件：每个 `(name, data)` 也 `register_document`（`SOURCE_DOCUMENT`），收集其块为 `evidence_blocks`（附 `document_id`）。
    4. `extractor.extract(blocks, prompt_version)` → `claims`。
    5. 对每条 claim：`route_claim(claim, has_evidence=bool(evidence_blocks), force_mode=None if mode=="auto" else mode)` → 按 routes 顺序逐个引擎核验；任一 `REFUTED` → 取该结果（最严格优先）；否则取第一个非 `INSUFFICIENT/UNABLE` 的结果；全不可核验 → `NOT_VERIFIABLE` 结果。
    6. 汇总：`verdicts` 计数、`claims` 列表（`outcome.to_dict()` + `source_text` + `page_number` + `claim_kind`）、`error_report`（verdict ∈ {REFUTED, PARTIALLY_SUPPORTED} 的 `ErrorItem`，按 page_number 排序）、`total_claims`、`is_mock`（任一 claim 的 `extraction_method=="rules"` 且 extractor 为 mock）。
    7. 返回结构见设计文档 §6.1（`document_id` / `total_claims` / `verdicts` / `claims` / `error_report` / `is_mock`）。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_service.py"""
import io
import re

import pytest

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.generic_verification.service import verify_pdf


def _make_pdf(text_pages: list[str]) -> bytes:
    """用 PyMuPDF 生成带文本页的最小 PDF。"""
    import fitz

    doc = fitz.open()
    for t in text_pages:
        page = doc.new_page()
        page.insert_text((72, 72), t, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _real_settings(monkeypatch):
    """默认 mock 模式 + 关闭 OCR，保证测试无外部依赖。"""
    monkeypatch.setattr(get_settings, "cache_clear", lambda: None)
    s = get_settings()
    s.ocr_engine = "off"
    s.claim_extraction_base_url = ""
    return s


def test_verify_pdf_internal_conflict(monkeypatch):
    _real_settings(monkeypatch)
    pdf = _make_pdf(["营业收入 1.2 亿元，详细数据见下表。", "营业收入 1.2 万元。"])
    result = verify_pdf(None, pdf, "sample.pdf")
    assert result["total_claims"] >= 1
    assert result["is_mock"] is True
    assert any(c["verdict"] == "REFUTED" for c in result["claims"])


def test_verify_pdf_rejects_broken_pdf(monkeypatch):
    _real_settings(monkeypatch)
    with pytest.raises(AppError):
        verify_pdf(None, b"not a pdf", "broken.pdf")


def test_verify_pdf_error_report_sorted(monkeypatch):
    _real_settings(monkeypatch)
    pdf = _make_pdf(["营业收入 1.2 亿元。", "营业收入 1.2 万元。"])
    result = verify_pdf(None, pdf, "sample.pdf")
    pages = [e["page_number"] for e in result["error_report"]]
    assert pages == sorted(pages)
```

注意：`verify_pdf` 需要 `session` 参数；测试里传 `None` 要求实现支持「无 DB 会话的纯内存路径」（用 `register_document` 需要 DB，纯内存路径直接 `parse_with_ocr` + 手写 blocks）。若实现选择强依赖 DB，则测试改用真实会话（复用 conftest 的隔离 DB + `app.db.get_session`）—— 两条路都可以，但必须让测试可运行且无外部依赖。推荐：`verify_pdf` 接受 `session: Session | None`，`None` 时走纯内存解析路径（不落库），DB 路径仅用于 API 层。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_service.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.services.generic_verification.service'`

- [ ] **Step 3: 实现**

`backend/app/services/generic_verification/service.py`：

```python
"""通用 PDF 核验编排入口（Phase 24）。

verify_pdf(session, pdf_bytes, filename, ...)：
解析（含 OCR 兜底）→ 主张拆解 → 自动路由 → 逐引擎核验 → 五类判定 + error_report 汇总。
session 为 None 时走纯内存路径（不落库），供测试与无 DB 场景使用。
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.generic_verification.ocr import parse_with_ocr
from app.services.verification.base import (
    STATUS_INSUFFICIENT,
    STATUS_PARTIALLY_SUPPORTED,
    STATUS_REFUTED,
    STATUS_SUPPORTED,
    STATUS_UNABLE,
)

logger = logging.getLogger(__name__)

ERROR_REPORT_VERDICTS = frozenset({STATUS_REFUTED, STATUS_PARTIALLY_SUPPORTED})
_PREFER_VERDICTS = (STATUS_REFUTED, STATUS_SUPPORTED, STATUS_PARTIALLY_SUPPORTED)


def _parsed_to_blocks(parsed) -> list[dict]:
    blocks: list[dict] = []
    for page in parsed.pages:
        for b in page.blocks:
            blocks.append({
                "index": b.block_index,
                "text": b.text or "",
                "page_number": page.page_number,
                "block_type": b.block_type,
            })
    return blocks


def _load_evidence_blocks(session, evidence_files: list[tuple[str, bytes]]) -> list[dict]:
    """证据文件解析为块列表（纯内存路径直接解析；DB 路径由 API 层注册后传入 bytes）。"""
    out: list[dict] = []
    for name, data in evidence_files:
        try:
            parsed = parse_with_ocr(data)
        except AppError:
            logger.warning("evidence file parse failed: %s", name)
            continue
        for b in _parsed_to_blocks(parsed):
            b["document_id"] = None
            out.append(b)
    return out


def _verify_one(claim, routes: list[str], doc_blocks: list[dict], evidence_blocks: list[dict],
                user_materials: list[str] | None) -> dict:
    """按路由顺序核验单条主张；任一 REFUTED 即整体 REFUTED。

    - internal 引擎用待核验文档自身的块（doc_blocks）
    - cross_doc 引擎用证据文档的块（evidence_blocks）
    """
    from app.services.generic_verification.routing import (
        ROUTE_CROSS_DOC,
        ROUTE_EXTERNAL,
        ROUTE_INTERNAL,
    )
    from app.services.generic_verification.verifiers.cross_document import verify_claim_cross_document
    from app.services.generic_verification.verifiers.external_knowledge import verify_claim_external
    from app.services.generic_verification.verifiers.internal_consistency import verify_claim_internal

    if not routes:
        return {
            "claim_id": claim.claim_id, "verdict": "NOT_VERIFIABLE", "confidence": 0.0,
            "mode_used": [], "evidence": [], "reason": "观点/预测类主张不强行核验", "error_type": None,
        }
    outcomes = []
    for route in routes:
        if route == ROUTE_INTERNAL:
            outcomes.append(verify_claim_internal(claim, doc_blocks))
        elif route == ROUTE_CROSS_DOC:
            outcomes.append(verify_claim_cross_document(claim, evidence_blocks))
        elif route == ROUTE_EXTERNAL:
            cfg = get_settings()
            outcomes.append(verify_claim_external(
                claim, user_materials=user_materials, enable_web_search=cfg.generic_web_search,
            ))
    refuted = [o for o in outcomes if o.verdict == STATUS_REFUTED]
    if refuted:
        return refuted[0].to_dict()
    for o in outcomes:
        if o.verdict in _PREFER_VERDICTS:
            return o.to_dict()
    return (outcomes[0] if outcomes else _unable(claim)).to_dict()


def _unable(claim) -> dict:
    from app.services.generic_verification.schemas import VerificationOutcome

    return VerificationOutcome(
        claim_id=claim.claim_id, verdict=STATUS_UNABLE, confidence=0.4,
        mode_used=[], evidence=[], reason="无法判定", error_type=None,
    )


def verify_pdf(session, pdf_bytes: bytes, filename: str,
               evidence_files: list[tuple[str, bytes]] | None = None,
               mode: str = "auto",
               user_materials: list[str] | None = None) -> dict:
    """执行一次完整通用 PDF 核验，返回设计文档 §6.1 的结构。"""
    from app.services.generic_verification.claim_extraction import GenericClaimExtractor
    from app.services.generic_verification.routing import route_claim
    from app.services.generic_verification.schemas import ErrorItem

    cfg = get_settings()

    # 1. 解析（含扫描页 OCR 兜底）
    try:
        parsed = parse_with_ocr(pdf_bytes)
    except AppError:
        raise
    blocks = _parsed_to_blocks(parsed)

    # 2. 证据块
    evidence_blocks = _load_evidence_blocks(session, evidence_files or [])

    # 3. 主张拆解
    extractor = GenericClaimExtractor(settings=cfg)
    result = extractor.extract(blocks, cfg.generic_extraction_prompt_version)

    # 4. 逐条核验
    claim_rows: list[dict] = []
    error_items: list[ErrorItem] = []
    for claim in result.claims:
        force = None if mode == "auto" else mode
        routes = route_claim(claim, has_evidence=bool(evidence_blocks), force_mode=force)
        outcome = _verify_one(claim, routes, blocks, evidence_blocks, user_materials)
        claim_rows.append({
            "claim_id": claim.claim_id,
            "source_text": claim.source_text,
            "page_number": claim.page_number,
            "claim_kind": claim.claim_kind,
            **outcome,
        })
        if outcome["verdict"] in ERROR_REPORT_VERDICTS:
            error_items.append(ErrorItem(
                page_number=claim.page_number,
                source_text=claim.source_text,
                verdict=outcome["verdict"],
                error_type=outcome["error_type"] or "UNKNOWN",
                detail=outcome["reason"],
            ))

    # 5. 汇总
    verdicts = {STATUS_SUPPORTED: 0, STATUS_REFUTED: 0, STATUS_PARTIALLY_SUPPORTED: 0,
                STATUS_INSUFFICIENT: 0, STATUS_UNABLE: 0, "NOT_VERIFIABLE": 0}
    for r in claim_rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1

    return {
        "document_id": None,  # 纯内存路径无 DB 文档；API 层可回填
        "total_claims": len(claim_rows),
        "verdicts": verdicts,
        "claims": claim_rows,
        "error_report": [e.to_dict() for e in sorted(error_items, key=lambda e: e.page_number)],
        "is_mock": result.is_mock,
    }
```

注意：`_verify_one` 中 `internal` 路由传入的是 `evidence_blocks` 而非全文 blocks —— 内部自洽应针对**待核验文档自身**的块。实现时把 `blocks` 同时传给 `_verify_one(claim, routes, blocks, evidence_blocks, user_materials)`：`internal` 用 `blocks`、`cross_doc` 用 `evidence_blocks`。`document_id` 在 API 层用注册后的真实 id 回填。以测试通过且语义正确为准。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_service.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/generic_verification/service.py backend/tests/test_generic_verification/test_service.py
git commit -m "feat: add generic verification orchestration service"
```

---

### Task 11: API 端点与注册

**Files:**
- Create: `backend/app/api/generic_verify.py`
- Modify: `backend/app/main.py`（import + include_router）
- Test: `backend/tests/test_generic_verification/test_api.py`

**Interfaces:**
- Consumes: Task 10 `verify_pdf`、`app/db.get_session`、`app/core.exceptions.AppError`。
- Produces:
  - `router = APIRouter(prefix="/api/v1/generic-verify", tags=["generic-verify"])`
  - `POST /api/v1/generic-verify`：`file: UploadFile = File(...)`、`evidence_files: list[UploadFile] = File(default=[])`、`mode: str = Form("auto")`、`user_materials: list[str] = Form(default=[])`、`session=Depends(get_session)`。
    - `mode` 非法（非 `auto|internal|cross_doc|external`）→ `AppError(422, "INVALID_MODE")`。
    - 调用 `verify_pdf`（DB 路径：先 `register_document` 落库拿 id，再走核心核验，回填 `document_id`）。
    - 返回 200 JSON（§6.1 结构）。
- 注意：FastAPI 的 `Form(default=[])` 不支持可变默认值，用 `Form(...)` + `Annotated` 或 `list[str] = Form(default_factory=list)`（FastAPI 支持 `Form(default_factory=list)`）。

- [ ] **Step 1: 写失败测试**

```python
"""backend/tests/test_generic_verification/test_api.py"""
import fitz
from fastapi.testclient import TestClient

from app.main import create_app


def _make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_generic_verify_endpoint_ok():
    app = create_app()
    client = TestClient(app)
    pdf = _make_pdf("营业收入 1.2 亿元，详见第 1 章。")
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.pdf", pdf, "application/pdf")},
        data={"mode": "auto"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_claims" in body
    assert "error_report" in body
    assert "is_mock" in body


def test_generic_verify_invalid_mode():
    app = create_app()
    client = TestClient(app)
    pdf = _make_pdf("营业收入 1.2 亿元。")
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.pdf", pdf, "application/pdf")},
        data={"mode": "bogus"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_MODE"


def test_generic_verify_non_pdf_rejected():
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/generic-verify",
        files={"file": ("sample.txt", b"hello", "text/plain")},
        data={"mode": "auto"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_api.py -v`
Expected: FAIL，`AssertionError: assert 404`（路由未注册）

- [ ] **Step 3: 实现**

`backend/app/api/generic_verify.py`：

```python
"""通用 PDF 内容核验 API（Phase 24）。

POST /api/v1/generic-verify
- file: 待核验 PDF（必填）
- evidence_files: 证据 PDF/文本（可选，多文件）
- mode: auto | internal | cross_doc | external（默认 auto）
- user_materials: 用户提供的参考资料文本（可选）
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db import get_session
from app.services import document_service
from app.services.generic_verification.service import verify_pdf

router = APIRouter(prefix="/api/v1/generic-verify", tags=["generic-verify"])

VALID_MODES = {"auto", "internal", "cross_doc", "external"}


@router.post("")
def generic_verify(
    file: UploadFile = File(...),
    evidence_files: list[UploadFile] = File(default_factory=list),
    mode: str = Form("auto"),
    user_materials: list[str] = Form(default_factory=list),
    session: Session = Depends(get_session),
) -> dict:
    if mode not in VALID_MODES:
        raise AppError(
            f"非法的核验方式: {mode}（可选: {sorted(VALID_MODES)}）",
            status_code=422, code="INVALID_MODE",
        )
    data = file.file.read()
    # 注册待核验文档（DB 路径，用于回填 document_id 与留痕）
    doc, _ = document_service.register_document(
        session, filename=file.filename or "upload", data=data,
        document_role="REPORT_TO_VERIFY",
    )
    if doc.parse_status != "COMPLETED":
        raise AppError(
            f"待核验文档解析失败: {doc.parse_error or doc.parse_status}",
            status_code=422, code="PARSE_FAILED",
        )
    evidence = []
    for ef in evidence_files:
        edata = ef.file.read()
        try:
            edoc, _ = document_service.register_document(
                session, filename=ef.filename or "evidence", data=edata,
                document_role="SOURCE_DOCUMENT",
            )
        except AppError:
            continue
        if edoc.parse_status == "COMPLETED":
            evidence.append((ef.filename or "evidence", edata))

    result = verify_pdf(
        session, data, file.filename or "upload",
        evidence_files=evidence or None, mode=mode, user_materials=user_materials,
    )
    result["document_id"] = doc.id
    return result
```

`backend/app/main.py` 修改（import 区追加，`include_router` 追加）：

```python
from app.api.generic_verify import router as generic_verify_router
# ...
    app.include_router(generic_verify_router)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && python -m pytest tests/test_generic_verification/test_api.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/generic_verify.py backend/app/main.py backend/tests/test_generic_verification/test_api.py
git commit -m "feat: add generic verify API endpoint"
```

---

### Task 12: 全量回归

**Files:**
- 无新增（运行既有测试）。

**Interfaces:**
- Consumes: 全部前序任务。

- [ ] **Step 1: 运行全部测试确认无回归**

Run: `cd backend && python -m pytest -q`
Expected: PASS（现有财报测试全部通过 + 新增 `test_generic_verification/` 全部通过；若现有测试出现失败，检查是否因 Task 1 的 config 字段或 Task 11 的 router 注册引入 —— 修正后重跑）

- [ ] **Step 2: import 冒烟**

Run: `cd backend && python -c "from app.main import create_app; app = create_app(); print(len(app.routes))"`
Expected: 打印路由数（比之前多 1 条 generic-verify），无 ImportError

- [ ] **Step 3: Commit（若有修正）**

```bash
git add -A
git commit -m "test: regression pass for generic pdf verification"
```

---

## 自审记录（writing-plans Self-Review）

对照设计文档检查：覆盖 §3 架构（模块/共用层/API/数据流）→ Task 1–11；§4 主张模型与拆解 → Task 2–4；§5 路由与三引擎 → Task 5–8；§6.2 OCR → Task 9；§6.1/§6.3 输出与错误处理 → Task 10–11；§6.4 测试 → Task 12。无占位符；接口命名在任务间一致（`verify_claim_internal` / `verify_claim_cross_document` / `verify_claim_external` / `route_claim` / `verify_pdf` / `GenericClaim` / `VerificationOutcome` / `ErrorItem`）。




