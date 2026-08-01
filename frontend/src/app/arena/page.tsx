"use client";

import { useState } from "react";

type EvidenceRef = {
  block_id?: string | number;
  document_id?: string | number;
  page_number?: string | number;
  text?: string;
  evidence_tier?: string;
};

type Viewpoint = {
  viewpoint_id: string;
  claim: string;
  evidence: EvidenceRef[];
  confidence: number;
  metric?: string;
  unsupported: boolean;
};

type Challenge = {
  challenge_id: string;
  target_viewpoint_id: string;
  challenge_type: string;
  counter_claim: string;
  missing_evidence?: string;
  risk?: string;
  evidence: EvidenceRef[];
  risk_score?: number;
  valid: boolean;
};

type AuditorIssue = {
  issue_id: string;
  issue_type: string;
  description: string;
  affected: string;
};

type AuditorReport = {
  audit_score: number;
  issues: AuditorIssue[];
  evidence_coverage: number;
  logical_consistency: number;
  risk_completeness: number;
  valid_challenges: string[];
  invalid_challenges: string[];
};

type ScoreBreakdown = { score: number; notes: string };

type ArenaScore = {
  analyst_quality: ScoreBreakdown;
  skeptic_detection: ScoreBreakdown;
  auditor_reliability: ScoreBreakdown;
  evidence_score: ScoreBreakdown;
  reasoning_score: ScoreBreakdown;
  risk_detection_score: ScoreBreakdown;
  efficiency_score: ScoreBreakdown;
  safety_score: ScoreBreakdown;
  final_arena_score: number;
};

type Message = {
  message_id: string;
  role: string;
  phase: string;
  content: string;
  viewpoints?: Viewpoint[];
  challenges?: Challenge[];
  audit?: AuditorReport | null;
  evidence?: EvidenceRef[];
  timestamp?: string;
};

type ArenaResult = {
  result_id: string;
  run_id: string;
  analyst_viewpoints: Viewpoint[];
  skeptic_challenges: Challenge[];
  auditor_report: AuditorReport | null;
  score: ArenaScore;
  winner: string;
  created_at?: string;
};

type ArenaRun = {
  run_id: string;
  company: string;
  research_question: string;
  phase: string;
  messages: Message[];
  result: ArenaResult | null;
  created_at?: string;
  finished_at?: string;
};

const ROLE_LABEL: Record<string, string> = {
  Analyst: "分析师",
  Skeptic: "质疑者",
  Auditor: "审计师",
  Judge: "评判",
};

const ROLE_COLOR: Record<string, string> = {
  Analyst: "#38bdf8",
  Skeptic: "#f87171",
  Auditor: "#fbbf24",
  Judge: "#4ade80",
};

const CHALLENGE_LABEL: Record<string, string> = {
  "Unsupported Claim": "无依据主张",
  Overstatement: "夸大",
  "Missing Evidence": "缺证据",
  "Contradictory Facts": "事实冲突",
  "Growth Quality Problem": "增长质量",
};

const WINNER_LABEL: Record<string, string> = {
  analyst: "分析师胜",
  skeptic: "质疑者胜",
  tie: "平局",
};

const WINNER_COLOR: Record<string, string> = {
  analyst: "#38bdf8",
  skeptic: "#f87171",
  tie: "#fbbf24",
};

