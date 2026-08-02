"use client";

import { useState } from "react";

type ClaimContext = {
  claim_text: string;
  claim_type: string;
  risk_type: string;
  company: string;
  stock_code: string;
};

type Step = {
  step: number;
  tool: string;
  purpose: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  reasoning: string;
  status: string;
  evidence_source: { block_id?: number; page_number?: number; text?: string; score?: number }[];
  timestamp: string;
};

type Conclusion = {
  verification_status: string;
  risk_score: number;
  risk_level: string;
  risk_type: string;
  evidence_count: number;
  summary: string;
};

type Investigation = {
  trace_id: string;
  run_id: string;
  claim_context: ClaimContext;
  plan: { objective: string; claim_type: string; risk_type: string; steps: Step[] };
  steps: Step[];
  evidence: { block_id?: number; page_number?: number; text?: string; score?: number; evidence_type?: string }[];
  conclusion: Conclusion;
  memory_used: boolean;
  created_at: string;
};

const LEVEL_COLOR: Record<string, string> = {
  HIGH: "#f87171",
  MEDIUM: "#fbbf24",
  LOW: "#4ade80",
};

const STATUS_COLOR: Record<string, string> = {
  DONE: "#4ade80",
  RUNNING: "#fbbf24",
  FAILED: "#f87171",
  PENDING: "#94a3b8",
};

const TOOL_LABEL: Record<string, string> = {
  retrieve_evidence: "检索证据",
  verify_claim: "核验主张",
  get_company_profile: "获取公司画像",
  get_business_map: "获取业务图谱",
  detect_conflicts: "检测冲突",
  assess_risk: "评估风险",
};

