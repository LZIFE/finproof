"use client";

import { useState } from "react";

type KeyRisk = {
  claim_id: string;
  category: string;
  category_label: string;
  claim: string;
  risk_score: number;
  risk_level: string;
  risk_type: string;
  verification_status: string;
  reason: string;
};

type Review = {
  claim_id: string;
  review_status: string;
  note: string;
  reviewer: string;
  risk_score: number;
  risk_type: string;
};

type Memo = {
  id: number;
  document_id: number;
  audit_id: number;
  company: string;
  stock_code: string;
  report_period: string;
  overall_risk_score: number;
  overall_risk_level: string;
  key_risks: KeyRisk[];
  evidence_chain: { claim_id: string; claim: string; evidence: string[]; verification: string; conclusion: string }[];
  claims_requiring_review: { claim_id: string; claim: string; risk_score: number; risk_level: string; category_label: string; review_status: string }[];
  reviews: Review[];
};

const REVIEW_STYLE: Record<string, string> = {
  NEED_REVIEW: "verdict-insufficient",
  APPROVED: "verdict-supported",
  REJECTED: "verdict-refuted",
};

export default function InvestmentPage() {
  const [auditId, setAuditId] = useState("");
  const [memo, setMemo] = useState<Memo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  const generateMemo = async () => {
    if (!auditId) return;
    setLoading(true);
    setError(null);
    setMemo(null);
    try {
      const resp = await fetch("/api/v1/investment/memos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audit_id: Number(auditId) }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setMemo(body);
    } catch (e) {
      setError(`Memo 生成失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const review = async (claimId: string, status: string) => {
    if (!memo) return;
    try {
      const resp = await fetch(`/api/v1/investment/memos/${memo.id}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_id: claimId,
          review_status: status,
          note: notes[claimId] ?? "",
          reviewer: "投资经理",
        }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setMemo((m) =>
        m ? { ...m, reviews: m.reviews.map((r) => (r.claim_id === claimId ? { ...r, review_status: body.review_status, note: body.note } : r)) } : m
      );
    } catch (e) {
      setError(`审核失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const reviewStatusOf = (claimId: string) =>
    memo?.reviews.find((r) => r.claim_id === claimId)?.review_status ?? "NEED_REVIEW";

  return (
    <main className="page">
      <h1>投资尽调（Phase 7 · Investment Due Diligence Agent）</h1>
      <p>
        生成 Investment Risk Memo：AI 观点 → 证据 → 风险 → 投资经理审核。
        <b> 不输出投资建议，不自动决策</b>——只呈现风险与证据，审核权留给投资经理。
      </p>

      <div className="form-row">
        <label>
          audit_id
          <input value={auditId} onChange={(e) => setAuditId(e.target.value)} style={{ width: 120 }} />
        </label>
        <button onClick={generateMemo} disabled={!auditId || loading}>
          {loading ? "生成中…" : "生成 Investment Risk Memo"}
        </button>
      </div>
      {error && <p className="bad">{error}</p>}

      {memo && (
        <section>
          <h2>公司信息</h2>
          <p>
            <b>{memo.company}</b>（{memo.stock_code} · 报告期 {memo.report_period}）
          </p>
          <div className={`verdict-card verdict-${memo.overall_risk_level === "HIGH" ? "refuted" : memo.overall_risk_level === "MEDIUM" ? "partial" : "supported"}`}>
            <h3>
              Overall Risk Score：<strong>{memo.overall_risk_score}/100</strong>{" "}
              <span className="muted">Risk Level: {memo.overall_risk_level}</span>
            </h3>
          </div>

          <h2>Key Risks（Top 风险）</h2>
          {memo.key_risks.slice(0, 8).map((k) => (
            <div key={k.claim_id} className={`verdict-card verdict-${k.risk_level === "HIGH" ? "refuted" : k.risk_level === "MEDIUM" ? "partial" : "supported"}`}>
              <h4>
                {k.claim_id} — {k.risk_score}（{k.risk_level} · {k.category_label} · {k.risk_type}）
              </h4>
              <p>
                <b>Claim：</b>
                {k.claim}
              </p>
              <p>
                <b>核验：</b>
                {k.verification_status} — {k.reason}
              </p>
            </div>
          ))}

          <h2>待审核事项（Claims Requiring Review）</h2>
          {memo.claims_requiring_review.map((c) => {
            const status = reviewStatusOf(c.claim_id);
            return (
              <div key={c.claim_id} className={`verdict-card ${REVIEW_STYLE[status] ?? ""}`}>
                <h4>
                  {c.claim_id} — {c.risk_score}（{c.risk_level} · {c.category_label}）
                  <span className="muted"> 审核状态：{status}</span>
                </h4>
                <p>{c.claim}</p>
                <div className="form-row">
                  <input
                    placeholder="审核备注"
                    value={notes[c.claim_id] ?? ""}
                    onChange={(e) => setNotes((n) => ({ ...n, [c.claim_id]: e.target.value }))}
                    style={{ width: 260 }}
                  />
                  <button onClick={() => review(c.claim_id, "APPROVED")} disabled={status !== "NEED_REVIEW"}>
                    通过 APPROVED
                  </button>
                  <button onClick={() => review(c.claim_id, "REJECTED")} disabled={status !== "NEED_REVIEW"}>
                    驳回 REJECTED
                  </button>
                </div>
              </div>
            );
          })}

          <h2>Evidence Chain（证据链）</h2>
          {memo.evidence_chain.slice(0, 5).map((c) => (
            <div key={c.claim_id} className="semantic-card">
              <p>
                <b>{c.claim_id}</b>：{c.claim}
              </p>
              <p>
                ↓ 证据：{c.evidence.join("；") || "无"}
              </p>
              <p>
                ↓ 核验：<strong>{c.verification}</strong> — {c.conclusion}
              </p>
            </div>
          ))}
        </section>
      )}

      {!memo && !loading && <p>输入 audit_id 生成 Investment Risk Memo。</p>}
    </main>
  );
}