export default function ArenaPage() {
  const [company, setCompany] = useState("美的集团");
  const [question, setQuestion] = useState("美的海外增长是否可持续");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<ArenaRun | null>(null);

  const runArena = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/arena/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company, research_question: question }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setRun(body);
    } catch (e) {
      setError(`竞技失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>Financial AI Agent Arena（Phase 19）</h1>
      <p className="muted">
        多 Agent 金融研究竞技：Analyst 提出观点 → Skeptic 挑战 → Auditor 审计 → Judge 评分。
        保持 Evidence First；不输出投资建议、股票推荐或交易。
      </p>

      {/* ① 启动竞技 */}
      <h2>① 启动竞技</h2>
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ flex: "2 1 200px" }}>
            公司
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label style={{ flex: "3 1 320px" }}>
            研究问题
            <input value={question} onChange={(e) => setQuestion(e.target.value)} />
          </label>
          <button onClick={runArena} disabled={loading}>
            {loading ? "竞技中…" : "启动竞技"}
          </button>
        </div>
        {error && <p className="bad">{error}</p>}
      </div>

      {run && (
        <>
          {/* ② Agent Debate Timeline */}
          <h2>② Agent Debate Timeline（{run.messages.length} 条消息）</h2>
          <div className="semantic-card" style={{ marginBottom: 12 }}>
            <p className="muted" style={{ fontSize: "0.85em" }}>
              Run {run.run_id} · {run.company} ·「{run.research_question}」· 阶段：{run.phase}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
              {run.messages.map((m, i) => (
                <div
                  key={m.message_id}
                  className="verdict-card"
                  style={{ borderLeftColor: ROLE_COLOR[m.role] || "#64748b", marginBottom: 0 }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                    <strong style={{ color: ROLE_COLOR[m.role] || "#64748b" }}>
                      [{i + 1}] {ROLE_LABEL[m.role] || m.role} · {m.phase}
                    </strong>
                    <span className="muted" style={{ fontSize: "0.8em" }}>{m.timestamp}</span>
                  </div>
                  <p style={{ margin: "2px 0", fontSize: "0.9em" }}>{m.content}</p>
                </div>
              ))}
            </div>
          </div>

          {/* ③ Analyst 观点 */}
          {run.result && (
            <>
              <h2>③ Analyst 观点（{run.result.analyst_viewpoints.length}）</h2>
              <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
                {run.result.analyst_viewpoints.map((v) => {
                  const challenged = run.result!.skeptic_challenges.some((c) => c.target_viewpoint_id === v.viewpoint_id);
                  return (
                    <div
                      key={v.viewpoint_id}
                      className="verdict-card"
                      style={{ borderLeftColor: v.unsupported ? "#fbbf24" : challenged ? "#f87171" : "#4ade80", marginBottom: 8 }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <strong>{v.viewpoint_id} · {v.metric || "-"}</strong>
                        <span style={{ color: v.unsupported ? "#fbbf24" : "#4ade80", fontSize: "0.85em" }}>
                          {v.unsupported ? "○ 无证据" : `✓ 证据 ${v.evidence.length}`} · 置信度 {v.confidence}
                        </span>
                      </div>
                      <p style={{ margin: "2px 0" }}>{v.claim}</p>
                      {v.evidence.length > 0 && (
                        <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>
                          证据：{v.evidence.map((e) => `${e.document_id || "?"} p${e.page_number || "?"}`).join("，")}
                        </p>
                      )}
                      {challenged && (
                        <p className="bad" style={{ margin: "2px 0", fontSize: "0.8em" }}>⚠ 被 Skeptic 挑战</p>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* ④ Skeptic 反驳 */}
              <h2>④ Skeptic 反驳（{run.result.skeptic_challenges.length}）</h2>
              <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
                {run.result.skeptic_challenges.length === 0 ? (
                  <p className="muted">无挑战。</p>
                ) : (
                  run.result.skeptic_challenges.map((c) => (
                    <div
                      key={c.challenge_id}
                      className="verdict-card"
                      style={{ borderLeftColor: c.valid ? "#f87171" : "#64748b", marginBottom: 8 }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <strong style={{ color: "#f87171" }}>
                          {c.challenge_id} · {CHALLENGE_LABEL[c.challenge_type] || c.challenge_type}
                        </strong>
                        <span style={{ fontSize: "0.85em" }}>
                          目标 {c.target_viewpoint_id} · {c.valid ? "✓ 成立" : "✗ 不成立"}
                        </span>
                      </div>
                      <p style={{ margin: "2px 0" }}>{c.counter_claim}</p>
                      {c.missing_evidence && <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>缺证据：{c.missing_evidence}</p>}
                      {c.risk && <p style={{ margin: "2px 0", fontSize: "0.8em", color: "#fbbf24" }}>风险：{c.risk}（评分 {c.risk_score}）</p>}
                    </div>
                  ))
                )}
              </div>

              {/* ⑤ Auditor 判断 */}
              {run.result.auditor_report && (
                <>
                  <h2>⑤ Auditor 判断</h2>
                  <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
                    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
                      <span>证据覆盖：<strong>{(run.result.auditor_report.evidence_coverage * 100).toFixed(0)}%</strong></span>
                      <span>逻辑一致：<strong>{(run.result.auditor_report.logical_consistency * 100).toFixed(0)}%</strong></span>
                      <span>风险完整：<strong>{(run.result.auditor_report.risk_completeness * 100).toFixed(0)}%</strong></span>
                      <span>挑战成立：<strong>{run.result.auditor_report.valid_challenges.length}/{run.result.skeptic_challenges.length}</strong></span>
                      <span>审计评分：<strong>{run.result.auditor_report.audit_score.toFixed(1)}</strong></span>
                    </div>
                    {run.result.auditor_report.issues.length > 0 && (
                      <div>
                        <strong>Issues（{run.result.auditor_report.issues.length}）：</strong>
                        <ul style={{ margin: "2px 0", paddingLeft: 18 }}>
                          {run.result.auditor_report.issues.map((i) => (
                            <li key={i.issue_id} className="muted">[{i.issue_type} · {i.affected}] {i.description}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* ⑥ Final Score */}
              {run.result.score && (
                <>
                  <h2>⑥ Final Score</h2>
                  <div className="verdict-card" style={{ borderLeftColor: WINNER_COLOR[run.result.winner] || "#64748b", marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <h3 style={{ margin: 0 }}>Final Arena Score</h3>
                      <span style={{ fontSize: "1.4em", fontWeight: 700, color: "#38bdf8" }}>
                        {run.result.score.final_arena_score.toFixed(1)}
                      </span>
                    </div>
                    <p className="muted" style={{ fontSize: "0.85em" }}>
                      辩论胜负：<strong style={{ color: WINNER_COLOR[run.result.winner] || "#64748b" }}>
                        {WINNER_LABEL[run.result.winner] || run.result.winner}
                      </strong>
                      （仅辩论胜负，非投资建议）
                    </p>
                  </div>

                  <div className="semantic-card" style={{ fontSize: "0.85em" }}>
                    <ScoreRow label="Evidence（30%）" bd={run.result.score.evidence_score} />
                    <ScoreRow label="Reasoning（25%）" bd={run.result.score.reasoning_score} />
                    <ScoreRow label="Risk Detection（25%）" bd={run.result.score.risk_detection_score} />
                    <ScoreRow label="Efficiency（10%）" bd={run.result.score.efficiency_score} />
                    <ScoreRow label="Safety（10%）" bd={run.result.score.safety_score} />
                    <hr style={{ border: "none", borderTop: "1px solid #1e293b", margin: "8px 0" }} />
                    <ScoreRow label="Analyst 质量" bd={run.result.score.analyst_quality} />
                    <ScoreRow label="Skeptic 发现能力" bd={run.result.score.skeptic_detection} />
                    <ScoreRow label="Auditor 可靠性" bd={run.result.score.auditor_reliability} />
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}

function ScoreRow({ label, bd }: { label: string; bd: ScoreBreakdown }) {
  const pct = Math.max(0, Math.min(100, bd.score));
  const color = pct >= 80 ? "#4ade80" : pct >= 50 ? "#fbbf24" : "#f87171";
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
        <span>{label}</span>
        <strong style={{ color }}>{pct.toFixed(1)}</strong>
      </div>
      <div style={{ height: 8, background: "#1e293b", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, transition: "width 0.3s" }} />
      </div>
      <p className="muted" style={{ fontSize: "0.8em", margin: "2px 0" }}>{bd.notes}</p>
    </div>
  );
}
