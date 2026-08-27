"use client";

import { useState } from "react";

type SourceRiskTag = {
  tag: string;
  label: string;
  severity: string;
  detail: string;
};

type SourceChainData = {
  claim: {
    claim_id: string;
    text: string;
    metric: string | null;
    value: number | null;
    unit: string | null;
    period: string | null;
    entity: string | null;
  };
  verdict: {
    status: string;
    confidence: number;
    reason: string;
    source_risk_tags: SourceRiskTag[];
  };
  evidence_chain: Array<{
    rank: number;
    source_level: string;
    source_level_label: string;
    source_level_reason: string | null;
    document_name: string | null;
    company: string | null;
    report_period: string | null;
    page_number: number | null;
    evidence_type: string;
    text: string;
    score: number;
    selected: boolean;
  }>;
  summary: {
    total_evidence: number;
    selected_count: number;
    strongest_label: string;
    weakest_label: string;
    risk_count: number;
  };
};

const LEVEL_COLOR: Record<string, string> = {
  OFFICIAL_DISCLOSURE: "#6ee7b7",
  REGULATORY_DATA: "#6ee7b7",
  THIRD_PARTY_REPORT: "#fcd34d",
  MEDIA_REPORT: "#fdba74",
  CHANNEL_CHECK: "#fdba74",
  FORECAST: "#fca5a5",
  NO_SOURCE: "#94a3b8",
};

const LEVEL_BG: Record<string, string> = {
  OFFICIAL_DISCLOSURE: "#064e3b",
  REGULATORY_DATA: "#065f46",
  THIRD_PARTY_REPORT: "#78350f",
  MEDIA_REPORT: "#7c2d12",
  CHANNEL_CHECK: "#7c2d12",
  FORECAST: "#7f1d1d",
  NO_SOURCE: "#1e293b",
};

