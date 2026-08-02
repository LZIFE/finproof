"use client";

import { useState } from "react";

type EntityNetwork = {
  nodes: { id: string; type: string; name: string; label: string }[];
  edges: { source: string; target: string; type: string; label: string; fact_id: string; confidence: number }[];
};

type EvidenceSource = {
  source: string;
  source_label: string;
  fact_count: number;
  facts: { fact_id: string; predicate: string; object_value: unknown; unit: string; period: string; evidence: string; timestamp: string; confidence: number }[];
};

type ConflictFinding = {
  finding_id: string;
  claim_id: string;
  claim: string;
  conflict_type: string;
  graph_facts: Record<string, unknown>[];
  difference: string;
  risk_type: string;
  risk_score: number;
  risk_level: string;
  evidence_trace: { role: string; text: string; source?: string; source_label?: string; timestamp?: string; confidence?: number; value?: number; kw?: string[] }[];
};

type GraphData = {
  document_id: number;
  entity_network: EntityNetwork;
  evidence_sources: EvidenceSource[];
  fact_count: number;
  entity_count: number;
  relationship_count: number;
};

type ConflictData = {
  document_id: number;
  findings: ConflictFinding[];
  conflict_count: number;
  support_count: number;
  overall_risk_score: number;
  overall_risk_level: string;
};

const ENTITY_COLOR: Record<string, string> = {
  COMPANY: "#2563eb",
  BUSINESS: "#16a34a",
  PRODUCT: "#9333ea",
  REGION: "#ea580c",
  COMPETITOR: "#dc2626",
  METRIC: "#0891b2",
  EXECUTIVE: "#ca8a04",
};

const CONFLICT_LABEL: Record<string, string> = {
  CLAIM_VS_FACT: "Claim 与 Fact 冲突",
  BUSINESS_OVERSTATEMENT: "Business 描述夸大",
  COMPETITIVE_NO_EVIDENCE: "Competitive 优势缺证据",
  GROWTH_INSUFFICIENT: "Growth 逻辑不足",
  NO_OPPOSITION: "无冲突/支持",
};

const RISK_STYLE: Record<string, string> = {
  HIGH: "verdict-refuted",
  MEDIUM: "verdict-partial",
  LOW: "verdict-supported",
};

