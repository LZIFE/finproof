"""ORM 模型注册：导入本包后 Base.metadata 将包含全部表。"""

from app.models.claim import Claim, ExtractionRun  # noqa: F401
from app.models.document import Document, DocumentBlock, DocumentPage  # noqa: F401
from app.models.evidence import (  # noqa: F401
    EvidenceCandidate,
    EvidenceRetrievalConfig,
    EvidenceRetrievalRun,
)
from app.models.verification import VerificationResultRow, VerificationRun  # noqa: F401
