"use client";

import { useState } from "react";

type ScenarioType = {
  type: string;
  label: string;
};

type ExpectedFinding = {
  finding_id: string;
  category: string;
  text: string;
  must_find: boolean;
  finding_type: string;
};

type Scenario = {
  scenario_id: string;
  scenario_type: string;
  company: string;
  industry: string;
  objective: string;
  available_documents: { document_id?: string; period?: string }[];
  hidden_risks: string[];
  expected_findings: ExpectedFinding[];
  difficulty: string;
  task_query: string;
};

type Step = {
  step_id: string;
  phase: string;
  tool: string;
  input_summary: string;
  output_summary: string;
  evidence_count: number;
  findings_count: number;
  success: boolean;
};

type ScoreBreakdown = {
  score: number;
  expected_count: number;
  detected_count: number;
  missed: string[];
  false_positives: string[];
  notes: string;
};

type SimulationScore = {
  evidence_score: ScoreBreakdown;
  reasoning_score: ScoreBreakdown;
  risk_detection_score: ScoreBreakdown;
  efficiency_score: ScoreBreakdown;
  hallucination_score: ScoreBreakdown;
  fin_agent_score: number;
  difficulty_weight: number;
  final_score: number;
};

type Result = {
  result_id: string;
  agent_run: {
    session_id?: string;
    tool_calls: { tool?: string; success?: boolean; evidence_count?: number; output_summary?: string }[];
    findings: { content?: string; supported?: boolean; evidence?: { document_id?: string; page_number?: string }[]; notes?: string }[];
    risk_findings: { content?: string; risk_level?: string; logical_gap?: string }[];
    evidence: { document_id?: string; page_number?: string; text?: string; evidence_tier?: string }[];
    memo: { company_overview?: string; evidence_coverage?: number; unsupported_claim_rate?: number; task_completion_rate?: number };
    duration_sec?: number;
  };
  detected_findings: string[];
  missed_findings: string[];
  hallucination_findings: string[];
  score: SimulationScore;
  success: boolean;
};

type SimulationRun = {
  run_id: string;
  scenario_id: string;
  scenario: Scenario | null;
  agent_name: string;
  phase: string;
  steps: Step[];
  result: Result | null;
  created_at?: string;
  finished_at?: string;
};

const PHASE_ORDER = ["Scenario", "Agent Investigates", "Collect Evidence", "Generate Memo", "Compare and Score"];

const PHASE_LABEL: Record<string, string> = {
  Scenario: "场景",
  "Agent Investigates": "Agent 调查",
  "Collect Evidence": "收集证据",
  "Generate Memo": "生成 Memo",
  "Compare and Score": "比对评分",
};

const STATUS_COLOR: Record<string, string> = {
  Easy: "#4ade80",
  Medium: "#fbbf24",
  Hard: "#f87171",
};

const CATEGORY_COLOR: Record<string, string> = {
  fact: "#38bdf8",
  risk: "#f87171",
  logic: "#fbbf24",
  contradiction: "#a78bfa",
};