export default function InvestigationPage() {
  const [claimText, setClaimText] = useState("海外业务成为利润增长核心");
  const [claimType, setClaimType] = useState("STRATEGIC");
  const [company, setCompany] = useState("美的集团");
  const [stockCode, setStockCode] = useState("000333");
  const [useMemory, setUseMemory] = useState(true);

  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch("/api/v1/investigations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_text: claimText,
          claim_type: claimType,
          risk_type: "",
          company,
          stock_code: stockCode,
          claim: { claim_id: "C-FE", original_text: claimText },
          use_memory: useMemory,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setInvestigation(body);
    } catch (e) {
      setError(`调查失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>自主调查 Agent（Phase 13 · Autonomous Investigation Agent）</h1>
      <p className="muted">
        Supervisor 升级：根据风险类型自主规划调查路径。Plan → Tool Calls → Evidence → Verification → Risk。
      </p>

      {/* 启动调查表单 */}
      <h2>① 启动自主调查</h2>
      <div className="card">
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ flex: "2 1 240px" }}>
            主张文本
            <input value={claimText} onChange={(e) => setClaimText(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 120px" }}>
            主张类型
            <select value={claimType} onChange={(e) => setClaimType(e.target.value)}>
              <option value="STRATEGIC">STRATEGIC 战略</option>
              <option value="FINANCIAL">FINANCIAL 财务</option>
              <option value="BUSINESS">BUSINESS 业务</option>
              <option value="COMPETITIVE">COMPETITIVE 竞争</option>
              <option value="GROWTH">GROWTH 增长</option>
              <option value="FORECAST">FORECAST 预测</option>
            </select>
          </label>
        </div>
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          <label style={{ flex: "1 1 120px" }}>
            公司
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px" }}>
            股票代码
            <input value={stockCode} onChange={(e) => setStockCode(e.target.value)} />
          </label>
          <label style={{ flex: "1 1 100px", display: "flex", alignItems: "center", gap: 6, paddingTop: 18 }}>
            <input type="checkbox" checked={useMemory} onChange={(e) => setUseMemory(e.target.checked)} />
            使用 Memory
          </label>
        </div>
        <button onClick={run} disabled={loading} style={{ marginTop: 12 }}>
          {loading ? "调查中…" : "启动自主调查"}
        </button>
      </div>

      {error && <p className="bad">{error}</p>}

      {/* ② Agent Reasoning Trace（Action Trace / Tool Results / Evidence） */}
      {investigation && (
        <>
          <h2>② Agent Reasoning Trace — 调查轨迹</h2>
          <div className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR[investigation.conclusion.risk_level] || "#64748b" }}>
            <h3>
              Trace {investigation.trace_id} · {investigation.run_id}
            </h3>
            <p className="muted">
              {investigation.plan.objective}
            </p>
            <p className="muted">
              Memory used: <strong>{investigation.memory_used ? "是" : "否"}</strong> · 创建于 {investigation.created_at}
            </p>
          </div>

          {/* 步骤执行链：Action Trace → Tool Results */}
          <h3>Action Trace（调查步骤）</h3>
          {investigation.steps.length === 0 ? (
            <p className="muted">无执行步骤。</p>
          ) : (
            <div>
              {investigation.steps.map((s) => {
                const out = s.output || {};
                const evCount =
                  (out.evidence_count as number) ||
                  (Array.isArray(out.evidence) ? (out.evidence as unknown[]).length : 0);
                return (
                  <div key={s.step} className="semantic-card" style={{ marginBottom: 10 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                      <strong>
                        Step {s.step} · {TOOL_LABEL[s.tool] || s.tool}
                      </strong>
                      <span style={{ color: STATUS_COLOR[s.status] || "#94a3b8", fontSize: "0.85em" }}>{s.status}</span>
                    </div>
                    <p className="muted" style={{ margin: "2px 0" }}>目的：{s.purpose}</p>
                    <p className="muted" style={{ margin: "2px 0" }}>
                      Tool Result：证据 {evCount} 条 ·{" "}
                      {(out.conflicts_found !== undefined || out.conflicts_found === 0)
                        ? `冲突 ${out.conflicts_found} `
                        : ""}
                      {(out.risk_assessment as Record<string, unknown> | undefined)?.risk_score !== undefined
                        ? `风险分 ${(out.risk_assessment as Record<string, unknown>).risk_score} `
                        : ""}
                    </p>
                    {s.evidence_source && s.evidence_source.length > 0 && (
                      <details style={{ marginTop: 4 }}>
                        <summary className="muted">证据来源 ({s.evidence_source.length})</summary>
                        <ul className="muted" style={{ margin: "4px 0", paddingLeft: 18 }}>
                          {s.evidence_source.slice(0, 3).map((e, i) => (
                            <li key={i}>
                              block {e.block_id ?? "?"} · p{e.page_number ?? "?"} · score {e.score ?? 0}
                              {e.text ? `：${e.text.slice(0, 60)}…` : ""}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* ③ Evidence 汇总 */}
          <h2>③ Evidence（汇总证据）</h2>
          {investigation.evidence.length === 0 ? (
            <p className="muted">无证据。</p>
          ) : (
            <div>
              {investigation.evidence.map((e, i) => (
                <div key={i} className="source-quote" style={{ fontSize: "0.85rem" }}>
                  <strong>block {e.block_id ?? "?"}</strong> · p{e.page_number ?? "?"} · 类型 {e.evidence_type || "UNKNOWN"} · score {e.score ?? 0}
                  <div className="muted" style={{ marginTop: 4 }}>{e.text?.slice(0, 200) ?? ""}</div>
                </div>
              ))}
            </div>
          )}

          {/* ④ Conclusion */}
          <h2>④ Conclusion（调查结论）</h2>
          <div className="verdict-card" style={{ borderLeftColor: LEVEL_COLOR[investigation.conclusion.risk_level] || "#64748b" }}>
            <h3>
              核验结论 <strong>{investigation.conclusion.verification_status}</strong>
            </h3>
            <p>
              风险分 <strong style={{ color: LEVEL_COLOR[investigation.conclusion.risk_level] || "#94a3b8" }}>
                {investigation.conclusion.risk_score}
              </strong>{" "}
              · {investigation.conclusion.risk_level} · 类型 {investigation.conclusion.risk_type || "-"}
            </p>
            <p className="muted">证据数：{investigation.conclusion.evidence_count}</p>
            <p>{investigation.conclusion.summary}</p>
          </div>
        </>
      )}
    </main>
  );
}
