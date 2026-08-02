"use client";

import { useState } from "react";

type Fact = {
  fact_id: string;
  dimension: string;
  subject: string;
  statement: string;
  value: number | null;
  unit: string;
  period: string;
  source: string;
  source_label: string;
  evidence: string;
  timestamp: string;
  confidence: number;
};

type Conflict = {
  finding_id: string;
  claim_id: string;
  fact_id: string;
  claim: string;
  fact: string;
  conflict_type: string;
  difference: string;
  risk_type: string;
  risk_score: number;
  risk_level: string;
  evidence_trace: { role: string; text: string; source?: string; source_label?: string; timestamp?: string; confidence?: number }[];
};

type Report = {
  id: number;
  document_id: number;
  company: string;
  stock_code: string;
  report_period: string;
  company_profile: {
    company: string;
    stock_code: string;
    business_fields: string[];
    key_financials: { statement: string; value: number; unit: string; period: string; source_label: string }[];
    market_coverage: string[];
    products: string[];
    competitors: string[];
  };
  verified_facts: Fact[];
  conflicts: Conflict[];
  risk_findings: { finding_id: string; claim_id: string; risk_type: string; risk_score: number; risk_level: string; summary: string; conflict_type: string }[];
  evidence_chain: { claim_id: string; claim: string; evidence: { role?: string; fact_id?: string; source?: string; source_label?: string; timestamp?: string; confidence?: number; text: string }[]; conflict_type: string; difference: string; risk_score: number; risk_level: string; risk_type: string }[];
  overall_risk_score: number;
  overall_risk_level: string;
  conflict_count: number;
  support_count: number;
};

const DIM_LABEL: Record<string, string> = {
  COMPANY: "公司",
  BUSINESS: "业务",
  FINANCIAL: "财务",
  MARKET: "市场",
  PRODUCT: "产品",
  COMPETITION: "竞争",
};

const SOURCE_LABEL: Record<string, string> = {
  FINANCIAL_REPORT: "财报",
  ANNOUNCEMENT: "公告",
  NEWS: "新闻",
  OFFICIAL_SITE: "官网",
};

const CONFLICT_LABEL: Record<string, string> = {
  FINANCIAL_DATA_CONFLICT: "财务数据冲突",
  BUSINESS_DESC_CONFLICT: "业务描述冲突",
  GROWTH_LOGIC_INSUFFICIENT: "增长逻辑不足",
  COMPETITIVE_EVIDENCE_MISSING: "竞争优势缺证据",
  NO_OPPOSITION: "无冲突/支持",
};

const RISK_STYLE: Record<string, string> = {
  HIGH: "verdict-refuted",
  MEDIUM: "verdict-partial",
  LOW: "verdict-supported",
};

