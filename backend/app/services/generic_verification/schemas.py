"""通用主张与核验结果数据结构（领域无关）。

- GenericClaim：通用主张骨架（数字/日期/实体/交叉引用），无财务 metric/period/scope 字段。
- VerificationOutcome：单条主张核验结果（五类判定 + 实际使用的核验方式）。
- ErrorItem：错误清单条目（仅 REFUTED / PARTIALLY_SUPPORTED 进入清单）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("claim_kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in CLAIM_KINDS:
            raise ValueError(f"invalid claim_kind: {v}")
        return v


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
