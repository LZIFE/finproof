"use client";

import { useState } from "react";

type ReplayEvent = {
  id?: number;
  audit_id: string;
  event_type: string; // claim_event / evidence_event / verification_event / risk_event / agent_event / conclusion_event
  timestamp?: string;
  actor: string; // 来源
  content: string; // 结果
  evidence_reference?: string; // 证据
  source?: string;
  evidence_summary?: string;
  result_summary?: string;
};

type ReplayTimeline = {
  audit_id: string;
  total_events: number;
  created_at?: string;
  events: ReplayEvent[];
  steps: Record<string, ReplayEvent[]>;
  step_order: string[];
  step_labels: Record<string, string>;
  step_icons: Record<string, string>;
};

type ReplayListItem = {
  audit_id: string;
  event_count: number;
  latest_timestamp?: string;
};

const STEP_COLOR: Record<string, string> = {
  claim_event: "#38bdf8",
  evidence_event: "#4ade80",
  verification_event: "#a78bfa",
  risk_event: "#fbbf24",
  agent_event: "#f87171",
  conclusion_event: "#22d3ee",
};

export default function ReplayPage() {
  const [auditId, setAuditId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<ReplayTimeline | null>(null);
  const [replays, setReplays] = useState<ReplayListItem[]>([]);

  const loadReplays = async () => {
    try {
      const r = await fetch("/api/v1/replay?limit=30");
      const body = await r.json();
      if (r.ok) setReplays(body.replays || []);
    } catch {
      /* noop */
    }
  };

  // 首次加载列表
  if (!loading && !timeline && !error && replays.length === 0) {
    loadReplays();
  }

  const fetchReplay = async (id: string) => {
    if (!id) {
      setError("请输入 audit_id");
      return;
    }
    setLoading(true);
    setError(null);
    setTimeline(null);
    try {
      const r = await fetch(`/api/v1/replay/${encodeURIComponent(id)}`);
      const body = await r.json();
      if (!r.ok) throw new Error(JSON.stringify(body));
      setTimeline(body);
      loadReplays();
    } catch (e) {
      setError(`回放查询失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>AI Audit Replay Timeline（Phase 21）</h1>
      <p className="muted">
        将已有 FinProof 审计流程转化为可视化审计回放：AI Claim → Evidence Found → Verification →
        Risk Assessment → Agent Discussion → Final Conclusion。
        每一步显示来源 / 证据 / 结果。**不新增分析能力**，仅展示既有 Evidence/Verification/Risk/Agent Trace。
        不输出投资建议；不修改 Verification/Risk 核心。
      </p>

      {/* 输入区 */}
      <h2>① 选择回放</h2>
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ flex: "2 1 280px" }}>
            audit_id
            <input
              value={auditId}
              onChange={(e) => setAuditId(e.target.value)}
              placeholder="如 ARENA-XXXX 或 RESEARCH-XXXX"
            />
          </label>
          <button onClick={() => fetchReplay(auditId)} disabled={loading}>
            {loading ? "回放中…" : "加载回放"}
          </button>
          <button onClick={loadReplays} disabled={loading}>
            刷新列表
          </button>
        </div>
        {error && <p className="bad">{error}</p>}

        {/* 已有回放列表快捷选择 */}
        {replays.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <strong className="muted" style={{ fontSize: "0.85em" }}>已有回放（{replays.length}）：</strong>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
              {replays.slice(0, 20).map((rp) => (
                <button
                  key={rp.audit_id}
                  onClick={() => { setAuditId(rp.audit_id); fetchReplay(rp.audit_id); }}
                  style={{ fontSize: "0.8em", padding: "2px 8px" }}
                  title={`${rp.event_count} events · ${rp.latest_timestamp}`}
                >
                  {rp.audit_id.length > 22 ? rp.audit_id.slice(0, 22) + "…" : rp.audit_id} ({rp.event_count})
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Timeline */}
      {timeline && (
        <>
          <h2>② Audit Replay Timeline</h2>
          <div className="semantic-card" style={{ marginBottom: 12 }}>
            <p className="muted" style={{ fontSize: "0.85em" }}>
              audit_id <strong>{timeline.audit_id}</strong> · 共 {timeline.total_events} 事件 · 生成于 {timeline.created_at}
            </p>
            {timeline.total_events === 0 ? (
              <p className="bad">无回放事件（该 audit_id 无既有审计数据）。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
                {timeline.step_order.map((et) => {
                  const stepEvents = timeline.steps[et] || [];
                  const color = STEP_COLOR[et] || "#64748b";
                  const icon = timeline.step_icons[et] || "•";
                  const label = timeline.step_labels[et] || et;
                  return (
                    <div
                      key={et}
                      className="verdict-card"
                      style={{ borderLeftColor: color, marginBottom: 0 }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <strong style={{ color }}>
                          {icon} {label}（{et}）
                        </strong>
                        <span className="muted" style={{ fontSize: "0.8em" }}>{stepEvents.length} 条</span>
                      </div>
                      {stepEvents.length === 0 ? (
                        <p className="muted" style={{ fontSize: "0.85em", margin: "2px 0" }}>— 无 —</p>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {stepEvents.map((e, i) => (
                            <div
                              key={`${et}-${e.id ?? i}`}
                              style={{ border: "1px solid #1e293b", borderRadius: 6, padding: 8, fontSize: "0.85em" }}
                            >
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                <strong style={{ color: "#94a3b8" }}>来源：{e.actor || "-"}</strong>
                                <span className="muted" style={{ fontSize: "0.8em" }}>{e.timestamp}</span>
                              </div>
                              <p style={{ margin: "2px 0" }}>{e.content}</p>
                              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4, fontSize: "0.8em" }}>
                                <span className="muted">
                                  证据：{e.evidence_summary || (e.evidence_reference ? "已引用" : "-")}
                                </span>
                                <span className="muted">
                                  结果：{e.result_summary || "-"}
                                </span>
                                {e.source && <span className="muted">模块：{e.source}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 全事件流（扁平视图） */}
          {timeline.total_events > 0 && (
            <>
              <h2>③ 全事件流（{timeline.events.length}）</h2>
              <div className="semantic-card" style={{ fontSize: "0.85em" }}>
                {timeline.events.map((e, i) => (
                  <div key={e.id ?? i} style={{ display: "flex", gap: 8, padding: "4px 0", borderBottom: "1px solid #1e293b" }}>
                    <span style={{ color: STEP_COLOR[e.event_type] || "#64748b", minWidth: 120 }}>
                      {timeline.step_icons[e.event_type] || "•"} {timeline.step_labels[e.event_type] || e.event_type}
                    </span>
                    <span style={{ color: "#94a3b8", minWidth: 140 }}>{e.actor}</span>
                    <span style={{ flex: 1 }}>{e.content.length > 80 ? e.content.slice(0, 80) + "…" : e.content}</span>
                    <span className="muted" style={{ fontSize: "0.85em" }}>{e.timestamp}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}