export default function KnowledgeGraphPage() {
  const [documentId, setDocumentId] = useState("1");
  const [auditId, setAuditId] = useState("");
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [conflictData, setConflictData] = useState<ConflictData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildGraph = async () => {
    if (!documentId) return;
    setLoading(true);
    setError(null);
    setGraphData(null);
    setConflictData(null);
    try {
      const body: Record<string, unknown> = { document_id: Number(documentId) };
      if (auditId) body.audit_id = Number(auditId);
      const resp = await fetch("/api/v1/knowledge-graph/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(result));
      // 自动查询图谱
      await fetchGraph();
    } catch (e) {
      setError(`构建知识图谱失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchGraph = async () => {
    try {
      const resp = await fetch(`/api/v1/knowledge-graph/${Number(documentId)}`);
      const result = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(result));
      setGraphData(result);
    } catch (e) {
      setError(`查询知识图谱失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const detectConflicts = async () => {
    if (!documentId) return;
    setLoading(true);
    setError(null);
    setConflictData(null);
    try {
      const resp = await fetch("/api/v1/knowledge-graph/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: Number(documentId) }),
      });
      const result = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(result));
      setConflictData(result);
    } catch (e) {
      setError(`冲突推理失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>金融知识图谱（Phase 10 · Financial Knowledge Graph Engine）</h1>
      <p>
        从 Claims / Evidence / Company Facts 抽取金融实体，构建知识图谱，进行冲突推理。
        <b> 不修改已有 Verification 逻辑。</b>
      </p>

      <div className="form-row">
        <label>
          document_id
          <input value={documentId} onChange={(e) => setDocumentId(e.target.value)} style={{ width: 120 }} />
        </label>
        <label>
          audit_id（可选）
          <input value={auditId} onChange={(e) => setAuditId(e.target.value)} style={{ width: 120 }} />
        </label>
        <button onClick={buildGraph} disabled={!documentId || loading}>
          {loading ? "处理中…" : "构建知识图谱"}
        </button>
        <button onClick={detectConflicts} disabled={!documentId || loading}>
          冲突推理
        </button>
      </div>
      {error && <p className="bad">{error}</p>}

      {/* Entity Network */}
      <h2>① Entity Network（实体网络）</h2>
      {graphData ? (
        <div className="semantic-card">
          <p>
            实体 <strong>{graphData.entity_count}</strong> · 关系{" "}
            <strong>{graphData.relationship_count}</strong> · 事实{" "}
            <strong>{graphData.fact_count}</strong>
          </p>
          <h4>实体（按类型分组）</h4>
          {Object.entries(
            graphData.entity_network.nodes.reduce<Record<string, typeof graphData.entity_network.nodes>>((acc, n) => {
              (acc[n.type] = acc[n.type] || []).push(n);
              return acc;
            }, {})
          ).map(([type, nodes]) => (
            <div key={type}>
              <span style={{ color: ENTITY_COLOR[type] || "#666", fontWeight: 600 }}>● {type}</span>
              <span className="muted"> ({nodes.length})</span>: {nodes.map((n) => n.name).join("、")}
            </div>
          ))}
          <h4>关系</h4>
          <ul>
            {graphData.entity_network.edges.slice(0, 12).map((e, i) => (
              <li key={i}>
                {e.source} —<strong>{e.label}</strong>→ {e.target}
                <span className="muted"> (置信度 {e.confidence.toFixed(2)})</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted">先构建知识图谱。</p>
      )}

      {/* Facts */}
      <h2>② Facts（图谱事实）</h2>
      {graphData && graphData.evidence_sources.length > 0 ? (
        <div className="semantic-card">
          {graphData.evidence_sources.map((src) => (
            <div key={src.source}>
              <h4>
                {src.source_label || src.source} <span className="muted">({src.source})</span>
              </h4>
              <p className="muted">事实数：{src.fact_count}</p>
              <ul>
                {src.facts.slice(0, 5).map((f) => (
                  <li key={f.fact_id}>
                    <strong>{f.predicate}</strong>
                    {f.object_value !== null ? ` = ${String(f.object_value)}${f.unit}` : ""}
                    {f.period ? ` (${f.period})` : ""}
                    <span className="muted"> · 置信度 {(f.confidence * 100).toFixed(0)}% · 时间 {f.timestamp || "—"}</span>
                    {f.evidence && (
                      <div className="muted" style={{ fontSize: "0.85em", marginTop: 4 }}>
                        证据：{f.evidence.slice(0, 120)}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">无事实数据。</p>
      )}

      {/* Evidence Source */}
      <h2>③ Evidence Source（证据来源）</h2>
      {graphData ? (
        <div className="semantic-card">
          <p>共 {graphData.evidence_sources.length} 个证据来源：</p>
          <ul>
            {graphData.evidence_sources.map((src) => (
              <li key={src.source}>
                <strong>{src.source}</strong>（{src.source_label}）— {src.fact_count} 条事实
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted">先构建知识图谱。</p>
      )}

      {/* Conflict */}
      <h2>④ Conflict（冲突推理结论）</h2>
      {conflictData ? (
        <div>
          <div className={`verdict-card ${RISK_STYLE[conflictData.overall_risk_level] || ""}`}>
            <h3>
              Overall Risk：<strong>{conflictData.overall_risk_score}/100</strong>{" "}
              <span className="muted">{conflictData.overall_risk_level}</span>
            </h3>
            <p className="muted">
              冲突 {conflictData.conflict_count} 条 / 支持 {conflictData.support_count} 条 / 共{" "}
              {conflictData.findings.length} 条 Claim
            </p>
          </div>
          {conflictData.findings.map((f) => (
            <div
              key={f.finding_id}
              className={`verdict-card ${
                f.conflict_type === "NO_OPPOSITION" ? RISK_STYLE.LOW : RISK_STYLE[f.risk_level] || ""
              }`}
            >
              <h4>
                {f.finding_id} · {f.claim_id} —{" "}
                <strong>{CONFLICT_LABEL[f.conflict_type] || f.conflict_type}</strong>
              </h4>
              <p>
                <b>Claim：</b>
                {f.claim}
              </p>
              <p>
                <b>Difference：</b>
                {f.difference}
              </p>
              <p>
                <b>Risk：</b>
                {f.risk_type} · {f.risk_score}（{f.risk_level}）
              </p>
              {f.graph_facts.length > 0 && (
                <p className="muted">关联图谱事实：{f.graph_facts.length} 条</p>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">点击"冲突推理"查看 Claim vs Graph Fact 结论。</p>
      )}
    </main>
  );
}
