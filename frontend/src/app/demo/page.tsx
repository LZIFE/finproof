"use client";

import { useEffect, useState } from "react";

type DemoStep = {
  step_number: number;
  name: string;
  frontend_label: string;
  status: string; // PENDING / RUNNING / OK / SKIPPED / ERROR
  duration: number;
  input_reference?: string;
  output_reference?: string;
  source?: string;
  evidence?: string;
  result?: string;
  error?: string;
};

type RiskFinding = {
  risk_id: string;
  risk_type: string;
  level: string; // HIGH / MEDIUM / LOW
  score: number;
  reason: string;
  status?: string;
};

type ReplayEvent = {
  id?: number;
  audit_id: string;
  event_type: string;
  timestamp?: string;
  actor: string;
  content: string;
  evidence_reference?: string;
  source?: string;
  evidence_summary?: string;
  result_summary?: string;
};

type ReplayTimeline = {
  audit_id: string;
  total_events: number;
  steps: Record<string, ReplayEvent[]>;
  step_order: string[];
  step_labels: Record<string, string>;
  step_icons: Record<string, string>;
};

type DemoRun = {
  demo_id: string;
  company: string;
  report_id?: string;
  status: string;
  current_step: string;
  steps: DemoStep[];
  reliability_score: number;
  risk_findings: RiskFinding[];
  audit_replay_id: string;
  audit_replay: ReplayTimeline | Record<string, never>;
  arena_run_id?: string;
  dashboard_id?: string;
  created_at?: string;
  finished_at?: string;
  frontend_steps: string[];
  frontend_labels: Record<string, string>;
};

const RISK_COLOR: Record<string, string> = {
  HIGH: "#f87171",
  MEDIUM: "#fbbf24",
  LOW: "#4ade80",
};

const STATUS_ICON: Record<string, string> = {
  OK: "✓",
  SKIPPED: "○",
  ERROR: "✗",
  RUNNING: "⟳",
  PENDING: "·",
};

// 前端 6 步动画顺序
const FRONTEND_STEP_ORDER = [
  "Understanding AI Report",
  "Finding Evidence",
  "Checking Facts",
  "Detecting Risks",
  "Agent Debate",
  "Generating Governance Report",
];

async function fetchLatestCompletedDemo(completedAfter?: number): Promise<DemoRun | null> {
  const listResponse = await fetch("/api/v1/demo?limit=1");
  if (!listResponse.ok) return null;
  const list = await listResponse.json();
  const latest = list?.demos?.[0];
  if (!latest?.demo_id || latest.status !== "DONE") return null;
  const completedAt = Date.parse(latest.created_at ?? "");
  if (completedAfter && (!Number.isFinite(completedAt) || completedAt < completedAfter)) {
    return null;
  }

  const detailResponse = await fetch(`/api/v1/demo/${latest.demo_id}`);
  if (!detailResponse.ok) return null;
  return detailResponse.json();
}

