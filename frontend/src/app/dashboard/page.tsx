"use client";

import { useState } from "react";

type ReliabilityScore = {
  overall_reliability: number;
  hallucination_detection_rate: number;
  evidence_coverage: number;
  reasoning_accuracy: number;
  risk_detection_rate: number;
  benchmark_accuracy: number;
  red_team_reliability: number;
  arena_score: number;
  samples: number;
};

type IntelligenceOverview = {
  companies_analyzed: number;
  claims_verified: number;
  risk_findings: number;
  evidence_chains: number;
  research_sessions: number;
  committee_runs: number;
  memos_generated: number;
  top_companies: { company: string; sessions: number }[];
};

type RiskItem = {
  risk_id: string;
  company: string;
  risk_type: string;
  level: string; // LOW / MEDIUM / HIGH
  description: string;
  status: string; // OPEN / RESOLVED / REVIEW
  evidence_count: number;
  detected_at?: string;
};

type RiskMonitoring = {
  current_risks: RiskItem[];
  unresolved_reviews: number;
  monitoring_alerts: number;
  historical_change: Record<string, number>;
  total_risks: number;
};

type AgentPerformance = {
  analyst_performance: number;
  skeptic_detection_rate: number;
  auditor_accuracy: number;
  agent_score: number;
  arena_runs: number;
  simulation_runs: number;
  fin_agent_score_mean: number;
  winner_distribution: Record<string, number>;
};

type EvidenceNode = {
  node_id: string;
  entity_type: string; // company / business / metric / evidence
  label: string;
  weight: number;
};

type EvidenceEdge = { source: string; target: string; relation: string };

type EvidenceGraph = {
  nodes: EvidenceNode[];
  edges: EvidenceEdge[];
  companies: number;
  metrics: number;
  evidence_count: number;
};

type AuditEvent = {
  event_id: string;
  user: string;
  action: string;
  timestamp?: string;
  model_version?: string;
  rule_version?: string;
  evidence_used?: number;
  detail?: string;
};

type AuditTimeline = {
  events: AuditEvent[];
  total_events: number;
  distinct_users: number;
  distinct_actions: number;
};

type Dashboard = {
  governance_id: string;
  generated_at?: string;
  reliability: ReliabilityScore;
  intelligence: IntelligenceOverview;
  risk_monitoring: RiskMonitoring;
  agent_performance: AgentPerformance;
  evidence_graph: EvidenceGraph;
  audit_timeline: AuditTimeline;
};

const RISK_COLOR: Record<string, string> = {
  HIGH: "#f87171",
  MEDIUM: "#fbbf24",
  LOW: "#4ade80",
};

const ENTITY_COLOR: Record<string, string> = {
  company: "#38bdf8",
  business: "#a78bfa",
  metric: "#fbbf24",
  evidence: "#4ade80",
};

