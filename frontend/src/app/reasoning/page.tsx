"use client";

import { useState } from "react";

type ReasoningResult = {
  result_id: string;
  reasoning_type: string;
  status: string;
  premises: string[];
  supporting_evidence: { evidence_id?: string | number; source?: string; page?: string | number; text?: string; stance?: string }[];
  counter_evidence: { evidence_id?: string | number; source?: string; page?: string | number; text?: string; stance?: string }[];
  assumptions: string[];
  logical_gap: string;
  confidence: number;
  explanation: string;
  suggested_safe_wording: string;
  triggered_rules: string[];
  evidence_ids: string[];
  rule_version: string;
};

type ReasoningRun = {
  run_id: string;
  claim_text: string;
  input_ref: Record<string, unknown>;
  results: ReasoningResult[];
  rule_version: string;
  created_at: string;
};

const STATUS_COLOR: Record<string, string> = {
  OK: "#4ade80",
  ASSUMPTION_UNVERIFIED: "#fbbf24",
  MIXED_EVIDENCE: "#fbbf24",
  LOGICAL_GAP: "#f87171",
  INSUFFICIENT_DATA: "#94a3b8",
  UNSUPPORTED: "#f87171",
};

const TYPE_LABEL: Record<string, string> = {
  METRIC_SUBSTITUTION: "指标偷换",
  PERIOD_SUBSTITUTION: "期间口径偷换",
  CORRELATION_AS_CAUSATION: "相关性写成因果",
  REVENUE_PROFIT_CONFUSION: "收入贡献写成利润贡献",
  GROWTH_QUALITY_RISK: "增长质量风险",
  BASE_EFFECT_RISK: "低基数高增长",
  SELECTIVE_EVIDENCE: "选择性引用证据",
  HIDDEN_ASSUMPTION: "隐含未披露假设",
  CONCLUSION_OVERREACH: "结论过度跳跃",
  CONTRADICTION: "冲突检测",
};

const DEMO_CLAIMS = [
  "海外收入增长，因此海外业务是利润增长核心",
  "营收增长说明经营质量改善",
  "公司市场份额领先，因此具有长期竞争优势",
];