export default function SimulationPage() {
  const [scenarioTypes, setScenarioTypes] = useState<ScenarioType[]>([]);
  const [scenarioType, setScenarioType] = useState("Financial Misstatement");
  const [company, setCompany] = useState("美的集团");
  const [industry, setIndustry] = useState("家电");
  const [difficulty, setDifficulty] = useState("Hard");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<SimulationRun | null>(null);

  const loadScenarios = async () => {
    try {
      const r = await fetch("/api/v1/simulation/scenarios");
      const body = await r.json();
      setScenarioTypes(body.scenario_types || []);
    } catch {
      /* 静默 */
    }
  };

  useState(() => {
    loadScenarios();
    return;
  });

  const runSimulation = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/simulation/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_type: scenarioType, company, industry, difficulty }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setRun(body);
    } catch (e) {
      setError(`模拟失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const currentPhaseIndex = run ? PHASE_ORDER.indexOf(run.phase) : -1;

  return (
    <main className="page">
      <h1>FinSim · Financial Agent Simulation Environment（Phase 18）</h1>
      <p className="muted">
        金融 AI Agent 竞技场：测试完整 Agent workflow（非单个答案）。保持 Evidence First；不输出投资建议。
      </p>

      {/* ① 启动模拟 */}
      <h2>① 启动模拟</h2>
      <div className="card">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ flex: "2 1 220px" }}>
            场景类型
            <select value={scenarioType} onChange={(e) => setScenarioType(e.target.value)} style={{ display: "block", width: "100%" }}>
              {scenarioTypes.length === 0 ? (
                <option value={scenarioType}>{scenarioType}</option>
              ) : (
                scenarioTypes.map((s) => <option key={s.type} value={s.type}>{s.label}</option>)
              )}
            </select>
          </label>
          <label style={{ flex: "2 1 160px" }}>
            公司
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            行业
            <input value={industry} onChange={(e) => setIndustry(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            难度
            <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} style={{ display: "block", width: "100%" }}>
              <option value="Easy">Easy</option>
              <option value="Medium">Medium</option>
              <option value="Hard">Hard</option>
            </select>
          </label>
          <button onClick={runSimulation} disabled={loading}>
            {loading ? "模拟中…" : "启动模拟"}
          </button>
        </div>
        {error && <p className="bad">{error}</p>}
      </div>

      {run && (
        <>
          {/* ② Scenario → Actions → Evidence → Findings → Score 流程 */}
          <h2>② Simulation Flow</h2>
          <div className="semantic-card" style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {PHASE_ORDER.map((ph, i) => {
                const done = i < currentPhaseIndex || run.phase === "Compare and Score";
                const active = i === currentPhaseIndex && run.phase !== "Compare and Score";
                const color = done ? "#4ade80" : active ? "#38bdf8" : "#94a3b8";
                return (
                  <div key={ph} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div
                      style={{
                        padding: "4px 10px",
                        borderRadius: 6,
                        border: `1px solid ${color}`,
                        color,
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
              Run {run.run_id} · Agent: {run.agent_name} · 当前阶段：{PHASE_LABEL[run.phase] || run.phase}
            </p>
          </div>

          {/* ③ Scenario 详情 + 埋点 */}
          {run.scenario && (
            <>
              <h2>③ Scenario</h2>
              <div className="semantic-card" style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <strong>{run.scenario.company} · {run.scenario.industry}</strong>
                  <span style={{ color: STATUS_COLOR[run.scenario.difficulty] || "#94a3b8", fontWeight: 600 }}>
                    {run.scenario.difficulty}
                  </span>
                </div>
                <p style={{ margin: "2px 0" }}><strong>任务目标：</strong>{run.scenario.objective}</p>
                {run.scenario.hidden_risks.length > 0 && (
                  <p className="muted" style={{ fontSize: "0.85em" }}>
                    <strong>隐藏风险（Hard 埋点）：</strong>{run.scenario.hidden_risks.join("；")}
                  </p>
                )}
                <h4 style={{ margin: "8px 0 4px 0" }}>埋点（Expected Findings）</h4>
                <div style={{ fontSize: "0.85em" }}>
                  {run.scenario.expected_findings.map((ef) => {
                    const detected = run.result?.detected_findings.includes(ef.finding_id);
                    const missed = run.result?.missed_findings.includes(ef.finding_id);
                    const color = detected ? "#4ade80" : missed ? "#f87171" : "#94a3b8";
                    return (
                      <div key={ef.finding_id} style={{ marginBottom: 4, padding: "4px 8px", background: "#1e293b22", borderRadius: 4, borderLeft: `3px solid ${CATEGORY_COLOR[ef.category] || "#64748b"}` }}>
                        <span style={{ color, fontWeight: 600 }}>
                          {detected ? "✓ 检出" : missed ? "✗ 未检出" : "○ 可选"} {ef.finding_id}
                        </span>
                        <span className="muted" style={{ marginLeft: 8 }}>[{ef.category}] {ef.text}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {/* ④ Agent Actions（steps） */}
          <h2>④ Agent Actions（{run.steps.length} 步）</h2>
          <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
            {run.steps.map((st, i) => (
              <div key={i} style={{ marginBottom: 6, display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ color: "#94a3b8", fontFamily: "monospace" }}>{st.step_id}</span>
                <span style={{ color: "#38bdf8", fontWeight: 600 }}>{st.tool}</span>
                <span className="muted" style={{ flex: "1 1 auto" }}>{st.output_summary}</span>
                <span style={{ color: st.success ? "#4ade80" : "#f87171" }}>[{st.success ? "OK" : "FAIL"}]</span>
                <span className="muted" style={{ flex: "0 0 80px", textAlign: "right" }}>证据 {st.evidence_count}</span>
              </div>
            ))}
          </div>

          {/* ⑤ Evidence */}
          {run.result && run.result.agent_run.evidence.length > 0 && (
            <>
              <h2>⑤ Evidence（{run.result.agent_run.evidence.length} 条）</h2>
              <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
                {run.result.agent_run.evidence.slice(0, 10).map((e, i) => (
                  <div key={i} style={{ marginBottom: 4, padding: "4px 8px", background: "#1e293b22", borderRadius: 4 }}>
                    <strong>{e.document_id || "?"} p{e.page_number || "?"}</strong>
                    <span className="muted" style={{ marginLeft: 8 }}>{(e.text || "").slice(0, 80)}…</span>
                    {e.evidence_tier && <span style={{ color: "#94a3b8", marginLeft: 8 }}>{e.evidence_tier}</span>}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ⑥ Findings */}
          {run.result && (
            <>
              <h2>⑥ Findings</h2>
              <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
                <h4 style={{ margin: "0 0 4px 0" }}>事实（{run.result.agent_run.findings.length}）</h4>
                {run.result.agent_run.findings.map((f, i) => (
                  <div key={i} className="verdict-card" style={{ borderLeftColor: f.supported ? "#4ade80" : "#fbbf24", marginBottom: 6 }}>
                    <span style={{ color: f.supported ? "#4ade80" : "#fbbf24", fontWeight: 600 }}>
                      {f.supported && f.evidence?.length ? `✓ 证据 ${f.evidence.length}` : "○ 无证据"}
                    </span>
                    <p style={{ margin: "2px 0" }}>{f.content}</p>
                    {f.notes && <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>{f.notes}</p>}
                  </div>
                ))}
                {run.result.agent_run.risk_findings.length > 0 && (
                  <>
                    <h4 style={{ margin: "8px 0 4px 0" }}>风险发现（{run.result.agent_run.risk_findings.length}）</h4>
                    {run.result.agent_run.risk_findings.map((r, i) => (
                      <div key={i} className="verdict-card" style={{ borderLeftColor: "#f87171", marginBottom: 6 }}>
                        <strong>{r.risk_level || "LOW"}</strong>
                        <p style={{ margin: "2px 0" }}>{r.content}</p>
                        {r.logical_gap && <p className="muted" style={{ margin: "2px 0", fontSize: "0.8em" }}>逻辑缺口：{r.logical_gap}</p>}
                      </div>
                    ))}
                  </>
                )}
                {run.result.hallucination_findings.length > 0 && (
                  <p className="bad" style={{ fontSize: "0.85em" }}>
                    无依据输出 {run.result.hallucination_findings.length} 条（Hallucination）
                  </p>
                )}
              </div>
            </>
          )}

          {/* ⑦ Score */}
          {run.result && (
            <>
              <h2>⑦ Score</h2>
              <div className="verdict-card" style={{ borderLeftColor: run.result.success ? "#4ade80" : "#fbbf24", marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <h3 style={{ margin: 0 }}>FinAgent Score</h3>
                  <span style={{ fontSize: "1.4em", fontWeight: 700, color: "#38bdf8" }}>
                    {run.result.score.final_score.toFixed(1)}
                  </span>
                </div>
                <p className="muted" style={{ fontSize: "0.85em" }}>
                  FinAgent Score（原始）：{run.result.score.fin_agent_score.toFixed(1)} · 难度权重：{run.result.score.difficulty_weight} ·
                  结果：<strong style={{ color: run.result.success ? "#4ade80" : "#fbbf24" }}>{run.result.success ? "✓ Success" : "○ Partial"}</strong>
                </p>
              </div>

              <div className="semantic-card" style={{ fontSize: "0.85em" }}>
                <ScoreRow label="Evidence Score（证据覆盖率）" bd={run.result.score.evidence_score} />
                <ScoreRow label="Reasoning Score（逻辑漏洞发现率）" bd={run.result.score.reasoning_score} />
                <ScoreRow label="Risk Detection Score（风险识别率）" bd={run.result.score.risk_detection_score} />
                <ScoreRow label="Efficiency Score（工具调用效率）" bd={run.result.score.efficiency_score} />
                <ScoreRow label="Hallucination Score（无依据输出比例，越高越好）" bd={run.result.score.hallucination_score} />
              </div>
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
      <p className="muted" style={{ fontSize: "0.8em", margin: "2px 0" }}>
        检出 {bd.detected_count}/{bd.expected_count} · {bd.notes}
        {bd.missed.length > 0 && ` · 未检出：${bd.missed.join(", ")}`}
        {bd.false_positives.length > 0 && ` · 禁止词命中：${bd.false_positives.length}`}
      </p>
    </div>
  );
}