export default function GovernanceDashboardPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);

  const build = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/governance/dashboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setDash(body);
    } catch (e) {
      setError(`仪表板构建失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  // 首屏自动构建一次
  if (!dash && !loading && !error) {
    build();
  }

  return (
    <main className="page">
      <h1>FinProof AI Reliability Center（Phase 20）</h1>
      <p className="muted">
        Executive AI Governance Dashboard：整合 Phase 0-19 能力，展示 FinProof 如何从 AI 生成内容中发现风险、验证事实、管理 AI 可靠性。
        保持 Evidence First；不输出投资建议、股票推荐或交易。
      </p>

      {error && <p className="bad">{error}</p>}
      {loading && !dash && <p className="muted">构建治理仪表板中…</p>}

      {dash && (
        <>
          <p className="muted" style={{ fontSize: "0.85em" }}>
            Governance ID {dash.governance_id} · 生成于 {dash.generated_at} · 样本数 {dash.reliability.samples}
          </p>

          {/* 第一屏：大卡片 */}
          <h2>① FinProof AI Reliability Center</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 16 }}>
            <BigCard
              title="AI Reliability Score"
              value={dash.reliability.overall_reliability}
              suffix="/100"
              color="#38bdf8"
              sub={`幻觉检出 ${(dash.reliability.hallucination_detection_rate * 100).toFixed(0)}% · 逻辑 ${(dash.reliability.reasoning_accuracy * 100).toFixed(0)}%`}
            />
            <BigCard
              title="Evidence Coverage"
              value={dash.reliability.evidence_coverage * 100}
              suffix="%"
              color="#4ade80"
              sub={`证据链 ${dash.intelligence.evidence_chains} 条 · 公司 ${dash.intelligence.companies_analyzed}`}
            />
            <BigCard
              title="Risk Detection"
              value={dash.reliability.risk_detection_rate * 100}
              suffix="%"
              color="#fbbf24"
              sub={`当前风险 ${dash.risk_monitoring.current_risks.length} · 未决 ${dash.risk_monitoring.unresolved_reviews}`}
            />
            <BigCard
              title="Agent Arena Score"
              value={dash.reliability.arena_score}
              suffix="/100"
              color="#a78bfa"
              sub={`Agent 综合 ${dash.agent_performance.agent_score.toFixed(1)} · Arena ${dash.agent_performance.arena_runs} 次`}
            />
          </div>

          {/* 第二部分：实时风险地图 */}
          <h2>② 实时风险地图</h2>
          <div className="semantic-card" style={{ marginBottom: 16, fontSize: "0.85em" }}>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
              <span>总风险：<strong>{dash.risk_monitoring.total_risks}</strong></span>
              <span>当前：<strong>{dash.risk_monitoring.current_risks.length}</strong></span>
              <span>未决评审：<strong>{dash.risk_monitoring.unresolved_reviews}</strong></span>
              <span>监控 alerts：<strong>{dash.risk_monitoring.monitoring_alerts}</strong></span>
            </div>
            {dash.risk_monitoring.historical_change && Object.keys(dash.risk_monitoring.historical_change).length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <strong>近 7 日历史变化：</strong>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
                  {Object.entries(dash.risk_monitoring.historical_change).map(([d, n]) => (
                    <span key={d} className="muted" style={{ fontSize: "0.85em" }}>
                      {d.slice(5)}: <strong>{n}</strong>
                    </span>
                  ))}
                </div>
              </div>
            )}
            {dash.risk_monitoring.current_risks.length === 0 ? (
              <p className="muted">暂无当前风险条目。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {dash.risk_monitoring.current_risks.slice(0, 20).map((r) => (
                  <div
                    key={r.risk_id}
                    className="verdict-card"
                    style={{ borderLeftColor: RISK_COLOR[r.level] || "#64748b", marginBottom: 0 }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
                      <strong>{r.company} · {r.risk_type}</strong>
                      <span style={{ color: RISK_COLOR[r.level] || "#64748b", fontSize: "0.85em" }}>
                        {r.level} · {r.status} · 证据 {r.evidence_count}
                      </span>
                    </div>
                    <p style={{ margin: "2px 0", fontSize: "0.85em" }}>{r.description}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 第三部分：Agent Performance */}
          <h2>③ Agent Performance</h2>
          <div className="semantic-card" style={{ marginBottom: 16, fontSize: "0.85em" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 12 }}>
              <StatBox label="Analyst performance" value={dash.agent_performance.analyst_performance.toFixed(1)} color="#38bdf8" />
              <StatBox label="Skeptic detection rate" value={`${(dash.agent_performance.skeptic_detection_rate * 100).toFixed(0)}%`} color="#f87171" />
              <StatBox label="Auditor accuracy" value={`${(dash.agent_performance.auditor_accuracy * 100).toFixed(0)}%`} color="#fbbf24" />
              <StatBox label="Agent score" value={dash.agent_performance.agent_score.toFixed(1)} color="#a78bfa" />
              <StatBox label="FinAgent score mean" value={dash.agent_performance.fin_agent_score_mean.toFixed(1)} color="#4ade80" />
              <StatBox label="Arena / Sim runs" value={`${dash.agent_performance.arena_runs} / ${dash.agent_performance.simulation_runs}`} color="#64748b" />
            </div>
            {dash.agent_performance.winner_distribution && Object.keys(dash.agent_performance.winner_distribution).length > 0 && (
              <div>
                <strong>辩论胜负分布：</strong>
                <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
                  {Object.entries(dash.agent_performance.winner_distribution).map(([w, n]) => (
                    <span key={w} className="muted" style={{ fontSize: "0.85em" }}>
                      {w}: <strong>{n}</strong>
                    </span>
                  ))}
                </div>
                <p className="muted" style={{ fontSize: "0.8em", marginTop: 4 }}>仅辩论胜负，非投资建议</p>
              </div>
            )}
          </div>

          {/* 第四部分：Evidence Chain */}
          <h2>④ Evidence Chain</h2>
          <div className="semantic-card" style={{ marginBottom: 16, fontSize: "0.85em" }}>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
              <span>公司：<strong>{dash.evidence_graph.companies}</strong></span>
              <span>指标：<strong>{dash.evidence_graph.metrics}</strong></span>
              <span>证据：<strong>{dash.evidence_graph.evidence_count}</strong></span>
              <span>节点：<strong>{dash.evidence_graph.nodes.length}</strong></span>
              <span>边：<strong>{dash.evidence_graph.edges.length}</strong></span>
            </div>
            {dash.evidence_graph.nodes.length === 0 ? (
              <p className="muted">暂无证据图谱节点。</p>
            ) : (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {dash.evidence_graph.nodes.slice(0, 60).map((n) => (
                  <span
                    key={n.node_id}
                    style={{
                      padding: "2px 8px",
                      borderRadius: 12,
                      fontSize: "0.8em",
                      background: "rgba(56,189,248,0.08)",
                      color: ENTITY_COLOR[n.entity_type] || "#64748b",
                      border: `1px solid ${ENTITY_COLOR[n.entity_type] || "#64748b"}40`,
                    }}
                    title={`${n.entity_type} · ${n.label}`}
                  >
                    {n.entity_type[0].toUpperCase()} · {n.label.length > 16 ? n.label.slice(0, 16) + "…" : n.label}
                  </span>
                ))}
              </div>
            )}
            {dash.evidence_graph.edges.length > 0 && (
              <p className="muted" style={{ fontSize: "0.8em", marginTop: 8 }}>
                关系边 {dash.evidence_graph.edges.length} 条（Company → Business → Metric → Evidence）
              </p>
            )}
          </div>

          {/* 第五部分：Audit Timeline */}
          <h2>⑤ Audit Timeline</h2>
          <div className="semantic-card" style={{ fontSize: "0.85em" }}>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
              <span>总事件：<strong>{dash.audit_timeline.total_events}</strong></span>
              <span>用户：<strong>{dash.audit_timeline.distinct_users}</strong></span>
              <span>动作：<strong>{dash.audit_timeline.distinct_actions}</strong></span>
            </div>
            {dash.audit_timeline.events.length === 0 ? (
              <p className="muted">暂无审计事件。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {dash.audit_timeline.events.slice(0, 30).map((e) => (
                  <div key={e.event_id} style={{ borderLeft: "2px solid #64748b", paddingLeft: 8 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                      <strong>{e.user} · {e.action}</strong>
                      <span className="muted" style={{ fontSize: "0.8em" }}>{e.timestamp}</span>
                    </div>
                    <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>
                      model {e.model_version || "-"} · rule {e.rule_version || "-"} · evidence {e.evidence_used || 0}
                      {e.detail && ` · ${e.detail.slice(0, 60)}`}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ marginTop: 16 }}>
            <button onClick={build} disabled={loading}>
              {loading ? "重建中…" : "重建仪表板"}
            </button>
          </div>
        </>
      )}
    </main>
  );
}

function BigCard({ title, value, suffix, color, sub }: { title: string; value: number; suffix: string; color: string; sub: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="verdict-card" style={{ borderLeftColor: color }}>
      <div className="muted" style={{ fontSize: "0.8em", marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: "1.8em", fontWeight: 700, color }}>
        {pct.toFixed(1)}<span style={{ fontSize: "0.6em", color: "#94a3b8" }}>{suffix}</span>
      </div>
      <div style={{ height: 6, background: "#1e293b", borderRadius: 4, marginTop: 6, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.3s" }} />
      </div>
      <p className="muted" style={{ fontSize: "0.75em", marginTop: 4 }}>{sub}</p>
    </div>
  );
}

function StatBox({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ padding: 8, border: "1px solid #1e293b", borderRadius: 6 }}>
      <div className="muted" style={{ fontSize: "0.75em", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: "1.1em", fontWeight: 700, color }}>{value}</div>
    </div>
  );
}
