"use client";

import { useState } from "react";

type AgentFlow = {
  agent: string;
  status: string;
  summary: string;
  tools_called: string[];
  timestamp: string;
};

type ResearchFindings = {
  company_overview: {
    company: string;
    stock_code: string;
    report_period: string;
    business_fields: string[];
    products: string[];
    market_coverage: string[];
  };
  business_analysis: { segments: { subject: string; statement: string }[]; growth_drivers: string[]; risks: string[] };
  financial_summary: { key_metrics: { statement: string; value: number; unit: string; period: string }[] };
};

type RiskFindings = {
  risk_score: number;
  risk_level: string;
  risk_findings: { claim_id: string; risk_score: number; risk_level: string; risk_type: string; verification_status: string }[];
  conflict_findings: { finding_id: string; claim_id: string; claim: string; fact: string; conflict_type: string; difference: string; risk_type: string; risk_score: number; risk_level: string }[];
  verification_summary: { total_claims: number; status_counts: Record<string, number> };
};

type ComplianceFindings = {
  findings: { finding_id: string; check_type: string; claim_id: string; claim_text: string; description: string; severity: string; risk_score: number }[];
  unsupported_claim_count: number;
  overstatement_count: number;
  missing_evidence_count: number;
  forecast_as_fact_count: number;
  overall_compliance_score: number;
};

type HumanReviewItem = {
  item_id: string;
  agent: string;
  review_type: string;
  claim_id: string;
  description: string;
  risk_score: number;
  risk_level: string;
  review_status: string;
  note: string;
  reviewer: string;
};

type Report = {
  id: number;
  document_id: number;
  audit_id: number | null;
  company: string;
  stock_code: string;
  report_period: string;
  agent_flow: AgentFlow[];
  agent_results: Record<string, { agent: string; status: string; summary: string; tools_called: string[] }>;
  executive_summary: {
    company: string;
    overall_risk_score: number;
    overall_risk_level: string;
    overall_compliance_score: number;
    research_summary: string;
    risk_summary: string;
    compliance_summary: string;
    key_findings: string[];
  };
  research_findings: ResearchFindings;
  risk_findings: RiskFindings;
  compliance_findings: ComplianceFindings;
  evidence_chain: { agent: string; evidence_refs: string[]; summary: string }[];
  human_review_items: HumanReviewItem[];
  overall_risk_score: number;
  overall_risk_level: string;
};

const AGENT_LABEL: Record<string, string> = {
  supervisor: "Supervisor",
  research: "Research",
  risk: "Risk",
  compliance: "Compliance",
};

const COMPLIANCE_LABEL: Record<string, string> = {
  UNSUPPORTED_CLAIM: "无证据支持",
  OVERSTATEMENT: "夸大表达",
  MISSING_EVIDENCE: "证据缺失",
  FORECAST_AS_FACT: "预测描述为事实",
};

const RISK_STYLE: Record<string, string> = {
  HIGH: "verdict-refuted",
  MEDIUM: "verdict-partial",
  LOW: "verdict-supported",
};

const REVIEW_STYLE: Record<string, string> = {
  NEED_REVIEW: "verdict-insufficient",
  APPROVED: "verdict-supported",
  REJECTED: "verdict-refuted",
};

