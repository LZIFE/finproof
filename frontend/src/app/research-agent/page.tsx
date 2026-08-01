"use client";

import { useState } from "react";

type EvidenceRef = {
  block_id?: string | number;
  document_id?: string | number;
  page_number?: string | number;
  text?: string;
  final_score?: number;
  evidence_type?: string;
  evidence_tier?: string;
};

type Finding = {
  task_type: string;
  metric: string;
  content: string;
  evidence: EvidenceRef[];
  supported: boolean;
  risk_score?: number;
  risk_level?: string;
  notes?: string;
};

type RiskFinding = {
  risk_type: string;
  source_tool: string;
  content: string;
  evidence: EvidenceRef[];
  risk_score?: number;
  risk_level?: string;
  logical_gap?: string;
};

type ToolCall = {
  tool: string;
  task_type?: string;
  input_summary?: string;
  output_summary?: string;
  evidence_count?: number;
  success?: boolean;
  timestamp?: string;
};

type Memo = {
  company: string;
  stock_code?: string;
  company_overview: string;
  key_facts: Finding[];
  financial_facts: Finding[];
  business_facts: Finding[];
  risk_findings: RiskFinding[];
  evidence_chain: EvidenceRef[];
  open_questions: string[];
  evidence_coverage: number;
  unsupported_claim_rate: number;
  task_completion_rate: number;
  generated_at?: string;
};

type ResearchSession = {
  session_id: string;
  company: string;
  stock_code?: string;
  plan: { company: string; stock_code?: string; tasks: { task_type: string; category: string; objective: string; metric: string }[] } | null;
  phase: string;
  tool_calls: ToolCall[];
  findings: Finding[];
  risk_findings: RiskFinding[];
  memo: Memo | null;
  created_at?: string;
  finished_at?: string;
};

const PHASE_ORDER = ["Planning", "Collecting Evidence", "Analyzing", "Risk Checking", "Memo Generated"];

const PHASE_LABEL: Record<string, string> = {
  Planning: "规划",
  "Collecting Evidence": "收集证据",
  Analyzing: "分析",
  "Risk Checking": "风险检查",
  "Memo Generated": "Memo 已生成",
};

const TASK_LABEL: Record<string, string> = {
  "Company Profile": "企业画像",
  "Financial Overview": "财务摘要",
  "Business Analysis": "业务分析",
  "Risk Discovery": "风险发现",
  "Competition Facts": "竞争事实",
};

const STATUS_COLOR: Record<string, string> = {
  LOW: "#4ade80",
  MEDIUM: "#fbbf24",
  HIGH: "#f87171",
};

