"""ORM 模型注册：导入本包后 Base.metadata 将包含全部表。"""

from app.models.claim import Claim, ExtractionRun  # noqa: F401
from app.models.document import Document, DocumentBlock, DocumentPage  # noqa: F401
from app.models.evidence import (  # noqa: F401
    EvidenceCandidate,
    EvidenceRetrievalConfig,
    EvidenceRetrievalRun,
)
from app.models.verification import VerificationResultRow, VerificationRun  # noqa: F401
from app.models.audit import AuditReport  # noqa: F401
from app.models.risk import RiskAssessmentRow  # noqa: F401
from app.models.investment import InvestmentMemoRow, InvestmentReviewRow  # noqa: F401
from app.models.intelligence import IntelligenceReportRow  # noqa: F401
from app.models.investment_committee import CommitteeReportRow  # noqa: F401
from app.models.knowledge_graph import KGFactsRow, KGEntityRow, KGRelationshipRow  # noqa: F401
from app.models.benchmark import (  # noqa: F401
    BenchmarkCaseRow,
    BenchmarkResultRow,
    BenchmarkRunRow,
)
from app.models.portfolio import (  # noqa: F401
    PortfolioProjectRow,
    PortfolioRiskSnapshotRow,
)
from app.models.monitoring import (  # noqa: F401
    InvestmentThesisRow,
    MonitoringAlertRow,
)
from app.models.audit_trail import AuditTrailLogRow  # noqa: F401
from app.models.autonomous_agent import (  # noqa: F401
    InvestigationMemoryRow,
    InvestigationRunRow,
    InvestigationStepRow,
)
from app.models.red_team import (  # noqa: F401
    RedTeamCaseRow,
    RedTeamResultRow,
    RedTeamRunRow,
)
from app.models.copilot import CopilotMessageRow, CopilotSessionRow  # noqa: F401
from app.models.financial_reasoning import (  # noqa: F401
    ReasoningResultRow,
    ReasoningRunRow,
)
from app.models.research_agent import (  # noqa: F401
    ResearchSessionRow,
    ResearchTaskRow,
)
from app.models.financial_simulation import (  # noqa: F401
    SimulationRunRow,
    SimulationStepRow,
    SimulationResultRow,
)
from app.models.agent_arena import (  # noqa: F401
    ArenaRunRow,
    ArenaMessageRow,
    ArenaResultRow,
)
from app.models.replay import (  # noqa: F401
    AuditReplayEventRow,
)
from app.models.demo_mode import (  # noqa: F401
    DemoRunRow,
    DemoStepRow,
)
from app.models.reliability_improvement import (  # noqa: F401
    ReliabilityReportRow,
)