export default function IntelligencePage() {
  const [documentId, setDocumentId] = useState("1");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const resp = await fetch("/api/v1/intelligence/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: Number(documentId),
          claims: [
            { claim_id: "INV-0001", claim: "海外业务高速增长", dimension: "MARKET", period: "2025FY" },
            { claim_id: "INV-0002", claim: "公司保持行业领先", dimension: "COMPETITION", period: "2025FY" },
            { claim_id: "INV-0003", claim: "盈利能力持续提升", dimension: "FINANCIAL", period: "2025FY" },
          ],
          external_facts: [
            { dimension: "COMPETITION", subject: "美的空调", statement: "美的空调线上线下市场份额第一", source: "NEWS", source_label: "行业第三方报告", evidence: "美的空调线上线下市场份额均位列第一。", timestamp: "2026-07-28T00:00:00Z", confidence: 0.75 },
          ],
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setReport(body);
    } catch (e) {
      setError(`投资调查失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <h1>投资情报（Phase 8 · Investment Intelligence Agent）</h1>
      <p>
        输入投资标的 → 公司公开信息与投资材料交叉验证 → 发现潜在风险。
        <b> 不开发自动投资建议、不进行股票推荐、不替代投资经理决策。</b>
      </p>

      <div className="form-row">
        <label>
          document_id
          <input value={documentId} onChange={(e) => setDocumentId(e.target.value)} style={{ width: 120 }} />
        </label>
        <button onClick={run} disabled={!documentId || loading}>
          {loading ? "调查中…" : "运行投资调查"}
        </button>
      </div>
      {error && <p className="bad">{error}</p>}

      {!report && !loading && (
        <p>输入 document_id（已注册的财报文档）运行投资调查。</p>
      )}

      {report && (
        <section>
          {/* Summary */}
          <h2>① 投资标的</h2>
          <p>
            <b>{report.company}</b>（{report.stock_code} · 报告期 {report.report_period}）
          </p>
          <div className={`verdict-card ${RISK_STYLE[report.overall_risk_level]}`}>
            <h3>
              Overall Risk：<strong>{report.overall_risk_score}/100</strong>{" "}
              <span className="muted">{report.overall_risk_level}</span>
            </h3>
            <p className="muted">
              冲突 {report.conflict_count} 条 / 支持 {report.support_count} 条 / 事实 {report.verified_facts.length} 条
            </p>
          </div>

          {/* Company Facts */}
          <h2>② Company Facts（公司事实 · Evidence First）</h2>
          {report.verified_facts.length === 0 && <p className="muted">无事实</p>}
          {report.verified_facts.slice(0, 12).map((f) => (
            <div key={f.fact_id} className="semantic-card">
              <h4>
                {f.fact_id} · {DIM_LABEL[f.dimension] || f.dimension} ·{" "}
                <span className="muted">{SOURCE_LABEL[f.source] || f.source}</span>
              </h4>
              <p>
                <b>事实：</b>
                {f.statement}
                {f.value !== null ? `（${f.value}${f.unit}）` : ""}
              </p>
              <p>
                <b>证据：</b>
                {f.evidence}
              </p>
              <p className="muted">
                来源：{f.source_label || f.source} · 时间 {f.timestamp} · 置信度 {(f.confidence * 100).toFixed(0)}%
              </p>
            </div>
          ))}

          {/* Evidence Sources */}
          <h2>③ Evidence Sources（证据来源）</h2>
          <div className="semantic-card">
            <p>
              <b>业务领域：</b>
              {report.company_profile.business_fields.join("、") || "—"}
            </p>
            <p>
              <b>核心产品：</b>
              {report.company_profile.products.join("、") || "—"}
            </p>
            <p>
              <b>市场覆盖：</b>
              {report.company_profile.market_coverage.join("、") || "—"}
            </p>
            <p>
              <b>主要竞争对手：</b>
              {report.company_profile.competitors.join("、") || "—"}
            </p>
            <p>
              <b>关键财务指标：</b>
            </p>
            <ul>
              {report.company_profile.key_financials.slice(0, 6).map((k, i) => (
                <li key={i}>
                  {k.statement}（{k.value}
                  {k.unit}·{k.period}）— 来源 {k.source_label}
                </li>
              ))}
            </ul>
          </div>

          {/* Conflict Findings */}
          <h2>④ Conflict Findings（投资观点 vs 外部事实）</h2>
          {report.conflicts.length === 0 && <p className="muted">无冲突结论</p>}
          {report.conflicts.map((c) => (
            <div
              key={c.finding_id}
              className={`verdict-card ${c.conflict_type === "NO_OPPOSITION" ? RISK_STYLE.LOW : RISK_STYLE[c.risk_level] || ""}`}
            >
              <h4>
                {c.finding_id} · {c.claim_id} —{" "}
                <strong>{CONFLICT_LABEL[c.conflict_type] || c.conflict_type}</strong>
              </h4>
              <p>
                <b>Claim：</b>
                {c.claim}
              </p>
              <p>
                <b>Fact：</b>
                {c.fact}
              </p>
              <p>
                <b>Difference：</b>
                {c.difference}
              </p>
              <p>
                <b>Risk：</b>
                {c.risk_type} · {c.risk_score}（{c.risk_level}）
              </p>
            </div>
          ))}

          {/* Risk Summary */}
          <h2>⑤ Risk Summary（风险汇总）</h2>
          {report.risk_findings.length === 0 && <p className="muted">无风险点</p>}
          {report.risk_findings.map((r) => (
            <div key={r.finding_id} className={`verdict-card ${RISK_STYLE[r.risk_level] || ""}`}>
              <h4>
                {r.finding_id} · {r.claim_id} — {r.risk_type} {r.risk_score}（{r.risk_level}）
              </h4>
              <p>
                <b>冲突类型：</b>
                {CONFLICT_LABEL[r.conflict_type] || r.conflict_type}
              </p>
              <p>{r.summary}</p>
            </div>
          ))}

          {/* Evidence Chain: Claim ↓ Evidence ↓ Conflict ↓ Risk */}
          <h2>⑥ Evidence Chain（Claim ↓ External Evidence ↓ Conflict ↓ Risk）</h2>
          {report.evidence_chain.map((ec) => (
            <div key={ec.claim_id} className="semantic-card">
              <h4>
                {ec.claim_id} — {ec.claim}
              </h4>
              {ec.evidence.map((ev, i) => (
                <p key={i}>
                  ↓ {ev.role === "claim" ? "claim" : ev.source || "fact"}：{(ev.text || "").slice(0, 120)}
                </p>
              ))}
              <p>
                ↓ <strong>{CONFLICT_LABEL[ec.conflict_type] || ec.conflict_type}</strong> · 风险 {ec.risk_score}（{ec.risk_level}）
              </p>
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
