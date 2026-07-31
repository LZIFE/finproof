"""主张提取 API 的 Pydantic 请求/响应模型（Phase 3）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    ClaimNature,
    ClaimType,
    ComparisonType,
    ExtractionMode,
    ExtractionRunStatus,
    PeriodType,
    ReviewStatus,
    RiskLevel,
    ValueOperator,
)


class ClaimCreate(BaseModel):
    """主张入库前的 Schema（模型输出必须先通过本 Schema 才能入库）。"""

    claim_uid: str = Field(min_length=1, max_length=64)
    extraction_run_id: int
    document_id: int
    source_block_id: int | None = None
    source_page_number: int = Field(default=1, ge=0)
    source_text: str = Field(min_length=1)
    parent_block_id: int | None = None
    parent_sentence_text: str | None = None
    clause_index: int | None = None
    source_span_start: int | None = None
    source_span_end: int | None = None
    normalized_claim: str = Field(min_length=1)
    claim_type: ClaimType
    entity_name: str | None = None
    stock_code: str | None = None
    metric: str | None = None
    metric_code: str | None = None
    reported_value: float | None = None
    reported_value_text: str | None = None
    value_operator: ValueOperator = ValueOperator.EQUAL
    range_min: float | None = None
    range_max: float | None = None
    unit: str | None = None
    currency: str | None = None
    period: str | None = None
    period_type: PeriodType = PeriodType.UNSPECIFIED
    comparison_period: str | None = None
    comparison_type: ComparisonType = ComparisonType.NONE
    scope: str | None = None
    business_segment: str | None = None
    geography: str | None = None
    claim_nature: ClaimNature = ClaimNature.FACT
    risk_level: RiskLevel = RiskLevel.MEDIUM
    risk_reason: str | None = None
    requires_calculation: bool = False
    requires_external_evidence: bool = True
    extraction_method: str = Field(default="RULE_BASED", max_length=30)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    review_status: ReviewStatus = ReviewStatus.PENDING


class ClaimOut(ClaimCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    review_comment: str | None = None
    review_changes: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExtractionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    status: ExtractionRunStatus
    mode: ExtractionMode
    provider: str
    model_name: str | None
    prompt_version: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    input_block_count: int
    candidate_sentence_count: int
    candidate_claim_count: int
    extracted_claim_count: int
    schema_valid_count: int
    duplicate_removed_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime


class RunCreateRequest(BaseModel):
    mode: ExtractionMode = ExtractionMode.MOCK
    force: bool = False


class RunCreateResponse(BaseModel):
    extraction_run_id: int
    document_id: int
    status: ExtractionRunStatus
    mode: ExtractionMode
    extracted_claim_count: int


class ClaimListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    claims: list[ClaimOut]


class ReviewRequest(BaseModel):
    review_status: ReviewStatus
    comment: str | None = None
    # EDITED 时记录修改后的字段（原始系统输出保留在原列，不覆盖）
    changes: dict | None = None