export default function CommitteePage() {
  const [documentId, setDocumentId] = useState("1");
  const [auditId, setAuditId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const run = async () => {
    if (!documentId) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const body: Record<string, unknown> = { document_id: Number(documentId) };
      if (auditId) body.audit_id = Number(auditId);
      const resp = await fetch("/api/v1/committee/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(result));
      setReport(result);
    } catch (e) {
      setError(`委员会审核失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const review = async (itemId: string, status: string) => {
    if (!report) return;
    try {
      const resp = await fetch(`/api/v1/committee/runs/${report.id}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          item_id: itemId,
          review_status: status,
          note: notes[itemId] ?? "",
          reviewer: "投资经理",
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setReport((r) =>
        r ? { ...r, human_review_items: r.human_review_items.map((h) => (h.item_id === itemId ? { ...h, review_status: body.review_status, note: body.note } : h)) } : r
      );
    } catch (e) {
      setError(`审核失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const reviewStatusOf = (itemId: string) =>
    report?.human_review_items.find((h) => h.item_id === itemId)?.review_status ?? "NEED_REVIEW";

  return (
    <main className="page">
      <h1>投资委员会（Phase 9 · Investment Committee Multi-Agent）</h1>
      <p>
        Supervisor Agent 拆解任务 → 依次调用 Research / Risk / Compliance Agent → 汇总委员会报告。
        <b> 不输出投资建议、不自动决定买卖、保持 Human-in-the-loop。</b>
      </p>

      <div className="form-row">
        <label>
          document_id
          <input value={documentId} onChange={(e) => setDocumentId(e.target.value)} style={{ width: 120 }} />
        </label>
        <label>
          audit_id（可选）
          <input value={auditId} onChange={(e) => setAuditId(e.target.value)} style={{ width: 120 }} />
        </label>
        <button onClick={run} disabled={!documentId || loading}>
          {loading ? "审核中…" : "运行投资委员会"}
        </button>
      </div>
      {error && <p className="bad">{error}</p>}

      {!report && !loading && <p>输入 document_id（与可选 audit_id）运行多 Agent 投资委员会审核。</p>}

      {report && (
        <section>
          {/* Agent 执行流程 */}
          <h2>① Agent 执行流程（Supervisor ↓ Research ↓ Risk ↓ Compliance）</h2>
          {report.agent_flow.map((f) => (
            <div key={f.agent} className={`semantic-card ${f.status === "DONE" ? "verdict-supported" : f.status === "FAILED" ? "verdict-refuted" : "verdict-partial"}`}>
              <h4>
                {AGENT_LABEL[f.agent] || f.agent} · <span className="muted">{f.status}</span>
              </h4>
              <p>{f.summary}</p>
              <p className="muted">工具调用：{f.tools_called.join("、") || "—"}</p>
            </div>
          ))}

          {/* Executive Summary */}
          <h2>② Executive Summary（执行摘要）</h2>
          <p>
            <b>{report.executive_summary.company}</b> · Overall Risk{" "}
            <strong>{report.executive_summary.overall_risk_score}/100</strong>{" "}
            <span className="muted">{report.executive_summary.overall_risk_level}</span> ·
            Compliance <strong>{report.executive_summary.overall_compliance_score}/100</strong>
          </p>
          <div className="semantic-card">
            <p><b>Research：</b>{report.executive_summary.research_summary}</p>
            <p><b>Risk：</b>{report.executive_summary.risk_summary}</p>
            <p><b>Compliance：</b>{report.executive_summary.compliance_summary}</p>
            <p><b>关键发现：</b></p>
            <ul>
              {report.executive_summary.key_findings.map((k, i) => <li key={i}>{k}</li>)}
            </ul>
          </div>

          {/* Research Findings */}
          <h2>③ Research Findings（调研结论）</h2>
          <div className="semantic-card">
            <h4>Company Overview</h4>
            <p><b>业务领域：</b>{report.research_findings.company_overview.business_fields.join("、") || "—"}</p>
            <p><b>核心产品：</b>{report.research_findings.company_overview.products.join("、") || "—"}</p>
            <p><b>市场覆盖：</b>{report.research_findings.company_overview.market_coverage.join("、") || "—"}</p>
            <h4>Business Analysis</h4>
            <p><b>增长驱动：</b>{report.research_findings.business_analysis.growth_drivers.join("、") || "—"}</p>
            <p><b>业务风险：</b>{report.research_findings.business_analysis.risks.join("、") || "—"}</p>
            <h4>Financial Summary</h4>
            <ul>
              {report.research_findings.financial_summary.key_metrics.slice(0, 5).map((m, i) => (
                <li key={i}>{m.statement}（{m.value}{m.unit} · {m.period}）</li>
              ))}
            </ul>
          </div>

          {/* Risk Findings */}
          <h2>④ Risk Findings（风险结论）</h2>
          <div className={`verdict-card ${RISK_STYLE[report.risk_findings.risk_level]}`}>
            <h3>Risk Score：<strong>{report.risk_findings.risk_score}/100</strong> · {report.risk_findings.risk_level}</h3>
          </div>
          {report.risk_findings.risk_findings.slice(0, 5).map((r) => (
            <div key={r.claim_id} className={`verdict-card ${RISK_STYLE[r.risk_level]}`}>
              <h4>{r.claim_id} — {r.risk_type} {r.risk_score}（{r.risk_level}）</h4>
              <p className="muted">核验：{r.verification_status}</p>
            </div>
          ))}
          {report.risk_findings.conflict_findings.slice(0, 5).map((c) => (
            <div key={c.finding_id} className={`verdict-card ${RISK_STYLE[c.risk_level]}`}>
              <h4>{c.finding_id} · {c.claim_id} — {c.conflict_type}</h4>
              <p><b>Claim：</b>{c.claim}</p>
              <p><b>Fact：</b>{c.fact}</p>
              <p><b>差异：</b>{c.difference}</p>
            </div>
          ))}

          {/* Compliance Findings */}
          <h2>⑤ Compliance Findings（合规结论）</h2>
          <div className="semantic-card">
            <p>
              合规评分：<strong>{report.compliance_findings.overall_compliance_score}/100</strong> ·
              无证据支持 {report.compliance_findings.unsupported_claim_count} / 夸大表达 {report.compliance_findings.overstatement_count} /
              证据缺失 {report.compliance_findings.missing_evidence_count} / 预测为事实 {report.compliance_findings.forecast_as_fact_count}
            </p>
          </div>
          {report.compliance_findings.findings.map((f) => (
            <div key={f.finding_id} className={`verdict-card ${RISK_STYLE[f.severity]}`}>
              <h4>{f.finding_id} · {COMPLIANCE_LABEL[f.check_type] || f.check_type} — {f.severity}</h4>
              <p>{f.description}</p>
              {f.claim_text && <p className="muted">关联主张：{f.claim_text}</p>}
            </div>
          ))}

          {/* Evidence Chain */}
          <h2>⑥ Evidence Chain（证据链）</h2>
          {report.evidence_chain.map((ec) => (
            <div key={ec.agent} className="semantic-card">
              <h4>{AGENT_LABEL[ec.agent] || ec.agent} Agent</h4>
              <p>{ec.summary}</p>
              <p className="muted">证据引用：{ec.evidence_refs.join("、") || "—"}</p>
            </div>
          ))}

          {/* Human Review Items */}
          <h2>⑦ Human Review Items（人工审核项 · Human-in-the-loop）</h2>
          {report.human_review_items.length === 0 && <p className="muted">无人工审核项</p>}
          {report.human_review_items.map((h) => {
            const status = reviewStatusOf(h.item_id);
            return (
              <div key={h.item_id} className={`verdict-card ${REVIEW_STYLE[status] ?? ""}`}>
                <h4>
                  {h.item_id} · {AGENT_LABEL[h.agent] || h.agent} — {h.review_type}
                  <span className="muted"> 审核状态：{status}</span>
                </h4>
                <p>{h.description}</p>
                <p className="muted">风险 {h.risk_score}（{h.risk_level}）· 关联主张 {h.claim_id || "—"}{h.note ? ` · 备注 ${h.note}` : ""}</p>
                <div className="form-row">
                  <input
                    placeholder="审核备注"
                    value={notes[h.item_id] ?? ""}
                    onChange={(e) => setNotes((n) => ({ ...n, [h.item_id]: e.target.value }))}
                    style={{ width: 260 }}
                  />
                  <button onClick={() => review(h.item_id, "APPROVED")} disabled={status !== "NEED_REVIEW"}>
                    通过 APPROVED
                  </button>
                  <button onClick={() => review(h.item_id, "REJECTED")} disabled={status !== "NEED_REVIEW"}>
                    驳回 REJECTED
                  </button>
                </div>
              </div>
            );
          })}
        </section>
      )}
    </main>
  );
}
