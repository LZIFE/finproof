"use client";

import { useState } from "react";

type VerificationResult = {
  claim_id: string;
  verification_status: string;
  confidence: number;
  verification_type: string;
  matched_evidence_ids: number[];
  calculation_detail: Record<string, unknown> | null;
  reason: string;
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
};

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
            </div>
          ))}
        </section>
      )}

      {!detail && !loading && <p>输入 claim_ids 并点击"创建核验任务"。</p>}
    </main>
  );
}