export default function ReasoningPage() {
  const [claimText, setClaimText] = useState("海外收入增长，因此海外业务是利润增长核心");
  const [company, setCompany] = useState("美的集团");
  const [evidenceJson, setEvidenceJson] = useState('[\n  {"block_id": 1, "text": "海外收入同比增长10%"},\n  {"block_id": 2, "text": "海外利润同比下滑5%"}\n]');
  const [run, setRun] = useState<ReasoningRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runReasoning = async () => {
    setLoading(true);
    setError(null);
    let evidence: unknown[] = [];
    try {
      evidence = JSON.parse(evidenceJson);
    } catch {
      setError("证据 JSON 解析失败，请检查格式");
      setLoading(false);
      return;
    }
    try {
      const resp = await fetch("/api/v1/reasoning/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_text: claimText,
          evidence_candidates: evidence,
          company,
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setRun(body);
    } catch (e) {
      setError(`推理失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>Financial Reasoning Engine（Phase 16）</h1>
      <p className="muted">
        可解释金融推理层：识别多证据之间的逻辑关系、隐含假设和结论跳跃。不替代 Verification；不输出投资建议。
      </p>

      {/* ① 输入 */}
      <h2>① 输入主张与证据</h2>
      <div className="card">
        <div className="form-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ flex: "2 1 280px" }}>
            主张文本（Claim）
            <textarea value={claimText} onChange={(e) => setClaimText(e.target.value)} rows={2} style={{ width: "100%" }} />
          </label>
          <label style={{ flex: "1 1 120px" }}>
            公司
            <input value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
        </div>
        <label style={{ display: "block", marginTop: 8 }}>
          证据候选（JSON 数组）
          <textarea value={evidenceJson} onChange={(e) => setEvidenceJson(e.target.value)} rows={5} style={{ width: "100%", fontFamily: "monospace", fontSize: "0.85em" }} />
        </label>
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={runReasoning} disabled={loading}>
            {loading ? "推理中…" : "启动推理"}
          </button>
          <span className="muted" style={{ fontSize: "0.85em" }}>Demo 主张：</span>
          {DEMO_CLAIMS.map((c) => (
            <button key={c} onClick={() => setClaimText(c)} style={{ fontSize: "0.8em" }}>
              {c.slice(0, 16)}…
            </button>
          ))}
        </div>
      </div>

      {error && <p className="bad">{error}</p>}

      {/* ② 推理结果展示：Claim → Premises → Supporting/Counter → Assumptions → Gap → Result */}
      {run && (
        <>
          <h2>② 推理结果（共 {run.results.length} 条）</h2>
          <div className="verdict-card" style={{ borderLeftColor: "#38bdf8" }}>
            <h3>Run {run.run_id}</h3>
            <p className="muted">规则版本：{run.rule_version} · 创建于 {run.created_at}</p>
            <p><strong>Claim：</strong>{run.claim_text}</p>
          </div>

          {run.results.length === 0 ? (
            <p className="muted">无触发结果。</p>
          ) : (
            <div>
              {run.results.map((r) => (
                <div key={r.result_id} className="semantic-card" style={{ marginBottom: 12, borderLeftColor: STATUS_COLOR[r.status] || "#64748b" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <strong>
                      {r.result_id} · {TYPE_LABEL[r.reasoning_type] || r.reasoning_type}
                    </strong>
                    <span style={{ color: STATUS_COLOR[r.status] || "#94a3b8", fontSize: "0.85em", fontWeight: 600 }}>
                      {r.status}
                    </span>
                  </div>

                  {/* Premises */}
                  {r.premises.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <strong>Premises（前提）：</strong>
                      <ul style={{ margin: "2px 0", paddingLeft: 18 }}>
                        {r.premises.map((p, i) => <li key={i} className="muted">{p}</li>)}
                      </ul>
                    </div>
                  )}

                  {/* Supporting Evidence / Counter Evidence */}
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 6 }}>
                    <div style={{ flex: "1 1 200px" }}>
                      <strong style={{ color: "#4ade80" }}>支持证据（{r.supporting_evidence.length}）</strong>
                      {r.supporting_evidence.length === 0 ? (
                        <p className="muted" style={{ fontSize: "0.85em" }}>无</p>
                      ) : (
                        <ul style={{ margin: "2px 0", paddingLeft: 18 }}>
                          {r.supporting_evidence.slice(0, 2).map((e, i) => (
                            <li key={i} className="muted" style={{ fontSize: "0.85em" }}>
                              {e.source || "?"} p{e.page || "?"}：{e.text?.slice(0, 60)}…
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div style={{ flex: "1 1 200px" }}>
                      <strong style={{ color: "#f87171" }}>反证（{r.counter_evidence.length}）</strong>
                      {r.counter_evidence.length === 0 ? (
                        <p className="muted" style={{ fontSize: "0.85em" }}>无</p>
                      ) : (
                        <ul style={{ margin: "2px 0", paddingLeft: 18 }}>
                          {r.counter_evidence.slice(0, 2).map((e, i) => (
                            <li key={i} className="muted" style={{ fontSize: "0.85em" }}>
                              {e.source || "?"} p{e.page || "?"}：{e.text?.slice(0, 60)}…
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>

                  {/* Assumptions */}
                  {r.assumptions.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <strong style={{ color: "#fbbf24" }}>隐含假设（未披露）：</strong>
                      <ul style={{ margin: "2px 0", paddingLeft: 18 }}>
                        {r.assumptions.map((a, i) => <li key={i} className="muted">{a}</li>)}
                      </ul>
                    </div>
                  )}

                  {/* Logical Gap */}
                  {r.logical_gap && (
                    <p style={{ marginBottom: 6 }}>
                      <strong style={{ color: "#f87171" }}>逻辑缺口：</strong>
                      <span className="muted">{r.logical_gap}</span>
                    </p>
                  )}

                  {/* Result: explanation + safe wording */}
                  <p><strong>可解释说明：</strong>{r.explanation}</p>
                  <p style={{ borderLeft: "3px solid #4ade80", paddingLeft: 8 }}>
                    <strong>安全措辞：</strong>{r.suggested_safe_wording}
                  </p>
                  <p className="muted" style={{ fontSize: "0.8em" }}>
                    触发规则：{r.triggered_rules.join(", ")} · 证据ID：{r.evidence_ids.length} · 置信度 {r.confidence}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* 流程图：Claim → Premises → Supporting/Counter → Assumptions → Gap → Result */}
          <h2>③ 推理流程</h2>
          <div className="semantic-card" style={{ fontSize: "0.85em" }}>
            <p>
              <strong>Claim</strong> → <strong>Premises</strong>（已识别前提） →{" "}
              <strong style={{ color: "#4ade80" }}>Supporting Evidence</strong> /{" "}
              <strong style={{ color: "#f87171" }}>Counter Evidence</strong> →{" "}
              <strong style={{ color: "#fbbf24" }}>Assumptions</strong>（隐含假设） →{" "}
              <strong style={{ color: "#f87171" }}>Logical Gap</strong>（逻辑缺口） →{" "}
              <strong>Result</strong>（reasoning_type + status + safe_wording）
            </p>
          </div>
        </>
      )}
    </main>
  );
}
