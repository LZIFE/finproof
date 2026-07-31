"use client";

import { useCallback, useEffect, useState } from "react";

type Candidate = {
  rank: number;
  document_id: number;
  page_number: number;
  block_id: number | null;
  final_score: number;
  metric_score: number;
  value_score: number;
  period_score: number;
  entity_score: number;
  text_score: number;
  matched_terms: string[];
  retrieval_method: string;
  block_text: string | null;
  evidence_type: string;
  evidence_quality_score: number;
  evidence_rank_reason: string | null;
  evidence_tier: string;
};

const EVIDENCE_TYPE_LABEL: Record<string, string> = {
  PRIMARY_FINANCIAL_STATEMENT: "★★★★★ 财务报表",
  FINANCIAL_NOTE: "★★★★ 财报附注",
  BUSINESS_SEGMENT: "★★★★ 业务分部",
  MANAGEMENT_DISCUSSION: "★★★ 管理层分析",
  NARRATIVE_DISCLOSURE: "★★ 定性描述",
  UNKNOWN: "☆ 未知",
};

type RunOut = {
  id: number;
  dataset: string;
  input_mode: string;
  status: string;
  top_k: number;
  retrieval_version: string;
  claim_count: number;
  duration_ms: number;
  created_at: string;
};

type ClaimCandidates = {
  claim_id: string;
  candidates: Candidate[];
};

type ClaimsOut = {
  retrieval_run_id: number;
  claim_count: number;
  claims: ClaimCandidates[];
};

export default function EvidenceRetrievalPage() {
  const [dataset, setDataset] = useState("demo");
  const [topK, setTopK] = useState(5);
  const [runs, setRuns] = useState<RunOut[]>([]);
  const [currentRun, setCurrentRun] = useState<RunOut | null>(null);
  const [claimsOut, setClaimsOut] = useState<ClaimsOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createRun = async () => {
    setLoading(true);
    setError(null);
    setClaimsOut(null);
    setCurrentRun(null);
    try {
      const resp = await fetch("/api/v1/evidence-retrievals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input_mode: "ORACLE_GOLD", dataset, top_k: topK }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setCurrentRun(body);
      await loadClaims(body.id);
    } catch (e) {
      setError(`检索任务失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  };

  const loadClaims = useCallback(async (runId: number) => {
    try {
      const resp = await fetch(`/api/v1/evidence-retrievals/${runId}/claims`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(body));
      setClaimsOut(body);
    } catch (e) {
      setError(`加载候选失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }, []);

  useEffect(() => {
    fetch("/api/v1/evidence-retrievals").catch(() => undefined);
    // 拉取最近一次检索任务（若有）
    fetch("/api/v1/evidence-retrievals?limit=1")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((rows) => {
        if (Array.isArray(rows) && rows.length) {
          setRuns(rows);
          setCurrentRun(rows[0]);
          loadClaims(rows[0].id);
        }
      })
      .catch(() => undefined);
  }, [loadClaims]);

  const scoreColor = (s: number) =>
    s >= 0.6 ? "green" : s >= 0.4 ? "orange" : "gray";

  return (
    <main className="page">
      <h1>Evidence Retrieval（Phase 4A · Oracle 模式）</h1>
      <p className="oracle-badge">
        Oracle Evaluation Mode — Claims are from frozen gold dataset.
      </p>
      <p>
        输入冻结金标准主张（ORACLE_GOLD），输出 Top-K 财报证据候选（页码/文本块/解释分数）。本页不进行事实核验。
      </p>

      <div className="form-row">
        <label>
          数据集
          <select value={dataset} onChange={(e) => setDataset(e.target.value)}>
            <option value="demo">demo（美的集团）</option>
            <option value="holdout">holdout（五粮液）</option>
          </select>
        </label>
        <label>
          Top-K
          <input
            type="number"
            min={1}
            max={20}
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
          />
        </label>
        <button onClick={createRun} disabled={loading}>
          {loading ? "检索中…" : "创建检索任务"}
        </button>
      </div>

      {currentRun && (
        <p className="good">
          检索任务 #{currentRun.id}：{currentRun.input_mode} / {currentRun.dataset} / top_k={currentRun.top_k} / 状态{" "}
          {currentRun.status} / 主张 {currentRun.claim_count} 条 / 耗时 {currentRun.duration_ms}ms
        </p>
      )}
      {error && <p className="bad">{error}</p>}

      {claimsOut && (
        <section>
          <h2>
            主张 Top-{currentRun?.top_k ?? topK} 证据候选（{claimsOut.claims.length} 条主张有候选）
          </h2>
          {claimsOut.claims.map((c) => (
            <details key={c.claim_id} open={c.claim_id === claimsOut.claims[0]?.claim_id}>
              <summary>
                <strong>{c.claim_id}</strong>（{c.candidates.length} 个候选）
              </summary>
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>证据类型</th>
                    <th>页</th>
                    <th>块</th>
                    <th>总分</th>
                    <th>指标</th>
                    <th>数值</th>
                    <th>期间</th>
                    <th>排名原因</th>
                    <th>文本块内容</th>
                  </tr>
                </thead>
                <tbody>
                  {c.candidates.map((cd) => (
                    <tr key={`${cd.rank}-${cd.block_id}`}>
                      <td>{cd.rank}</td>
                      <td>
                        <span className={cd.evidence_tier === "primary" ? "tier-primary" : ""}>
                          {EVIDENCE_TYPE_LABEL[cd.evidence_type] ?? cd.evidence_type}
                        </span>
                        {cd.evidence_tier === "primary" && "（Primary）"}
                      </td>
                      <td>doc{cd.document_id} p{cd.page_number}</td>
                      <td>{cd.block_id ?? "-"}</td>
                      <td style={{ color: scoreColor(cd.final_score), fontWeight: 700 }}>
                        {cd.final_score.toFixed(3)}
                      </td>
                      <td>{cd.metric_score}</td>
                      <td>{cd.value_score}</td>
                      <td>{cd.period_score}</td>
                      <td className="block-text">{cd.evidence_rank_reason ?? "-"}</td>
                      <td className="block-text">{cd.block_text ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </section>
      )}

      {!claimsOut && !loading && (
        <p>点击"创建检索任务"运行 Oracle 证据检索。</p>
      )}
    </main>
  );
}