export default function ResearchAgentPage() {
  const [company, setCompany] = useState("美的集团");
  const [stockCode, setStockCode] = useState("000333");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<ResearchSession | null>(null);

  const runResearch = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/research/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company, stock_code: stockCode }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setSession(body);
    } catch (e) {
      setError(`研究流程失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const currentPhaseIndex = session ? PHASE_ORDER.indexOf(session.phase) : -1;

  return (
    <main className="page">
      <h1>Autonomous Financial Research Agent（Phase 17）</h1>
      <p className="muted">
        从公司名称/股票代码出发的自主金融研究流程，输出 Evidence First Research Memo。
        仅含事实、证据、风险、待验证事项；不构成投资建议、股票推荐或估值预测。
      </p>

      {/* ① 输入 */}
      <h2>① 启动研究</h2>
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ flex: "2 1 240px" }}>
            公司名称
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 120px" }}>
            股票代码
            <input value={stockCode} onChange={(e) => setStockCode(e.target.value)} />
          </label>
          <button onClick={runResearch} disabled={loading}>
            {loading ? "研究中…" : "启动研究"}
          </button>
        </div>
        {error && <p className="bad">{error}</p>}
      </div>

      {session && (
        <>
          {/* ② Research Progress：Planning → Collecting → Analyzing → Risk Checking → Memo */}
          <h2>② Research Progress</h2>
          <div className="semantic-card" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {PHASE_ORDER.map((ph, i) => {
                const done = i < currentPhaseIndex || session.phase === "Memo Generated";
                const active = i === currentPhaseIndex && session.phase !== "Memo Generated";
                const color = done ? "#4ade80" : active ? "#38bdf8" : "#94a3b8";
                return (
                  <div key={ph} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div
                      style={{
                        padding: "4px 10px",
                        borderRadius: 6,
                        border: `1px solid ${color}`,
                        color: color,
                        background: active ? "#38bdf822" : "transparent",
                        fontSize: "0.85em",
                      }}
                    >
                      {done ? "✓" : active ? "▶" : "○"} {PHASE_LABEL[ph] || ph}
                    </div>
                    {i < PHASE_ORDER.length - 1 && <span style={{ color: "#64748b" }}>↓</span>}
                  </div>
                );
              })}
            </div>
            <p className="muted" style={{ fontSize: "0.85em", marginTop: 6 }}>
              Session {session.session_id} · 当前阶段：{PHASE_LABEL[session.phase] || session.phase}
            </p>
          </div>

          {/* ③ Plan：研究任务清单 */}
          {session.plan && (
            <>
              <h2>③ 研究计划（{session.plan.tasks.length} 项任务）</h2>
              <div className="semantic-card" style={{ marginBottom: 12 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85em" }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "#94a3b8" }}>
                      <th style={{ padding: "4px 8px" }}>任务</th>
                      <th style={{ padding: "4px 8px" }}>类别</th>
                      <th style={{ padding: "4px 8px" }}>指标</th>
                      <th style={{ padding: "4px 8px" }}>研究目标</th>
                    </tr>
                  </thead>
                  <tbody>
                    {session.plan.tasks.map((t, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                        <td style={{ padding: "4px 8px" }}>{TASK_LABEL[t.task_type] || t.task_type}</td>
                        <td style={{ padding: "4px 8px" }}>{t.category}</td>
                        <td style={{ padding: "4px 8px" }}>{t.metric}</td>
                        <td style={{ padding: "4px 8px" }} className="muted">{t.objective}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* ④ Tool Trace：工具调用链 */}
          {session.tool_calls.length > 0 && (
            <>
              <h2>④ Tool Trace（{session.tool_calls.length} 次调用）</h2>
              <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
                {session.tool_calls.slice(0, 12).map((tc, i) => (
                  <div key={i} style={{ marginBottom: 4, display: "flex", gap: 8 }}>
                    <span style={{ color: tc.success ? "#4ade80" : "#f87171", fontWeight: 600 }}>
                      [{tc.success ? "OK" : "FAIL"}] {tc.tool}
                    </span>
                    <span className="muted" style={{ flex: "1 1 auto" }}>{tc.output_summary}</span>
                    <span className="muted" style={{ flex: "0 0 60px", textAlign: "right" }}>证据 {tc.evidence_count ?? 0}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ⑤ Research Memo：7 段结构 */}
          {session.memo && (
            <>
              <h2>⑤ Research Memo（Evidence First）</h2>

              {/* ① Company Overview */}
              <div className="verdict-card" style={{ borderLeftColor: "#38bdf8", marginBottom: 10 }}>
                <h3 style={{ margin: "0 0 4px 0" }}>① Company Overview</h3>
                <p className="muted" style={{ fontSize: "0.85em" }}>{session.memo.company_overview}</p>
              </div>

              {/* ② Key Facts */}
              <MemoFactSection title="② Key Facts" findings={session.memo.key_facts} />

              {/* ③ Financial Facts */}
              <MemoFactSection title="③ Financial Facts" findings={session.memo.financial_facts} />

              {/* ④ Business Facts */}
              <MemoFactSection title="④ Business Facts" findings={session.memo.business_facts} />

              {/* ⑤ Risk Findings */}
              <div className="semantic-card" style={{ marginBottom: 10 }}>
                <h3 style={{ margin: "0 0 6px 0" }}>⑤ Risk Findings（{session.memo.risk_findings.length}）</h3>
                {session.memo.risk_findings.length === 0 ? (
                  <p className="muted" style={{ fontSize: "0.85em" }}>未发现风险。</p>
                ) : (
                  session.memo.risk_findings.map((r, i) => (
                    <div key={i} className="verdict-card" style={{ borderLeftColor: STATUS_COLOR[r.risk_level || "LOW"], marginBottom: 8, fontSize: "0.85em" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                        <strong>{r.risk_type} · {r.source_tool}</strong>
                        <span style={{ color: STATUS_COLOR[r.risk_level || "LOW"] }}>{r.risk_level} ({r.risk_score ?? 0})</span>
                      </div>
                      <p style={{ margin: "2px 0" }}>{r.content}</p>
                      {r.logical_gap && <p className="muted" style={{ margin: "2px 0" }}><strong>逻辑缺口：</strong>{r.logical_gap}</p>}
                    </div>
                  ))
                )}
              </div>

              {/* ⑥ Evidence Chain */}
              <div className="semantic-card" style={{ marginBottom: 10 }}>
                <h3 style={{ margin: "0 0 6px 0" }}>⑥ Evidence Chain（{session.memo.evidence_chain.length} 条）</h3>
                {session.memo.evidence_chain.length === 0 ? (
                  <p className="muted" style={{ fontSize: "0.85em" }}>无证据引用。</p>
                ) : (
                  <div style={{ fontSize: "0.85em" }}>
                    {session.memo.evidence_chain.slice(0, 8).map((e, i) => (
                      <div key={i} style={{ marginBottom: 4, padding: "4px 8px", background: "#1e293b22", borderRadius: 4 }}>
                        <strong>{e.document_id || "?"} p{e.page_number || "?"}</strong>
                        <span className="muted" style={{ marginLeft: 8 }}>{e.text?.slice(0, 80)}…</span>
                        {e.evidence_tier && <span style={{ color: "#94a3b8", marginLeft: 8 }}>{e.evidence_tier}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* ⑦ Open Questions */}
              <div className="semantic-card" style={{ marginBottom: 10, borderLeft: "3px solid #fbbf24" }}>
                <h3 style={{ margin: "0 0 6px 0" }}>⑦ Open Questions（{session.memo.open_questions.length}）</h3>
                {session.memo.open_questions.length === 0 ? (
                  <p className="muted" style={{ fontSize: "0.85em" }}>无待验证事项。</p>
                ) : (
                  <ul style={{ margin: "2px 0", paddingLeft: 18, fontSize: "0.85em" }}>
                    {session.memo.open_questions.map((q, i) => <li key={i} className="muted">{q}</li>)}
                  </ul>
                )}
              </div>

              {/* 评测指标 */}
              <div className="semantic-card" style={{ fontSize: "0.85em" }}>
                <h3 style={{ margin: "0 0 6px 0" }}>评测指标</h3>
                <p>Evidence Coverage: <strong>{session.memo.evidence_coverage}</strong></p>
                <p>Unsupported Claim Rate: <strong>{session.memo.unsupported_claim_rate}</strong></p>
                <p>Task Completion Rate: <strong>{session.memo.task_completion_rate}</strong></p>
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}

// 子组件：事实段渲染（含证据绑定标记）
function MemoFactSection({ title, findings }: { title: string; findings: Finding[] }) {
  return (
    <div className="semantic-card" style={{ marginBottom: 10 }}>
      <h3 style={{ margin: "0 0 6px 0" }}>{title}（{findings.length}）</h3>
      {findings.length === 0 ? (
        <p className="muted" style={{ fontSize: "0.85em" }}>无事实。</p>
      ) : (
        findings.map((f, i) => (
          <div
            key={i}
            className="verdict-card"
            style={{
              borderLeftColor: f.supported ? "#4ade80" : "#fbbf24",
              marginBottom: 6,
              fontSize: "0.85em",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <strong>{TASK_LABEL[f.task_type] || f.task_type} · {f.metric}</strong>
              <span style={{ color: f.supported ? "#4ade80" : "#fbbf24", fontSize: "0.8em" }}>
                {f.supported ? `✓ 证据 ${f.evidence.length}` : "○ 无证据（Open Question）"}
              </span>
            </div>
            <p style={{ margin: "2px 0" }}>{f.content}</p>
            {f.evidence.length > 0 && (
              <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>
                证据：{f.evidence.map((e) => `${e.document_id || "?"} p${e.page_number || "?"}`).join("，")}
              </p>
            )}
            {f.notes && <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>{f.notes}</p>}
          </div>
        ))
      )}
    </div>
  );
}