export default function DemoPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<DemoRun | null>(null);
  const [activeStep, setActiveStep] = useState(0); // 动画当前步

  useEffect(() => {
    let cancelled = false;
    fetchLatestCompletedDemo()
      .then((latest) => {
        if (!cancelled && latest) {
          setRun(latest);
          setActiveStep(latest.frontend_steps?.length || FRONTEND_STEP_ORDER.length);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const startDemo = async () => {
    const startedAt = Date.now();
    setLoading(true);
    setError(null);
    setRun(null);
    setActiveStep(0);
    try {
      const resp = await fetch("/api/v1/demo/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company: "美的集团" }),
      });
      const responseText = await resp.text();
      let body: DemoRun;
      try {
        body = JSON.parse(responseText) as DemoRun;
      } catch {
        throw new Error(responseText || `HTTP ${resp.status}`);
      }
      if (!resp.ok) throw new Error(JSON.stringify(body));
      // 模拟 6 步动画推进（基于 frontend_steps）
      const steps = body.frontend_steps || FRONTEND_STEP_ORDER;
      for (let i = 0; i < steps.length; i++) {
        setActiveStep(i + 1);
        await new Promise((r) => setTimeout(r, 400));
      }
      setRun(body);
    } catch (e) {
      const latest = await fetchLatestCompletedDemo(startedAt).catch(() => null);
      if (latest) {
        setRun(latest);
        setActiveStep(latest.frontend_steps?.length || FRONTEND_STEP_ORDER.length);
      } else {
        setError(`演示启动失败：${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setLoading(false);
    }
  };

  // 前端动画步标签
  const frontendSteps = run?.frontend_steps || FRONTEND_STEP_ORDER;
  const frontendLabels = run?.frontend_labels || {};

  // 后端步按 frontend_label 分桶（供每步展示 来源/证据/结果）
  const stepsByFrontend: Record<string, DemoStep[]> = {};
  if (run) {
    for (const s of run.steps) {
      const key = s.frontend_label || s.name;
      if (!stepsByFrontend[key]) stepsByFrontend[key] = [];
      stepsByFrontend[key].push(s);
    }
  }

  const replay = run?.audit_replay as ReplayTimeline | undefined;

  return (
    <main className="page">
      <h1>FinProof AI Reliability Audit（Phase 22 Demo）</h1>
      <p className="muted">
        比赛演示模式：一次点击看到完整 AI 审计闭环 — AI Report → Evidence → Facts → Risks → Agent Debate → Governance Report。
        <strong> 不新增分析能力</strong>，仅编排既有模块。保持 Evidence First；不输出投资建议、股票推荐或交易。
      </p>

      {/* 第一屏：Start Demo */}
      <h2>① FinProof AI Reliability Audit</h2>
      <div className="card" style={{ textAlign: "center", padding: 24 }}>
        <p style={{ fontSize: "1.1em", marginBottom: 16 }}>
          固定 Demo Case：<strong>美的集团 AI 研究报告</strong>
          <span className="muted" style={{ fontSize: "0.85em" }}>（错误财务增长率 · 战略夸大 · 证据不足）</span>
        </p>
        <button
          onClick={startDemo}
          disabled={loading}
          style={{ fontSize: "1.1em", padding: "12px 32px" }}
        >
          {loading ? "审计中…" : "▶ Start Demo"}
        </button>
        {error && <p className="bad" style={{ marginTop: 12 }}>{error}</p>}
      </div>

      {/* 执行动画：6 步 */}
      {(loading || run) && (
        <>
          <h2>② 执行动画</h2>
          <div className="semantic-card" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {frontendSteps.map((fs, i) => {
                const isActive = activeStep === i + 1 && loading;
                const isDone = activeStep > i + 1 || run;
                const stepsHere = stepsByFrontend[fs] || [];
                const allOk = stepsHere.length > 0 && stepsHere.every((s) => s.status === "OK");
                const hasErr = stepsHere.some((s) => s.status === "ERROR");
                const hasSkip = stepsHere.some((s) => s.status === "SKIPPED");
                const icon = isDone ? (hasErr ? "✗" : allOk ? "✓" : hasSkip ? "○" : "·") : isActive ? "⟳" : "·";
                const color = hasErr ? "#f87171" : allOk ? "#4ade80" : isActive ? "#38bdf8" : "#64748b";
                return (
                  <div
                    key={fs}
                    className="verdict-card"
                    style={{ borderLeftColor: color, marginBottom: 0, opacity: isDone || isActive ? 1 : 0.5 }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <strong style={{ color }}>
                        Step {i + 1}: {fs} <span className="muted" style={{ fontSize: "0.85em" }}>({frontendLabels[fs] || fs})</span>
                      </strong>
                      <span style={{ color, fontSize: "1.2em" }}>{icon}</span>
                    </div>
                    {/* 每一步展示：来源 / Evidence / Result */}
                    {stepsHere.length > 0 && (
                      <div style={{ fontSize: "0.85em", marginTop: 4 }}>
                        {stepsHere.map((s, j) => (
                          <div key={j} style={{ border: "1px solid #1e293b", borderRadius: 6, padding: 6, marginBottom: 4 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                              <strong className="muted">来源：{s.source || s.name}</strong>
                              <span className="muted" style={{ fontSize: "0.85em" }}>{s.status} · {s.duration}ms</span>
                            </div>
                            <p style={{ margin: "2px 0" }}>{s.result || s.error || "-"}</p>
                            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: "0.85em" }}>
                              <span className="muted">Evidence: {s.evidence || "-"}</span>
                              <span className="muted">Result: {s.output_reference || "-"}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {/* 最后：最终输出 */}
      {run && (
        <>
          <h2>③ 最终输出</h2>

          {/* Reliability Score */}
          <div className="verdict-card" style={{ borderLeftColor: "#38bdf8", marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <h3 style={{ margin: 0 }}>AI 可靠性评分（Reliability Score）</h3>
              <span style={{ fontSize: "1.8em", fontWeight: 700, color: "#38bdf8" }}>
                {run.reliability_score.toFixed(1)}<span style={{ fontSize: "0.55em", color: "#94a3b8" }}>/100</span>
              </span>
            </div>
            <div style={{ height: 10, background: "#1e293b", borderRadius: 6, overflow: "hidden" }}>
              <div
                style={{
                  width: `${Math.max(0, Math.min(100, run.reliability_score))}%`,
                  height: "100%",
                  background: "#38bdf8",
                  transition: "width 0.5s",
                }}
              />
            </div>
            <p className="muted" style={{ fontSize: "0.85em", marginTop: 4 }}>
              = Arena Score × 0.6 + Dashboard reliability × 0.4 · 仅反映 AI 生成内容的事实验证与风险检出能力，不构成投资建议
            </p>
          </div>

          {/* Risk Findings */}
          <h3>风险列表（Risk Findings）</h3>
          <div className="semantic-card" style={{ marginBottom: 12, fontSize: "0.85em" }}>
            {run.risk_findings.length === 0 ? (
              <p className="muted">暂无风险条目。</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {run.risk_findings.map((r) => (
                  <div
                    key={r.risk_id}
                    className="verdict-card"
                    style={{ borderLeftColor: RISK_COLOR[r.level] || "#64748b", marginBottom: 0 }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
                      <strong>{r.risk_id} · {r.risk_type}</strong>
                      <span style={{ color: RISK_COLOR[r.level] || "#64748b", fontSize: "0.85em" }}>
                        {r.level} · score {r.score} · {r.status || "-"}
                      </span>
                    </div>
                    <p style={{ margin: "2px 0" }}>{r.reason}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Audit Replay */}
          <h3>完整审计链（Audit Replay）</h3>
          <div className="semantic-card" style={{ fontSize: "0.85em" }}>
            {!replay || replay.total_events === 0 ? (
              <p className="muted">暂无审计回放事件。</p>
            ) : (
              <>
                <p className="muted" style={{ marginBottom: 8 }}>
                  audit_id <strong>{replay.audit_id}</strong> · 共 {replay.total_events} 事件 · 6 步时间线
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {(replay.step_order || []).map((et) => {
                    const evs = replay.steps?.[et] || [];
                    const label = replay.step_labels?.[et] || et;
                    const icon = replay.step_icons?.[et] || "•";
                    return (
                      <div key={et} style={{ borderLeft: "3px solid #4ade80", paddingLeft: 8 }}>
                        <strong>{icon} {label}</strong>
                        <span className="muted" style={{ fontSize: "0.85em", marginLeft: 8 }}>（{evs.length} 事件）</span>
                        {evs.length === 0 ? (
                          <p className="muted" style={{ fontSize: "0.85em", margin: "2px 0" }}>— 无 —</p>
                        ) : (
                          <div style={{ marginTop: 4 }}>
                            {evs.slice(0, 3).map((e, i) => (
                              <div key={i} style={{ fontSize: "0.85em", marginBottom: 2 }}>
                                <strong className="muted">来源：{e.actor}</strong>
                                <span style={{ marginLeft: 8 }}>{e.content.length > 70 ? e.content.slice(0, 70) + "…" : e.content}</span>
                              </div>
                            ))}
                            {evs.length > 3 && <p className="muted" style={{ fontSize: "0.8em" }}>… 其余 {evs.length - 3} 条</p>}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          {/* 元信息 */}
          <p className="muted" style={{ fontSize: "0.8em", marginTop: 16 }}>
            demo_id {run.demo_id} · arena {run.arena_run_id || "-"} · dashboard {run.dashboard_id || "-"} · 创建 {run.created_at} · 完成 {run.finished_at}
          </p>
        </>
      )}
    </main>
  );
}