function SourceChainCard({ claimId }: { claimId: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SourceChainData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (data) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`/api/v1/source-chain/${encodeURIComponent(claimId)}`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setData(body);
    } catch (e) {
      setError(`来源链加载失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={toggle} style={{ fontSize: "0.85em" }}>
        {open ? "▾ 收起来源链" : "▸ 查看来源链"}
      </button>

      {open && (
        <div style={{ marginTop: 10, padding: 12, background: "#0f172a", borderRadius: 8, border: "1px solid #1e293b" }}>
          {loading && <p className="muted">来源链构建中…</p>}
          {error && <p className="bad">{error}</p>}

          {data && (
            <>
              {/* 主张块 */}
              <div style={{ padding: "8px 12px", background: "#1e293b", borderRadius: 6, marginBottom: 4 }}>
                <div style={{ fontSize: "0.75em", color: "#94a3b8", marginBottom: 4 }}>📌 研报主张</div>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>{data.claim.text}</div>
                <div style={{ fontSize: "0.8em", color: "#94a3b8", display: "flex", gap: 16, flexWrap: "wrap" }}>
                  {data.claim.metric && <span>指标：{data.claim.metric}</span>}
                  {data.claim.value != null && <span>数值：{data.claim.value}{data.claim.unit || ""}</span>}
                  {data.claim.period && <span>期间：{data.claim.period}</span>}
                  {data.claim.entity && <span>主体：{data.claim.entity}</span>}
                </div>
              </div>

              <div style={{ textAlign: "center", color: "#475569", fontSize: "1.2em", lineHeight: 1 }}>↓</div>

              {/* 核验结论块 */}
              <div style={{ padding: "8px 12px", background: "#1e293b", borderRadius: 6, marginBottom: 4 }}>
                <div style={{ fontSize: "0.75em", color: "#94a3b8", marginBottom: 4 }}>🔍 核验结论</div>
                <div style={{ fontWeight: 700, color: data.verdict.status === "SUPPORTED" ? "#4ade80" : data.verdict.status === "REFUTED" ? "#f87171" : "#fbbf24" }}>
                  {data.verdict.status}（置信度 {(data.verdict.confidence * 100).toFixed(0)}%）
                </div>
                {data.verdict.source_risk_tags.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    {data.verdict.source_risk_tags.map((risk) => (
                      <span
                        key={risk.tag}
                        title={risk.detail}
                        style={{
                          display: "inline-block",
                          margin: "2px 6px 2px 0",
                          padding: "2px 8px",
                          borderRadius: 10,
                          fontSize: "0.78em",
                          fontWeight: 600,
                          cursor: "help",
                          background: risk.severity === "HIGH" ? "#7f1d1d" : "#78350f",
                          color: risk.severity === "HIGH" ? "#fca5a5" : "#fcd34d",
                        }}
                      >
                        {risk.severity === "HIGH" ? "⚠" : "△"} {risk.label}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ textAlign: "center", color: "#475569", fontSize: "1.2em", lineHeight: 1 }}>↓</div>

              {/* 证据链 */}
              <div style={{ fontSize: "0.75em", color: "#94a3b8", marginBottom: 6 }}>
                📎 证据溯源链（{data.summary.total_evidence} 条候选，{data.summary.selected_count} 条被采用 ·
                最强来源：{data.summary.strongest_label} · 最弱来源：{data.summary.weakest_label}）
              </div>
              {data.evidence_chain.map((ev) => {
                const color = LEVEL_COLOR[ev.source_level] || "#94a3b8";
                const bg = LEVEL_BG[ev.source_level] || "#1e293b";
                return (
                  <div
                    key={ev.rank}
                    style={{
                      padding: "8px 12px",
                      background: ev.selected ? "#1e293b" : "#0f172a",
                      borderRadius: 6,
                      marginBottom: 6,
                      borderLeft: `3px solid ${color}`,
                      opacity: ev.selected ? 1 : 0.6,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4, flexWrap: "wrap", gap: 6 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontWeight: 700, color }}>证据 {ev.rank}</span>
                        <span style={{
                          padding: "1px 8px",
                          borderRadius: 10,
                          fontSize: "0.9em",
                          fontWeight: 600,
                          background: bg,
                          color,
                        }}>
                          {ev.source_level_label}
                        </span>
                        {ev.selected ? (
                          <span style={{ color: "#4ade80", fontSize: "0.9em" }}>✓ 已采用</span>
                        ) : (
                          <span style={{ color: "#64748b", fontSize: "0.9em" }}>✗ 未采用</span>
                        )}
                      </div>
                      <span style={{ fontSize: "0.85em", color: "#64748b" }}>相关度 {ev.score}</span>
                    </div>
                    <div style={{ fontSize: "0.82em", color: "#94a3b8", marginBottom: 4 }}>
                      {ev.document_name && <span>📄 {ev.document_name}</span>}
                      {ev.company && <span> · {ev.company}</span>}
                      {ev.report_period && <span> · {ev.report_period}</span>}
                      {ev.page_number && <span> · P{ev.page_number}</span>}
                    </div>
                    <div style={{ fontSize: "0.88em", lineHeight: 1.5, color: "#cbd5e1" }}>
                      「{ev.text.length > 150 ? ev.text.slice(0, 150) + "…" : ev.text}」
                    </div>
                    {ev.source_level_reason && (
                      <div style={{ fontSize: "0.78em", color: "#64748b", marginTop: 4, fontStyle: "italic" }}>
                        {ev.source_level_reason}
                      </div>
                    )}
                  </div>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}

type VerificationResult = {
  claim_id: string;
  verification_status: string;
  confidence: number;
  verification_type: string;
  matched_evidence_ids: number[];
  calculation_detail: Record<string, unknown> | null;
  reason: string;
  source_risk_tags: SourceRiskTag[];
};

type VerificationRun = {
  id: number;
  mode: string;
  claim_count: number;
  status: string;
  created_at: string;
};

type Detail = {
  run: VerificationRun;
  results: VerificationResult[];
};

const STATUS_STYLE: Record<string, string> = {
  SUPPORTED: "verdict-supported",
  REFUTED: "verdict-refuted",
  PARTIALLY_SUPPORTED: "verdict-partial",
  INSUFFICIENT_EVIDENCE: "verdict-insufficient",
  UNABLE_TO_DETERMINE: "verdict-unable",
};

const TYPE_LABEL: Record<string, string> = {
  EXACT_VALUE_CHECK: "数值验证",
  GROWTH_RATE_CHECK: "增长率验证",
  PERIOD_CHECK: "期间验证",
  MULTI_EVIDENCE_CHECK: "多证据组合",
  SEMANTIC_CHECK: "语义核验",
  SEMANTIC_SUPPORT_CHECK: "语义证据充分性",
  CAUSAL_CHECK: "因果关系验证",
  COMPARISON_CHECK: "比较类验证",
  EVIDENCE_SUFFICIENCY_CHECK: "证据充分性",
};

const SEMANTIC_TYPES = new Set([
  "SEMANTIC_SUPPORT_CHECK",
  "CAUSAL_CHECK",
  "COMPARISON_CHECK",
  "EVIDENCE_SUFFICIENCY_CHECK",
]);

function SemanticEvidenceCard({ r }: { r: VerificationResult }) {
  const cd = r.calculation_detail as {
    semantic_type?: string;
    coverage?: Record<string, boolean>;
    required_desc?: string[];
    covered?: number;
    required?: number;
    has_financial_result?: boolean;
    has_disclosed_reason?: boolean;
    has_time_order?: boolean;
    has_industry_rank?: boolean;
    has_peer_data?: boolean;
  } | null;
  if (!cd) return null;
  const coverage = cd.coverage ?? {};
  const descs = cd.required_desc ?? [];
  const dims = Object.keys(coverage);
  return (
    <div className="semantic-card">
      <p>
        <b>Semantic Evidence Card</b>（{cd.semantic_type ?? "语义主张"}）
      </p>
      {dims.length > 0 && (
        <ul>
          {dims.map((d, i) => (
            <li key={d}>
              {coverage[d] ? "✓" : "✗"} {descs[i] ?? d}
            </li>
          ))}
        </ul>
      )}
      {cd.has_financial_result !== undefined && (
        <ul>
          <li>{cd.has_financial_result ? "✓" : "✗"} 财务结果（数值）</li>
          <li>{cd.has_disclosed_reason || cd.has_time_order ? "✓" : "✗"} 公司披露原因/时间顺序</li>
        </ul>
      )}
      {cd.has_industry_rank !== undefined && (
        <ul>
          <li>{cd.has_industry_rank ? "✓" : "✗"} 行业排名/市占率</li>
          <li>{cd.has_peer_data ? "✓" : "✗"} 同行业比较数据</li>
        </ul>
      )}
      <p>
        <b>结果：</b>
        <strong>{r.verification_status}</strong>（覆盖 {cd.covered}/{cd.required} 个要求维度）
      </p>
    </div>
  );
}

export default function VerificationPage() {
  const [claimIds, setClaimIds] = useState("CLM-001, CLM-004, CLM-005");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createVerification = async () => {
    setLoading(true);
    setError(null);
    setDetail(null);
    try {
      const ids = claimIds
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const resp = await fetch("/api/v1/verifications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ claim_ids: ids, mode: "RULE_BASED" }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setDetail(body);
    } catch (e) {
      setError(`核验失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const calcSummary = (d: Record<string, unknown> | null) => {
    if (!d) return null;
    const keys = ["converted_value", "calculated_growth_pp", "claimed_growth_pp", "calculated_quarter_value", "claimed_value"];
    const parts = keys.filter((k) => d[k] !== undefined).map((k) => `${k}=${d[k]}`);
    return parts.length ? parts.join(" ｜ ") : JSON.stringify(d);
  };

  return (
    <main className="page">
      <h1>金融事实核验（Phase 4B.1 · Deterministic Verification）</h1>
      <p>
        输入结构化主张 → 财报证据检索 → 确定性计算核验 → 可解释结论（SUPPORTED / REFUTED / 证据不足）。
      </p>

      <div className="form-row">
        <label>
          claim_ids（逗号分隔）
          <input
            value={claimIds}
            onChange={(e) => setClaimIds(e.target.value)}
            style={{ width: 320 }}
          />
        </label>
        <button onClick={createVerification} disabled={loading}>
          {loading ? "核验中…" : "创建核验任务"}
        </button>
      </div>
      {error && <p className="bad">{error}</p>}

      {detail && (
        <section>
          <p className="good">
            核验任务 #{detail.run.id}：mode={detail.run.mode} / status={detail.run.status} / {detail.run.claim_count} 条主张
          </p>
          {detail.results.map((r) => (
            <div key={r.claim_id} className={`verdict-card ${STATUS_STYLE[r.verification_status] ?? ""}`}>
              <h3>
                {r.claim_id} —{" "}
                <strong>{r.verification_status}</strong>{" "}
                <span className="muted">（{TYPE_LABEL[r.verification_type] ?? r.verification_type} · 置信度 {r.confidence}）</span>
              </h3>
              <p>
                <b>证据：</b>block [{r.matched_evidence_ids.join(", ") || "无"}]
              </p>
              {SEMANTIC_TYPES.has(r.verification_type) && <SemanticEvidenceCard r={r} />}
              {r.source_risk_tags && r.source_risk_tags.length > 0 && (
                <div style={{ margin: "8px 0" }}>
                  <b>来源风险：</b>
                  {r.source_risk_tags.map((risk) => (
                    <span
                      key={risk.tag}
                      title={risk.detail}
                      style={{
                        display: "inline-block",
                        margin: "2px 6px 2px 0",
                        padding: "2px 10px",
                        borderRadius: 12,
                        fontSize: "0.82em",
                        fontWeight: 600,
                        cursor: "help",
                        background: risk.severity === "HIGH" ? "#7f1d1d" : "#78350f",
                        color: risk.severity === "HIGH" ? "#fca5a5" : "#fcd34d",
                        border: `1px solid ${risk.severity === "HIGH" ? "#ef4444" : "#f59e0b"}55`,
                      }}
                    >
                      {risk.severity === "HIGH" ? "⚠" : "△"} {risk.label}
                    </span>
                  ))}
                </div>
              )}
              {calcSummary(r.calculation_detail) && (
                <p>
                  <b>计算：</b>
                  <code>{calcSummary(r.calculation_detail)}</code>
                </p>
              )}
              <p>
                <b>说明：</b>
                {r.reason}
              </p>
              <SourceChainCard claimId={r.claim_id} />
            </div>
          ))}
        </section>
      )}

      {!detail && !loading && <p>输入 claim_ids 并点击"创建核验任务"。</p>}
    </main>
  );
}
