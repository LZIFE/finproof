"""Knowledge Graph API Schema（Phase 10）。"""

from pydantic import BaseModel, Field


class KnowledgeGraphBuildRequest(BaseModel):
    """构建知识图谱请求。

    输入源（任务书 §2）：Claims / Evidence / Company Facts。
    通过 document_id 关联已有数据。
    """

    document_id: int = Field(ge=1)
    audit_id: int | None = Field(default=None, ge=1)
    intelligence_report_id: int | None = Field(default=None, ge=1)


class ConflictDetectRequest(BaseModel):
    """冲突推理请求。"""

    document_id: int = Field(ge=1)
